"""Server-side implementations of the dialog tools.

`polya.helper` holds the public signatures and docs (that is what the AI's tool schemas are built
from, and what you call from a code message). Both routes end up here, acting on the live dialog.
"""
from fastcore.funccall import get_schema

from . import helper
from .dialogs import MSG_TYPES, reply

NAMES = [n for n in helper.__all__ if n != 'tool_info']


def schemas(names=NAMES):
    return [{'type': 'function', 'function': get_schema(getattr(helper, n), pname='parameters')} for n in names]


def _msg(s, id):
    try: return s.dlg.msg(id)
    except Exception: raise ValueError(f'No message with id {id!r}. Use view_dlg to see the ids.') from None


async def add_msg(s, origin, content, msg_type='note', after='', before='', run=False):
    if msg_type not in MSG_TYPES: raise ValueError(f'msg_type must be one of {MSG_TYPES}')
    if before: kw = dict(before=_msg(s, before))
    else:
        anchor = after or s.cursor_id or s.current_id
        kw = dict(after=_msg(s, anchor)) if anchor and s.has(anchor) else {}
    m = s.dlg.mk_message(content, msg_type=msg_type, **kw)
    if not after and not before: s.cursor_id = m.id
    s.changed(m)
    if run and msg_type == 'code': return f'Added message {m.id}. Output:\n{await run_msg(s, origin, m.id)}'
    return m.id


async def update_msg(s, origin, id, content=None, msg_type=None, hidden=None, pinned=None):
    m = _msg(s, id)
    if msg_type is not None:
        if msg_type not in MSG_TYPES: raise ValueError(f'msg_type must be one of {MSG_TYPES}')
        if msg_type != m.msg_type: m.msg_type = msg_type
    if content is not None: m.content = content
    if hidden is not None: m.skipped = int(bool(hidden))
    if pinned is not None: m.pinned = int(bool(pinned))
    s.changed(m)
    return f'Updated message {m.id}'


async def del_msg(s, origin, id):
    m = _msg(s, id)
    if m.id == s.current_id: raise ValueError('That message is running right now; it cannot be deleted.')
    s.remove(m)
    return f'Deleted message {id}'


async def read_msg(s, origin, id):
    m = _msg(s, id)
    res = f'<{m.msg_type} id="{m.id}">\n{m.view(nums=True)}\n</{m.msg_type}>'
    if m.msg_type == 'code' and m.output: res += f'\n<output>\n{m.ai_output}\n</output>'
    if m.msg_type == 'prompt' and reply(m): res += f'\n<reply>\n{reply(m)}\n</reply>'
    return res


async def find_msgs(s, origin, pattern='', msg_type=None):
    found = s.dlg.find_msgs(pattern, msg_type=msg_type)
    return '\n'.join(m.preview(maxlen=160) for m in found) or 'No messages match.'


async def view_dlg(s, origin): return s.dlg.summary(maxlen=160) or '(the dialog is empty)'


async def msg_str_replace(s, origin, id, old_str, new_str):
    m = _msg(s, id)
    n = m.content.count(old_str)
    if n != 1: raise ValueError(f'old_str occurs {n} times in message {id}; it must occur exactly once.')
    diff = m.str_replace(old_str, new_str)
    s.changed(m)
    return str(diff)


async def run_msg(s, origin, id):
    m = _msg(s, id)
    if m.msg_type != 'code': raise ValueError(f'Message {id} is a {m.msg_type} message; only code messages can be run.')
    if origin == 'kernel':
        # Called from a running code message: the kernel is busy with that cell, so run this one afterwards.
        s.queue_run(m)
        return f'Message {id} is queued and will run when the current message finishes.'
    await s.exec_code(m)
    return m.ai_output or '(no output)'


IMPL = dict(add_msg=add_msg, update_msg=update_msg, del_msg=del_msg, read_msg=read_msg, find_msgs=find_msgs,
            view_dlg=view_dlg, msg_str_replace=msg_str_replace, run_msg=run_msg)


async def call(s, origin, name, args):
    if name not in IMPL: raise ValueError(f'Unknown dialog tool {name!r}')
    return await IMPL[name](s, origin, **{k: v for k, v in (args or {}).items() if v is not None})
