"""Linking cells to the code they came from.

A linked cell remembers a file, a symbol (`order_total`, `Order.subtotal`) and a fingerprint of that
symbol's source at the moment it was pulled in. From those three things, and nothing else, Polya can
say whether the cell and the file still agree, show the difference, and write the cell back.
No model is involved anywhere in this module.
"""
import ast, difflib, hashlib, textwrap
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


@lru_cache(maxsize=256)
def _parsed(path, mtime):
    text = Path(path).read_text(encoding='utf8')
    return text, ast.parse(text)


def parsed(path):
    path = Path(path)
    if not path.is_file(): raise SourceError(f'No such file: {path}')
    try: return _parsed(str(path), path.stat().st_mtime_ns)
    except SyntaxError as e: raise SourceError(f'{path} does not parse: {e}') from None


def _walk(body, prefix=''):
    for n in body:
        if isinstance(n, DEFS):
            q = prefix + n.name
            yield q, n
            if isinstance(n, ast.ClassDef): yield from _walk(n.body, q + '.')


def symbols(path):
    "Qualified names of the functions, classes and methods in a file, in order."
    return [q for q, _ in _walk(parsed(path)[1].body)]


def find(path, qualname):
    "Where `qualname` is in `path`: dict(start, end, indent, source), lines 1-based inclusive. None if it is not there."
    text, tree = parsed(path)
    node = next((n for q, n in _walk(tree.body) if q == qualname), None)
    if node is None: return None
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    lines = text.splitlines()
    block = lines[start - 1:node.end_lineno]
    indent = len(block[0]) - len(block[0].lstrip())
    return dict(start=start, end=node.end_lineno, indent=indent, source=textwrap.dedent('\n'.join(block)))


def def_name(code):
    "Name of the first function or class defined at the top level of `code` ('' if there is none)."
    try: tree = ast.parse(textwrap.dedent(code))
    except SyntaxError: return ''
    return next((n.name for n in tree.body if isinstance(n, DEFS)), '')


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
    fs, cs, base = sha(f['source']), sha(content), src.get('sha')
    if fs == cs: return 'sync', f['source']
    if fs == base: return 'edited', f['source']
    if cs == base: return 'disk', f['source']
    return 'conflict', f['source']


def udiff(old, new, name):
    d = difflib.unified_diff(norm(old).splitlines(), norm(new).splitlines(), f'{name} (file)', f'{name} (cell)', lineterm='', n=3)
    return '\n'.join(d)


def _indented(code, n):
    pad = ' ' * n
    return [pad + l if l.strip() else '' for l in norm(textwrap.dedent(code)).splitlines()]


def apply(src, content, project, force=False):
    """Write a linked cell back to its file. Returns the updated link.

    Refuses if the file's version changed since the cell was linked (unless `force`), and refuses
    anything outside the project folder.
    """
    path = resolve(src['file'], project)
    if not in_project(path, project): raise SourceError(f'{path} is outside the project folder, so Polya will not write to it.')
    try: ast.parse(textwrap.dedent(content))
    except SyntaxError as e: raise SourceError(f'The cell does not parse, so it was not written: {e}') from None
    text, _ = parsed(path)
    lines = text.splitlines()
    if src.get('kind') == 'new':
        after, indent, at = src.get('after') or '', 0, len(lines)
        if after:
            f = find(path, after)
            if f is None: raise SourceError(f'`{after}` (the function this was to go after) is no longer in {path}. Choose the place again.')
            indent, at = f['indent'], f['end']
        gap = [''] if indent else ['', '']
        while at > 0 and at <= len(lines) and not lines[at - 1].strip(): at -= 1     # do not stack blank lines
        new = lines[:at] + gap + _indented(content, indent) + lines[at:]
        if at >= len(lines): new = lines[:at] + (gap if lines[:at] else []) + _indented(content, indent)
        name = def_name(content)
        qual = (after.rsplit('.', 1)[0] + '.' if indent and '.' in after else '') + name if name else ''
    else:
        f = find(path, src['qualname'])
        if f is None: raise SourceError(f'`{src["qualname"]}` is no longer in {path}.')
        if not force and sha(f['source']) != src.get('sha'):
            raise SourceError(f'{path} changed since this cell was linked. Look at the diff, then revert the cell or apply again to overwrite the file.')
        new = lines[:f['start'] - 1] + _indented(content, f['indent']) + lines[f['end']:]
        name = def_name(content)
        qual = (src['qualname'].rsplit('.', 1)[0] + '.' if '.' in src['qualname'] else '') + name if name else src['qualname']
    Path(path).write_text('\n'.join(new) + '\n', encoding='utf8')
    return dict(file=src['file'], qualname=qual or src.get('qualname', ''), module=src.get('module') or module_name(path, project), sha=sha(content), kind='existing')
