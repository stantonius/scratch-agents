"""Linking cells to the code they came from.

A linked cell remembers a file, a symbol (`order_total`, `Order.subtotal`) and a fingerprint of that
symbol's source at the moment it was pulled in. From those three things, and nothing else, Polya can
say whether the cell and the file still agree, show the difference, and write the cell back.
No model is involved anywhere in this module.
"""
import ast, difflib, hashlib, io, re, textwrap, tokenize
from functools import lru_cache
from pathlib import Path

DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
LABELS = dict(sync='in sync', edited='edited here', disk='changed on disk', conflict='conflict', missing='not in file', new='new, not in a file yet',
              nofile='file not found')


class SourceError(ValueError): pass


def norm(s): return '\n'.join(l.rstrip() for l in (s or '').strip('\n').splitlines())


def sha(s): return hashlib.sha256(norm(s).encode()).hexdigest()[:16]


def resolve(file, project):
    "Absolute path for a link's `file` (stored relative to the project when it is inside it)."
    p = Path(file)
    return p if p.is_absolute() else Path(project or '.') / p


def relative(path, project):
    "How a path is stored in a link: relative to the project if it is inside it, else absolute."
    path = Path(path).resolve()
    if project:
        try: return str(path.relative_to(Path(project).resolve()))
        except ValueError: pass
    return str(path)


def in_project(path, project):
    if not project: return False
    try: Path(path).resolve().relative_to(Path(project).resolve()); return True
    except ValueError: return False


def module_name(path, project):
    "Dotted module name for a file inside the project, e.g. acme/orders.py -> acme.orders ('' if it cannot be one)."
    if not in_project(path, project): return ''
    parts = list(Path(path).resolve().relative_to(Path(project).resolve()).with_suffix('').parts)
    if parts and parts[-1] == '__init__': parts.pop()
    return '.'.join(parts) if parts and all(p.isidentifier() for p in parts) else ''


_NL = re.compile(r'\r\n|\r|\n')     # what Python itself treats as a line break in source


def _split(text):
    "(lines, endings): the text's lines without their line breaks, and the break each one had ('' if none)."
    lines, ends, pos = [], [], 0
    for m in _NL.finditer(text):
        lines.append(text[pos:m.start()]); ends.append(m.group()); pos = m.end()
    if pos < len(text): lines.append(text[pos:]); ends.append('')
    return lines, ends


@lru_cache(maxsize=256)
def _parsed(path, mtime):
    raw = Path(path).read_bytes()
    enc = tokenize.detect_encoding(io.BytesIO(raw).readline)[0]      # honours a BOM or a coding line
    text = raw.decode(enc)
    lines, ends = _split(text)
    used = [e for e in ends if e]
    nl = max(set(used), key=used.count) if used else '\n'             # the file's own line ending
    return dict(text=text, tree=ast.parse(raw), lines=lines, ends=ends, enc=enc, nl=nl)


def parsed(path):
    "The file as Polya needs it: text, syntax tree, lines, their endings, encoding and usual line ending."
    path = Path(path)
    if not path.is_file(): raise SourceError(f'No such file: {path}')
    try: return _parsed(str(path), path.stat().st_mtime_ns)
    except SyntaxError as e: raise SourceError(f'{path} does not parse: {e}') from None
    except (UnicodeDecodeError, LookupError) as e: raise SourceError(f'{path} could not be read as text: {e}') from None


def _walk(body, prefix=''):
    "Functions, classes and methods, including ones defined under `if`, `try`, `with` and the like (but not inside functions)."
    for n in body:
        if isinstance(n, DEFS):
            q = prefix + n.name
            yield q, n
            if isinstance(n, ast.ClassDef): yield from _walk(n.body, q + '.')
        else:
            for fld in ('body', 'orelse', 'finalbody'):
                sub = getattr(n, fld, None)
                if isinstance(sub, list): yield from _walk(sub, prefix)
            for h in getattr(n, 'handlers', []) or []: yield from _walk(h.body, prefix)
            for c in getattr(n, 'cases', []) or []: yield from _walk(c.body, prefix)


def _named(tree):
    """(name, node) pairs where a name that occurs more than once gets `#2`, `#3`, ... on its later occurrences.

    The same name can legitimately be defined several times: a property and its setter, `@overload`
    stubs, or alternatives under `if`/`else`. Each one needs its own address.
    """
    seen, out = {}, []
    for q, n in _walk(tree.body):
        seen[q] = seen.get(q, 0) + 1
        out.append((q if seen[q] == 1 else f'{q}#{seen[q]}', n))
    return out


def symbols(path):
    "Qualified names of the functions, classes and methods in a file, in order."
    return [q for q, _ in _named(parsed(path)['tree'])]


def find(path, qualname):
    "Where `qualname` is in `path`: dict(start, end, indent, source), lines 1-based inclusive, `indent` the leading whitespace. None if not there."
    f = parsed(path)
    node = next((n for q, n in _named(f['tree']) if q == qualname), None)
    if node is None: return None
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    block = f['lines'][start - 1:node.end_lineno]
    indent = block[0][:len(block[0]) - len(block[0].lstrip())]
    return dict(start=start, end=node.end_lineno, indent=indent, source=textwrap.dedent('\n'.join(block)))


def def_name(code):
    "Name of the first function or class defined at the top level of `code` ('' if there is none)."
    try: tree = ast.parse(textwrap.dedent(code))
    except SyntaxError: return ''
    return next((n.name for n in tree.body if isinstance(n, DEFS)), '')


def split_imports(code):
    """(imports, rest): the import statements a cell starts with, and the code after them.

    A cell may begin with the imports its code needs. They belong at the top of the file, not next to
    the function, so write-back handles the two parts separately.
    """
    code = norm(textwrap.dedent(code))
    try: tree = ast.parse(code)
    except SyntaxError: return [], code
    lead = []
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)): lead.append(n)
        else: break
    if not lead or len(lead) == len(tree.body): return [], code
    lines = code.splitlines()
    first = tree.body[len(lead)]
    start = min([first.lineno] + [d.lineno for d in getattr(first, 'decorator_list', [])])
    return [ast.unparse(n) for n in lead], norm('\n'.join(lines[start - 1:]))


def missing_imports(path, imports):
    "Those of `imports` (statements as text) that the file does not already have at its top level."
    if not imports: return []
    have = {ast.dump(n) for n in parsed(path)['tree'].body if isinstance(n, (ast.Import, ast.ImportFrom))}
    return [i for i in imports if ast.dump(ast.parse(i).body[0]) not in have]


def _add_imports(rows, imports, nl):
    "Insert import statements after the file's last top-level import (or its docstring, or at the top). `rows` keep their line endings."
    if not imports: return rows
    tree = ast.parse(''.join(rows) or '\n')
    last = [n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    if last: at = max(last)
    else:
        first = tree.body[0] if tree.body else None
        doc = first if isinstance(first, ast.Expr) and isinstance(getattr(first, 'value', None), ast.Constant) and isinstance(first.value.value, str) else None
        at = doc.end_lineno if doc else 0
        if not doc:
            while at < len(rows) and rows[at].startswith('#'): at += 1      # keep a shebang, coding line and header comment first
    head, tail = rows[:at], rows[at:]
    if head and not _NL.search(head[-1][-2:] or ''): head[-1] += nl
    pad = [nl] if not last and tail and tail[0].strip() else []
    return head + [i + nl for i in imports] + pad + tail


def link(path, qualname, project):
    "A new link for an existing symbol, plus its source."
    f = find(path, qualname)
    if f is None: raise SourceError(f'`{qualname}` is not defined in {path}. It has: {", ".join(symbols(path)[:40]) or "no functions or classes"}')
    return dict(file=relative(path, project), qualname=qualname, module=module_name(path, project), sha=sha(f['source']), kind='existing'), f['source']


def status(src, content, project):
    "(status, file_source) for a linked cell. Status is one of the keys of LABELS."
    if src.get('kind') == 'new': return 'new', None
    path = resolve(src['file'], project)
    try: f = find(path, src['qualname'])
    except SourceError: return 'nofile', None
    if f is None: return 'missing', None
    imports, body = split_imports(content)
    fs, cs, base = sha(f['source']), sha(body), src.get('sha')
    if fs == cs and not missing_imports(path, imports): return 'sync', f['source']
    if fs == base: return 'edited', f['source']
    if cs == base: return 'disk', f['source']
    return 'conflict', f['source']


def udiff(old, new, name):
    d = difflib.unified_diff(norm(old).splitlines(), norm(new).splitlines(), f'{name} (file)', f'{name} (cell)', lineterm='', n=3)
    return '\n'.join(d)


def _indented(code, prefix):
    "The code's lines, each given the leading whitespace `prefix` (the file's own: tabs stay tabs)."
    return [prefix + l if l.strip() else '' for l in norm(textwrap.dedent(code)).splitlines()]


def one_def(code):
    "The single function or class a file-bound cell holds (after any imports). Raises SourceError saying what is wrong otherwise."
    try: tree = ast.parse(textwrap.dedent(code))
    except SyntaxError as e: raise SourceError(f'The cell does not parse, so it was not written: {e}') from None
    body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    if len(body) == 1 and isinstance(body[0], DEFS): return body[0]
    what = 'no function or class' if not any(isinstance(n, DEFS) for n in body) else \
        f'{sum(isinstance(n, DEFS) for n in body)} functions or classes' if all(isinstance(n, DEFS) for n in body) else 'other statements besides its function or class'
    raise SourceError(f'A cell that is written to a file must hold exactly one function or class (imports may come first). This one has {what}. '
                      'Put each function in its own cell.')


def apply(src, content, project, force=False):
    """Write a linked cell back to its file. Returns (link, content).

    Only the lines of that one function or class change. Every other byte of the file is left as it
    was: its line endings (the new lines use the file's own), its encoding, its indentation style and
    whether it ends with a newline. Refuses if the file's version changed since the cell was linked
    (unless `force`), anything outside the project folder, a cell that is not exactly one function or
    class, and any result that would not parse. Imports the cell starts with are added to the file's
    import block (if not already there); the returned content is the cell without them.
    """
    path = resolve(src['file'], project)
    if not in_project(path, project): raise SourceError(f'{path} is outside the project folder, so Polya will not write to it.')
    name = one_def(content).name
    f = parsed(path)
    nl, rows = f['nl'], [l + e for l, e in zip(f['lines'], f['ends'])]
    imports, content = split_imports(content)
    imports = missing_imports(path, imports)
    if src.get('kind') == 'new':
        after, indent, at = src.get('after') or '', '', len(rows)
        if after:
            t = find(path, after)
            if t is None: raise SourceError(f'`{after}` (the function this was to go after) is no longer in {path}. Choose the place again.')
            indent, at = t['indent'], t['end']
        while at > 0 and at <= len(rows) and not rows[at - 1].strip(): at -= 1     # do not stack blank lines
        if at > 0 and not _NL.search(rows[at - 1][-2:]): rows[at - 1] += nl          # the file did not end with a newline
        gap = [] if at == 0 else [nl] if indent else [nl, nl]
        code = [r + nl for r in _indented(content, indent)]
        tail = rows[at:] if any(r.strip() for r in rows[at:]) else []                # at the very end, leave no stray blank lines
        rows = rows[:at] + gap + code + tail
        qual = (after.split('#')[0].rsplit('.', 1)[0] + '.' if indent and '.' in after else '') + name
    else:
        t = find(path, src['qualname'])
        if t is None: raise SourceError(f'`{src["qualname"]}` is no longer in {path}.')
        if not force and sha(t['source']) != src.get('sha'):
            raise SourceError(f'{path} changed since this cell was linked. Look at the diff, then revert the cell or apply again to overwrite the file.')
        code = [r + nl for r in _indented(content, t['indent'])]
        if t['end'] == len(rows) and not f['ends'][-1]: code[-1] = code[-1][:-len(nl)]    # keep "no newline at end of file"
        rows = rows[:t['start'] - 1] + code + rows[t['end']:]
        base = src['qualname'].split('#')[0]
        qual = src['qualname'] if base.rsplit('.', 1)[-1] == name else (base.rsplit('.', 1)[0] + '.' if '.' in base else '') + name
    rows = _add_imports(rows, imports, nl)
    out = ''.join(rows)
    try: ast.parse(out)
    except SyntaxError as e: raise SourceError(f'Writing this would leave {path} unparseable ({e}), so nothing was written.') from None
    with open(path, 'w', encoding=f['enc'], newline='') as fh: fh.write(out)       # newline='': write the endings exactly as built
    return dict(file=src['file'], qualname=qual, module=src.get('module') or module_name(path, project), sha=sha(content), kind='existing'), content
