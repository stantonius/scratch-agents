"""Dialog tools, as seen from inside a dialog's kernel.

These are preloaded into every kernel, so you can call them from a code message.
The AI gets the very same tools when you mention them as &`add_msg` (or tick
"AI can edit dialog"). Each one is a thin call to the Polya server, which owns the dialog.
"""
import json, os, urllib.error, urllib.request

from fastcore.funccall import call_func

__all__ = ['add_msg', 'update_msg', 'del_msg', 'read_msg', 'find_msgs', 'view_dlg', 'run_msg', 'msg_str_replace', 'tool_info']


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
    names = ', '.join(n for n in __all__ if n != 'tool_info')
    return add_msg(f"Tools available to the AI from here on: &`[{names}]`")
