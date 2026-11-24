"""Server-side implementations of the dialog tools.

`polya.helper` holds the public signatures and docs (that is what the AI's tool schemas are built
from, and what you call from a code message). Both routes end up here, acting on the live dialog.
"""
from fastcore.funccall import get_schema

from . import helper
from .dialogs import MSG_TYPES, SETUP, reply, settings

NAMES = list(helper.DIALOG_TOOLS)
OWN_ONLY = ('update_msg', 'del_msg', 'msg_str_replace')   # an outside agent may change only what it wrote itself
WRITES = ('add_msg', 'add_source', 'update_msg', 'del_msg', 'msg_str_replace')


def schemas(names=NAMES):
    return [{'type': 'function', 'function': get_schema(getattr(helper, n), pname='parameters')} for n in names]


def _msg(s, id):
    try: return s.dlg.msg(id)
    except Exception: raise ValueError(f'No message with id {id!r}. Use view_dlg to see the ids.') from None


async def add_msg(s, origin, content, msg_type='note', after='', before='', run=False, _foreign=False):
    if msg_type not in MSG_TYPES: raise ValueError(f'msg_type must be one of {MSG_TYPES}')
    if before: kw = dict(before=_msg(s, before))
    else:
        # In the dialog you are in, new messages follow the one that is running. In another dialog they go to the end.
        anchor = after or (None if _foreign else (s.cursor_id or s.current_id))
        kw = dict(after=_msg(s, anchor)) if anchor and s.has(anchor) else {}
    if origin in ('ai', 'agent'): kw['meta'] = {'polya_by': origin}   # so you can see who wrote it
    m = s.dlg.mk_message(content, msg_type=msg_type, **kw)
    if not after and not before and not _foreign: s.cursor_id = m.id
    s.changed(m)
    if run and msg_type == 'code': return f'Added message {m.id}. Output:\n{await run_msg(s, origin, m.id)}'
    return m.id


async def update_msg(s, origin, id, content=None, msg_type=None, hidden=None, pinned=None):
    m = _msg(s, id)
    if msg_type is not None:
        if msg_type not in MSG_TYPES: raise ValueError(f'msg_type must be one of {MSG_TYPES}')
        if msg_type != m.msg_type: m.msg_type = msg_type
    if content is not None and content != m.content:
        m.content = content
        if origin in ('ai', 'agent'): m.meta['polya_by'] = origin   # it is no longer what you wrote
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
    if origin in ('ai', 'agent'): m.meta['polya_by'] = origin
    s.changed(m)
    return str(diff)


async def run_msg(s, origin, id):
    m = _msg(s, id)
    if m.msg_type != 'code': raise ValueError(f'Message {id} is a {m.msg_type} message; only code messages can be run.')
    if origin == 'kernel':
        # Called from a running code message: the kernel is busy with that cell, so run this one afterwards.
        s.queue_run(m)
        return f'Message {id} is queued and will run when the current message finishes.'
    if origin == 'agent':
        await s.run_code(m)    # from outside: wait its turn like any other run
        return m.ai_output or '(no output)'
    if (m.meta or {}).get('polya_by') == 'ai':
        # Code the notebook's AI wrote never runs unsandboxed on its say-so.
        if not settings(s.dlg)['code_tools']:
            return (f'Message {id} was written by you, so it was NOT run: the user has to run it themselves, or turn on '
                    '"AI can run code" to let you run code in the sandbox. Tell the user it is there for them to review.')
        return await s.exec_sandboxed(m)
    await s.exec_code(m)       # a cell the user wrote, unchanged: running it is running their code
    return m.ai_output or '(no output)'


async def add_source(s, origin, symbol, file='', after='', _foreign=False):
    anchor = after or (None if _foreign else (s.cursor_id or s.current_id))
    m = await s.add_source(symbol, file, after=anchor if anchor and s.has(anchor) else None)
    if not after and not _foreign: s.cursor_id = m.id
    src = m.meta['polya_src']
    return f"{m.id}: linked to {src['file']} :: {src['qualname']} ({len(m.content.splitlines())} lines)"


IMPL = dict(add_source=add_source, add_msg=add_msg, update_msg=update_msg, del_msg=del_msg, read_msg=read_msg, find_msgs=find_msgs,
            view_dlg=view_dlg, msg_str_replace=msg_str_replace, run_msg=run_msg)


async def call(s, origin, name, args):
    "Run dialog tool `name` for session `s`. `args['dialog']` may name another dialog in the same folder."
    args = {k: v for k, v in (args or {}).items() if v is not None}
    if name == 'list_dialogs': return '\n'.join(n + ('  (this dialog)' if n == s.name else '') for n in s.dialog_names())
    if name not in IMPL: raise ValueError(f'Unknown dialog tool {name!r}')
    other = str(args.pop('dialog', '') or '').removesuffix('.ipynb')
    t = s
    if other and other != s.name:
        t = s.other(other)
        # Reading and editing reach other dialogs; running code does not. Each dialog has its own kernel,
        # and what runs there should be started by whoever is working in it.
        if name == 'run_msg' or args.get('run'):
            raise ValueError(f'Code can only be run in the dialog you are in ({s.name}), not in {other}. Add the message without running it.')
        if name in ('add_msg', 'add_source'): args['_foreign'] = True
    if origin == 'ai' and t.name == SETUP and name in WRITES:
        raise ValueError(f'The {SETUP} dialog runs at every kernel start and briefs the AI in every dialog, so only the user changes it. '
                         'Put your suggestion in a note in the current dialog instead.')
    if origin == 'agent' and name in OWN_ONLY:
        m = _msg(t, args.get('id'))
        if (m.meta or {}).get('polya_by') != 'agent':
            raise ValueError(f'Message {m.id} was written by the user. You may only change messages you added yourself. '
                             'To propose a change, add a new message with add_msg.')
    return await IMPL[name](t, origin, **args)
