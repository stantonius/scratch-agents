"""The AI turn: aihist builds the model's input from the dialog, fastllm talks to the model.

Nothing here knows about a particular provider. Point it at any endpoint with
POLYA_BASE_URL / POLYA_API_KEY / POLYA_MODEL (see README); the request goes there and nowhere else.
"""
import os

from aidialog.msg_parts import Part, Text, ToolResult, mk_tool_res_msg
from aihist import Reply, build, references
from fastllm.acomplete import acomplete
from fastllm.responses import response_input

from . import tools as dtools
from .dialogs import set_reply, settings

MAX_STEPS = int(os.environ.get('POLYA_MAX_STEPS', 12))

BASE_SP = """You are the AI collaborator inside Polya, a dialog-based notebook for solving problems step by step, in the spirit of George Pólya's "How to Solve It": understand the problem, devise a plan, carry it out in small verified steps, then look back and reflect.

A dialog is a sequence of messages that the user builds up and freely edits:
- <code id="..."> messages: Python the user runs in a persistent kernel (state carries over, like Jupyter). Their output follows in <out>.
- <markdown id="..."> messages: the user's notes.
- <prompt> messages: the user talking to you. Your earlier replies appear as your earlier turns. The user can edit or delete any of this, including your replies, so treat the dialog as the current truth rather than as a log.
You see everything above the current prompt (unless the user hid it), exactly as the user sees it.

How to work here:
- The user is in charge and wants to understand everything that ends up in the dialog. Help them take the next small step. Do not run ahead and solve the whole task unless they clearly ask for that.
- Code you write goes in fenced ```python blocks. It is NOT run automatically: the user reads it, copies it into a code message, and runs it themselves. So keep each block small, runnable on its own given the kernel state above, and end it with an expression that shows something worth checking. Prefer several small blocks to one big one.
- Build on the variables and functions that already exist in the dialog instead of redefining them.
- Never claim to have run code or seen a result unless it is in an <out> above or came back from a tool call.
- Values of expressions the user referenced with $`name` are given in a <variables> block.
- If the request is ambiguous, ask one short clarifying question instead of guessing.
- Format replies in markdown. Be direct and plain: no flattery, no filler."""

MODE_SP = {
    'learning': """Mode: LEARNING. The user wants to build their own skill, not just get an answer.
- If you do not yet know their background or what they have tried, ask briefly before explaining.
- Guide rather than hand over: give a hint, the next single step, or a question that leads them to it. Let them write the code. Only give a complete solution when they explicitly ask for one.
- When you do show code, show one or two lines for one step, say what output to expect, and invite them to run it and report back.
- When they hit an error, help them read it and find the cause themselves before you fix it.
- Keep replies short, and end with the next thing for them to try or decide.""",
    'concise': """Mode: CONCISE. The user knows what they want.
- Answer in as few words as will do. No preamble, no recap, no closing offers.
- Give compact, idiomatic code for the step asked about, with at most a line of explanation.
- Still one step at a time: do not expand the scope beyond what was asked.""",
    'standard': """Mode: STANDARD. Explain your reasoning at normal length, with code examples where they help, while still working in small steps the user can verify.""",
}

TOOLS_SP = """You have tools. They are Python functions that the user chose to give you; calling one really runs it.
- Use a tool when the user asks for it, or when it is clearly the way to get what they asked for. Otherwise just answer.
- Tools that change the dialog (add_msg, update_msg, del_msg, msg_str_replace, run_msg) edit the user's own working document. Make only the changes that were asked for, refer to messages by their id, and afterwards say briefly what you changed.
- Messages you add appear right after the current prompt, in the order you add them."""


def system_prompt(mode, has_tools):
    sp = BASE_SP + '\n\n' + MODE_SP.get(mode, MODE_SP['standard'])
    return sp + ('\n\n' + TOOLS_SP if has_tools else '')


def model_cfg(dlg):
    "Where the request goes. Per-dialog model name wins over the POLYA_MODEL default."
    cfg = dict(model=settings(dlg).get('model') or os.environ.get('POLYA_MODEL') or 'claude-sonnet-5-5')
    for k, env in (('base_url', 'POLYA_BASE_URL'), ('api_key', 'POLYA_API_KEY'), ('api_name', 'POLYA_API')):
        if os.environ.get(env): cfg[k] = os.environ[env]
    return cfg


def model_info(): return dict(input_modalities=['text'], max_input_tokens=int(os.environ.get('POLYA_CTX_TOKENS', 200_000)))


async def run_turn(s, prompt, emit, stopped):
    "Answer `prompt` in session `s`, streaming the reply into the message. `emit(text)` shows progress."
    dlg, info = s.dlg, model_info()
    refs = references(dlg, prompt.id)
    kernel_names = [n for n in refs.get('tools') or [] if n not in dtools.NAMES]
    dialog_names = dtools.NAMES if settings(dlg)['dialog_tools'] else [n for n in refs.get('tools') or [] if n in dtools.NAMES]

    tools, notes = dtools.schemas(dialog_names), []
    for nm, sch in (await s.kernel.schemas(kernel_names)).items():
        if isinstance(sch, dict): tools.append(sch)
        else: notes.append(f'Tool `{nm}` is not available: {sch} It must be defined in the kernel with type hints and a docstring.')
    recs = await s.kernel.user_exprs(refs.get('vars') or [])

    items = build(dlg, prompt.id, info, vars=recs) if recs else build(dlg, prompt.id, info)
    msgs, _ = response_input(items)
    system = system_prompt(settings(dlg)['mode'], bool(tools))
    if notes: system += '\n\nNote for this turn: ' + ' '.join(notes)
    kw = dict(stream=True, system=system, max_tokens=int(os.environ.get('POLYA_MAX_TOKENS', 4096)), **model_cfg(dlg))
    if tools: kw['tools'] = tools

    rep, shown, done = Reply(), '', False
    try:
        for step in range(MAX_STEPS):
            last = None
            async for o in await acomplete(msgs, **kw):
                last = o
                if isinstance(o, Part):
                    shown += rep.add(o)
                    emit(shown)
                if stopped(): break
            calls = getattr(last, 'tool_calls', None) or []
            if stopped() or not calls: break
            results = []
            for tc in calls:
                if stopped(): text = 'Stopped by the user before this call ran.'
                else:
                    try:
                        name = tc.name.replace('-', '.')
                        if name in dialog_names: text = str(await dtools.call(s, 'ai', name, tc.arguments or {}))
                        else: text = await s.kernel.call(name, tc.arguments or {})
                    except Exception as e: text = f'Error: {type(e).__name__}: {e}'
                r = ToolResult(id=tc.id, name=tc.name, text=text)
                results.append(r)
                shown += rep.add(r)
                emit(shown)
            msgs = msgs + [last.message, mk_tool_res_msg(calls, results)]
        else: rep.add(Text(f'\n\n*(Stopped after {MAX_STEPS} tool steps.)*'))
        done = True
    finally:
        # Keep whatever arrived, in aihist's saved-reply format. If the request failed before
        # anything arrived, leave the previous reply alone instead of wiping it.
        text = rep.finish('*(Stopped.)*' if stopped() else None).strip()
        if text or done: set_reply(prompt, text)
    return notes
