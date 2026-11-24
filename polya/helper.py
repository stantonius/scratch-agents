"""Dialog tools, as seen from inside a dialog's kernel.

These are preloaded into every kernel, so you can call them from a code message.
The AI gets the very same tools when you mention them as &`add_msg` (or tick
"AI can edit dialog"). Each one is a thin call to the Polya server, which owns the dialog.
"""
import json, os, urllib.error, urllib.request

from fastcore.funccall import call_func

DIALOG_TOOLS = ['add_msg', 'update_msg', 'del_msg', 'read_msg', 'find_msgs', 'view_dlg', 'run_msg', 'msg_str_replace', 'list_dialogs', 'add_source']
__all__ = DIALOG_TOOLS + ['tool_info', 'source_of', 'sandbox_dirs', 'sandbox_cmds', 'sandbox_allow']


def _api(name, **args):
    req = urllib.request.Request(
        f"{os.environ['POLYA_URL']}/api/tool",
        data=json.dumps(dict(dialog=os.environ['POLYA_DIALOG'], name=name, args=args)).encode(),
        headers={'Content-Type': 'application/json', 'X-Polya-Token': os.environ['POLYA_TOKEN']})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the server is local: never use a proxy
    try:
        with opener.open(req, timeout=600) as r: res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: res = json.loads(e.read())
        except Exception: raise RuntimeError(f'Polya server error {e.code}') from None
    if res.get('error'): raise ValueError(res['error'])
    return res['result']


async def _call_tool(name, args):
    "Used by the server to run an AI tool call in this kernel."
    import inspect
    from IPython import get_ipython
    res = call_func(name, args, ns=get_ipython().user_ns)
    if inspect.isawaitable(res): res = await res
    return res if isinstance(res, str) else repr(res)


def add_msg(
    content: str,            # Text of the new message
    msg_type: str = 'note',  # 'note', 'code', 'prompt' or 'raw'
    after: str = '',         # Id of the message to put it after (default: after the message that is running now)
    before: str = '',        # Id of the message to put it before (instead of `after`)
    run: bool = False,       # For a code message: run it straight away and return its output too? (Only in the dialog you are in)
    dialog: str = '',        # Another dialog in this folder to add to, by name (see list_dialogs). Default: the dialog you are in
) -> str:  # The new message's id, and its output if `run`
    "Add a message to a dialog. Messages added one after another keep their order. In another dialog it goes to the end unless you give `after` or `before`."
    return _api('add_msg', content=content, msg_type=msg_type, after=after, before=before, run=run, dialog=dialog)


def update_msg(
    id: str,               # Id of the message to change
    content: str = None,   # New content (omit to keep)
    msg_type: str = None,  # New type: 'note', 'code', 'prompt' or 'raw' (omit to keep)
    hidden: bool = None,   # True hides the message from the AI, False shows it (omit to keep)
    pinned: bool = None,   # True keeps the message in the AI's context even in very long dialogs (omit to keep)
    dialog: str = '',      # Another dialog in this folder that holds the message. Default: the dialog you are in
) -> str:  # Confirmation
    "Change an existing message's content, type, or hidden/pinned flags."
    return _api('update_msg', id=id, content=content, msg_type=msg_type, hidden=hidden, pinned=pinned, dialog=dialog)


def del_msg(
    id: str,           # Id of the message to delete
    dialog: str = '',  # Another dialog in this folder that holds the message. Default: the dialog you are in
) -> str:  # Confirmation
    "Delete a message from a dialog."
    return _api('del_msg', id=id, dialog=dialog)


def read_msg(
    id: str,           # Id of the message to read
    dialog: str = '',  # Another dialog in this folder that holds the message. Default: the dialog you are in
) -> str:  # The message as XML: its content, plus its output (code) or reply (prompt)
    "Read one message in full, with line numbers."
    return _api('read_msg', id=id, dialog=dialog)


def find_msgs(
    pattern: str = '',     # Regex to search message content for ('' matches every message)
    msg_type: str = None,  # Only this type: 'note', 'code', 'prompt' or 'raw'
    dialog: str = '',      # Another dialog in this folder to search. Default: the dialog you are in
) -> str:  # One line per match: `id:type:start of content`
    "Find messages whose content matches `pattern`."
    return _api('find_msgs', pattern=pattern, msg_type=msg_type, dialog=dialog)


def view_dlg(
    dialog: str = '',  # Another dialog in this folder to look at. Default: the dialog you are in
) -> str:  # One line per message: `id:type:start of content`
    "Outline of a whole dialog, in order."
    return _api('view_dlg', dialog=dialog)


def add_source(
    symbol: str,       # A function, class or method. With `file`: its name in that file, e.g. `order_total` or `Order.subtotal`. Without: a dotted import path, e.g. `acme.orders.order_total`
    file: str = '',    # The .py file that defines it, relative to the project folder, e.g. `acme/orders.py`. Give this whenever you know it
    after: str = '',   # Id of the message to put it after (default: after the message that is running now)
    dialog: str = '',  # Another dialog in this folder to add to. Default: the dialog you are in
) -> str:  # The new message's id
    "Bring a function, class or method from the codebase into the dialog as a linked code message. The code is copied from the file exactly as it is (do not retype project code with add_msg), and the message stays linked to the file so changes can be tracked and written back."
    return _api('add_source', symbol=symbol, file=file, after=after, dialog=dialog)


def list_dialogs() -> str:  # One dialog name per line
    "Names of the dialogs in this folder. Pass one as `dialog` to the other tools to read or edit it."
    return _api('list_dialogs')


def msg_str_replace(
    id: str,       # Id of the message to edit
    old_str: str,  # Text to replace; must occur exactly once in the message
    new_str: str,  # Replacement text
    dialog: str = '',  # Another dialog in this folder that holds the message. Default: the dialog you are in
) -> str:  # A diff of the change
    "Replace one exact occurrence of `old_str` with `new_str` in a message."
    return _api('msg_str_replace', id=id, old_str=old_str, new_str=new_str, dialog=dialog)


def run_msg(
    id: str,  # Id of the code message to run
) -> str:  # The message's output as text
    "Run a code message in this dialog's kernel and return its output. Code in other dialogs cannot be run from here."
    return _api('run_msg', id=id)


def tool_info():
    "Add a note that gives the AI the dialog tools from that point on."
    names = ', '.join(DIALOG_TOOLS)
    return add_msg(f"Tools available to the AI from here on: &`[{names}]`")


# ---------------------------------------------------------------- looking up definitions
def _resolve(name, ctx=''):
    "The object `name` (dotted) refers to: looked up in module `ctx` first (if given), then the kernel namespace."
    import builtins, sys
    from IPython import get_ipython
    first, *rest = name.split('.')
    spaces = ([vars(sys.modules[ctx])] if ctx and ctx in sys.modules else []) + [get_ipython().user_ns, vars(builtins)]
    for ns in spaces:
        if first in ns:
            obj = ns[first]
            break
    else:
        # Not a name the notebook has: try it as a module path, e.g. `acme.orders.order_total`.
        import importlib
        parts, obj = name.split('.'), None
        for i in range(len(parts), 0, -1):
            try: obj = importlib.import_module('.'.join(parts[:i]))
            except Exception: continue
            rest = parts[i:]
            break
        if obj is None: raise NameError(f"`{first}` is not defined in the kernel and is not an importable module. Run the cell that imports or defines it first.")
    for r in rest: obj = getattr(obj, r)
    return obj


def _definition(name, ctx=''):
    "Where `name` is defined and its source, for the go-to-definition panel."
    import inspect, textwrap
    obj = _resolve(name, ctx)
    if inspect.ismodule(obj): kind = 'module'
    elif inspect.isclass(obj): kind = 'class'
    elif inspect.isroutine(obj) or isinstance(obj, property): kind = 'function'
    else: kind = 'value'
    target = obj.fget if isinstance(obj, property) else (type(obj) if kind == 'value' else obj)
    if kind == 'function': target = inspect.unwrap(target)
    d = dict(name=name, kind=kind, qualname=getattr(target, '__qualname__', getattr(target, '__name__', name)),
             module=target.__name__ if kind == 'module' else (getattr(target, '__module__', '') or ''),
             doc=(inspect.getdoc(target) or '')[:2000], signature='', file='', line=0, source='', note='')
    if kind == 'value': d['note'] = f'`{name}` is a value of type {type(obj).__name__}: {repr(obj)[:200]}. Showing the definition of its type.'
    if kind != 'module':
        try: d['signature'] = str(inspect.signature(target))
        except (TypeError, ValueError): pass
    try:
        d['file'] = inspect.getsourcefile(target) or ''
        lines, start = inspect.getsourcelines(target)
        d['line'] = start or 1
        if len(lines) > 1500: lines = lines[:1500] + ['# ... truncated ...\n']
        d['source'] = textwrap.dedent(''.join(lines))
    except (TypeError, OSError):
        d['note'] = (d['note'] + ' ' if d['note'] else '') + 'No Python source is available for this (it is built in or compiled).'
    return d


def source_of(
    name: str,  # Dotted name as you would write it in a code message, e.g. `mypkg.orders.total` or `df.merge`
) -> str:  # The file and line where it is defined, then its source code
    "Source code of a function, class or module that the kernel can see, exactly as it is imported right now."
    d = _definition(name)
    head = f"# {d['qualname']}{d['signature']}  --  {d['file'] or 'no file'}:{d['line']}"
    body = d['source'] or d['note']
    return head + '\n' + (body if len(body) <= 12000 else body[:12000] + '\n# ... truncated ...')


# ---------------------------------------------------------------- the sandbox for the AI's own code
# When "AI can run code" is on, the AI gets a `python` tool and a `bash` tool. Both run here, in this
# kernel, so they see your variables and libraries -- but through Answer.AI's safepyrun and safecmd:
#   python: no network, no subprocesses, writes only under the folders below
#   bash:   only the commands below, output redirects only to the folders below
# These guard against an AI that is mistaken or misled. They are not a security boundary against
# code written to escape them. Widen them from your SETUP dialog with the three functions below.
SANDBOX_CMDS = """cat, head, tail, ls, tree, grep, rg, fgrep, egrep, cut, sort, uniq, wc, tr, column, file, stat, du, df, which, type,
diff, cmp, comm, date, whoami, hostname, uname, echo, printf, seq, basename, dirname, realpath, jq, fd,
git blame, git branch, git cat-file, git describe, git diff, git log, git ls-files, git ls-tree, git merge-base, git remote,
git rev-parse, git shortlog, git show, git stash list, git status, git tag,
xargs:exec=$0, tee:dest=$0, find:-delete|-ok|-okdir:exec=-exec|-execdir, rg:--pre, cd, pwd, test, [, true, false"""
_sbx = dict(py=None, dirs=['/tmp'], cmds=SANDBOX_CMDS)


def sandbox_dirs(*paths: str) -> list:
    "Also let the AI's sandboxed tools write under these folders (it can always write under /tmp). Returns the full list."
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if p not in _sbx['dirs']: _sbx['dirs'].append(p)
    _sbx['py'] = None
    return list(_sbx['dirs'])


def sandbox_cmds(*cmds: str) -> str:
    "Also let the AI's `bash` tool run these commands, e.g. sandbox_cmds('pytest', 'curl'). Returns the full allowlist."
    for c in cmds:
        if c.strip(): _sbx['cmds'] += ', ' + c.strip()
    return _sbx['cmds']


def sandbox_allow(*args):
    "Trust these callables inside the AI's `python` tool, so they may use the network, subprocesses or files (see safepyrun's `allow`)."
    from pyskills import allow
    return allow(*args)


async def _sandbox_run(kind, code):
    "Run the AI's `code` in the sandbox: {'result': text}, {'blocked': reason} or {'error': text}."
    import asyncio, contextlib, io
    lim = 6000
    try:
        if kind == 'bash':
            import safecmd
            rc, out = await asyncio.wait_for(asyncio.to_thread(
                safecmd.safe_run, code, cmds=_sbx['cmds'], dests=', '.join(_sbx['dirs'] + ['/dev/null']), ignore_ex=True), 300)
            text = (out or '').rstrip() + ('' if rc == 0 else f'\n[exit code {rc}]')
        else:
            if _sbx['py'] is None:
                from IPython import get_ipython
                from safepyrun import RunPython
                _sbx['py'] = RunPython(g=get_ipython().user_ns, ok_dests=list(_sbx['dirs']))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf): res = await _sbx['py'](code)
            text = buf.getvalue() + ('' if res is None else repr(res))
        text = text.strip() or '(no output)'
        return dict(result=text if len(text) <= lim else text[:lim] + f'… [truncated, {len(text) - lim} more chars]')
    except PermissionError as e: return dict(blocked=str(e).split('\nCall chain')[0][:400])
    except asyncio.TimeoutError: return dict(error='Timed out after 300 seconds.')
    except Exception as e:
        if type(e).__name__ in ('DisallowedCmd', 'DisallowedDest'):
            what = 'command is not on the allowlist' if type(e).__name__ == 'DisallowedCmd' else 'output destination is not an allowed folder'
            return dict(blocked=f'{what}: {e}')
        import traceback
        return dict(error=''.join(traceback.format_exception_only(type(e), e)).strip()[:2000])


# ---------------------------------------------------------------- running a linked cell inside its module
def _loaded_copies(module, qualname):
    "Every function or class object in the loaded program that is `module`'s `qualname`, wherever it is referenced from."
    import inspect, sys
    from IPython import get_ipython
    found = {}
    for d in [getattr(m, '__dict__', None) for m in list(sys.modules.values())] + [get_ipython().user_ns]:
        if not isinstance(d, dict): continue
        for v in list(d.values()):
            if (inspect.isfunction(v) or inspect.isclass(v)) and getattr(v, '__module__', None) == module and getattr(v, '__qualname__', None) == qualname:
                found[id(v)] = v
    return list(found.values())


def _module_namespaces(mod):
    "Every globals dict in use by `mod`'s functions and methods: normally just the module's own, plus stale copies."
    import inspect
    seen = {id(mod.__dict__): mod.__dict__}

    def note(f):
        f = getattr(f, '__func__', f)
        f = getattr(f, 'fget', f) if isinstance(f, property) else f
        g = getattr(f, '__globals__', None)
        if isinstance(g, dict) and g.get('__name__') == mod.__name__: seen.setdefault(id(g), g)
    for v in list(mod.__dict__.values()):
        if inspect.isfunction(v): note(v)
        elif inspect.isclass(v) and v.__module__ == mod.__name__:
            for m in list(vars(v).values()): note(m)
    return list(seen.values())


def _run_in_module(module, qualname, code):
    """Run a cell that is linked to `module`'s `qualname` as if it were still in that file.

    The code sees the module's own imports, constants and helpers. The definition it produces replaces
    the loaded one *in place*, so every caller in the package uses it straight away. Memory only: the
    file is not touched.
    """
    import importlib, linecache, sys, textwrap
    from IPython import get_ipython
    from IPython.extensions.autoreload import update_generic
    try: mod = importlib.import_module(module)
    except Exception as e: raise ImportError(f'Could not import {module} to run this cell in it: {type(e).__name__}: {e}') from None
    code = textwrap.dedent(code)
    fname = f'<polya {module}:{qualname}>'
    linecache.cache[fname] = (len(code), None, code.splitlines(True), fname)   # so tracebacks show these lines
    made = {}
    exec(compile(code, fname, 'exec'), mod.__dict__, made)
    defs = {k: v for k, v in made.items() if callable(v) or isinstance(v, (property, staticmethod, classmethod))}
    if not defs:
        mod.__dict__.update(made)
        return f'Ran in {module} (memory only). It defined no function or class.'
    *owner, _ = qualname.split('.')
    holder = mod
    for part in owner: holder = getattr(holder, part)
    # Every loaded copy of the thing being replaced. Usually there is one. After autoreload has patched a module
    # there can be two: the module's, and an older object that other files imported and still call.
    holders = [holder] + [c for c in _loaded_copies(module, '.'.join(owner)) if c is not holder] if owner else [mod]
    notes, bound, spaces = [], {k: v for k, v in made.items() if k not in defs}, _module_namespaces(mod)
    for name, new in defs.items():
        olds = [h.__dict__.get(name) for h in holders] + ([] if owner else _loaded_copies(module, name))
        olds = list({id(o): o for o in olds if o is not None and type(o) is type(new)}.values())
        for old in olds:
            try: update_generic(old, new)      # same trick as autoreload: callers keep their reference, the behaviour changes
            except Exception: olds = []
            g = getattr(getattr(old, '__func__', old), '__globals__', None)
            if isinstance(g, dict) and all(g is not sp for sp in spaces): spaces.append(g)
        if not olds:
            for h in holders: setattr(h, name, new)
            if 'super()' in code and owner: notes.append(f'{name} uses super() with no arguments, which only works once it is written to the file')
        if not owner:
            bound[name] = getattr(mod, name)
            get_ipython().user_ns[name] = bound[name]
    # New names (imports the cell brought, functions it added) must land wherever these functions look them up.
    for ns in spaces: ns.update(bound)
    where = f"{module}.{'.'.join(owner) + '.' if owner else ''}"
    return f"{', '.join(where + n for n in defs)} now runs this version, here and for every caller in the package. Memory only: the file is unchanged." + \
           (' Note: ' + '; '.join(notes) + '.' if notes else '')
