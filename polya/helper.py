"""Dialog tools, as seen from inside a dialog's kernel.

These are preloaded into every kernel, so you can call them from a code message.
The AI gets the very same tools when you mention them as &`add_msg` (or tick
"AI can edit dialog"). Each one is a thin call to the Polya server, which owns the dialog.
"""
import json, os, urllib.error, urllib.request

from fastcore.funccall import call_func

DIALOG_TOOLS = ['add_msg', 'update_msg', 'del_msg', 'read_msg', 'find_msgs', 'view_dlg', 'run_msg', 'msg_str_replace']
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
    run: bool = False,       # For a code message: run it straight away and return its output too?
) -> str:  # The new message's id, and its output if `run`
    "Add a message to the dialog. Messages added one after another keep their order."
    return _api('add_msg', content=content, msg_type=msg_type, after=after, before=before, run=run)


def update_msg(
    id: str,               # Id of the message to change
    content: str = None,   # New content (omit to keep)
    msg_type: str = None,  # New type: 'note', 'code', 'prompt' or 'raw' (omit to keep)
    hidden: bool = None,   # True hides the message from the AI, False shows it (omit to keep)
    pinned: bool = None,   # True keeps the message in the AI's context even in very long dialogs (omit to keep)
) -> str:  # Confirmation
    "Change an existing message's content, type, or hidden/pinned flags."
    return _api('update_msg', id=id, content=content, msg_type=msg_type, hidden=hidden, pinned=pinned)


def del_msg(
    id: str,  # Id of the message to delete
) -> str:  # Confirmation
    "Delete a message from the dialog."
    return _api('del_msg', id=id)


def read_msg(
    id: str,  # Id of the message to read
) -> str:  # The message as XML: its content, plus its output (code) or reply (prompt)
    "Read one message in full, with line numbers."
    return _api('read_msg', id=id)


def find_msgs(
    pattern: str = '',     # Regex to search message content for ('' matches every message)
    msg_type: str = None,  # Only this type: 'note', 'code', 'prompt' or 'raw'
) -> str:  # One line per match: `id:type:start of content`
    "Find messages whose content matches `pattern`."
    return _api('find_msgs', pattern=pattern, msg_type=msg_type)


def view_dlg() -> str:  # One line per message: `id:type:start of content`
    "Outline of the whole dialog, in order."
    return _api('view_dlg')


def msg_str_replace(
    id: str,       # Id of the message to edit
    old_str: str,  # Text to replace; must occur exactly once in the message
    new_str: str,  # Replacement text
) -> str:  # A diff of the change
    "Replace one exact occurrence of `old_str` with `new_str` in a message."
    return _api('msg_str_replace', id=id, old_str=old_str, new_str=new_str)


def run_msg(
    id: str,  # Id of the code message to run
) -> str:  # The message's output as text
    "Run a code message in the dialog's kernel and return its output."
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
    else: raise NameError(f"`{first}` is not defined in the kernel yet. Run the cell that imports or defines it first.")
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
