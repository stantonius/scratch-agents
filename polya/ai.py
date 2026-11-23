"""The AI turn: aihist builds the model's input from the dialog, fastllm talks to the model.

Nothing here knows about a particular provider. Point it at any endpoint with
POLYA_BASE_URL / POLYA_API_KEY / POLYA_MODEL (see README); the request goes there and nowhere else.
"""
import os
from pathlib import Path

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

SKILLS = Path(__file__).parent / 'skills'

GRILL_SP = """Mode: GRILL. In this mode you follow the skill below, written by Matt Pocock for coding agents (MIT licence), instead of answering directly. It is how the user stress-tests a plan, a design, or their understanding of a piece of code before anything gets written.

How the skill applies inside this notebook:
- You have no sub-agents. When a question needs a fact, look for it yourself first: in the dialog above, in the <variables>, or with a tool if the user gave you one that can find it (for example one that reads source code or searches the repository). Ask the user only for decisions, and for facts that you have no way to look up.
- Each round is one reply. The user answers in their next prompt; they may also answer by editing your reply.
- When the frontier is empty, summarise the settled decisions as a short numbered list and stop. Do not write the code for them unless they then ask.

<skill name="{name}">
{body}
</skill>"""


def _skill_text(path):
    "A SKILL.md body without its frontmatter."
    txt = path.read_text(encoding='utf8')
    if txt.startswith('---'): txt = txt.split('---', 2)[-1]
    return txt.strip()


def grill_prompt(folder=None):
    "The grilling skill, plus any extra skill files the user put in `<dialogs>/skills/`."
    sp = GRILL_SP.format(name='grilling', body=_skill_text(SKILLS / 'grilling' / 'SKILL.md'))
    extra = sorted(Path(folder, 'skills').glob('**/*.md')) if folder and Path(folder, 'skills').is_dir() else []
    for f in extra[:10]:
        name = f.parent.name if f.name.upper() == 'SKILL.MD' else f.stem
        sp += f'\n\nThe user also installed this skill; follow it when it applies:\n<skill name="{name}">\n{_skill_text(f)[:12000]}\n</skill>'
    return sp


TOOLS_SP = """You have tools. They are Python functions that the user chose to give you; calling one really runs it.
- Use a tool when the user asks for it, or when it is clearly the way to get what they asked for. Otherwise just answer.
- Tools that change the dialog (add_msg, update_msg, del_msg, msg_str_replace, run_msg) edit the user's own working document. Make only the changes that were asked for, refer to messages by their id, and afterwards say briefly what you changed.
- Messages you add appear right after the current prompt, in the order you add them."""


SANDBOX_TOOLS = [
    {'type': 'function', 'function': dict(
        name='python', description="Run Python code in the user's live kernel, inside a sandbox, and get back what it printed and the value of its last expression. "
        "It sees the user's variables, functions and installed libraries, and names it defines stay defined.",
        parameters=dict(type='object', properties={'code': {'type': 'string', 'description': 'Python source. End with an expression to see its value.'}}, required=['code']))},
    {'type': 'function', 'function': dict(
        name='bash', description="Run a read-only shell command line in the user's project folder (inspection commands such as ls, cat, grep, rg, find, wc, diff, and read-only git such as git status, git diff, git log) and get back its output.",
        parameters=dict(type='object', properties={'cmd': {'type': 'string', 'description': 'One bash command line. Pipes are fine.'}}, required=['cmd']))},
]

SANDBOX_SP = """The `python` and `bash` tools run inside a sandbox in the user's kernel:
- `python` cannot use the network or start subprocesses, and can write files only under folders the user approved (/tmp by default). Reading files, computing, and calling the user's own functions and libraries all work.
- `bash` runs only allowlisted commands, which by default are read-only.
- If a call is blocked, the code is left in the dialog as a cell for the user to review and run themselves. Do not look for another way to do the blocked thing: say what you wanted to do and why, and stop.
- Prefer these tools for looking things up and checking facts. Code that is the user's next step still belongs in a fenced block for them to run."""


def system_prompt(mode, has_tools, folder=None, notes='', sandbox=False):
    sp = BASE_SP
    if notes: sp += '\n\nStanding notes from the user about this project (they apply to every dialog):\n<project-notes>\n' + notes[:20000] + '\n</project-notes>'
    if mode == 'grill': sp += '\n\n' + grill_prompt(folder)
    return sp + ('\n\n' + TOOLS_SP if has_tools else '') + ('\n\n' + SANDBOX_SP if sandbox else '')


def model_cfg(dlg):
    "Where the request goes. Per-dialog model name wins over the POLYA_MODEL default."
    cfg = dict(model=settings(dlg).get('model') or os.environ.get('POLYA_MODEL') or 'claude-sonnet-5-5')
    for k, env in (('base_url', 'POLYA_BASE_URL'), ('api_key', 'POLYA_API_KEY'), ('api_name', 'POLYA_API')):
        if os.environ.get(env): cfg[k] = os.environ[env]
    return cfg


def model_info(): return dict(input_modalities=['text'], max_input_tokens=int(os.environ.get('POLYA_CTX_TOKENS', 200_000)))


async def sandbox_call(s, kind, args):
    "One `python` or `bash` call from the AI. A blocked call becomes a cell the user can read and run by hand."
    code = str(args.get('code' if kind == 'python' else 'cmd') or '')
    if not code.strip(): return 'Error: nothing to run.'
    res = await s.kernel.sandbox(kind, code)
    if 'result' in res: return res['result']
    if 'error' in res: return 'Error: ' + res['error']
    cell = code if kind == 'python' else '%%bash\n' + code
    anchor = s.cursor_id or s.current_id
    m = s.dlg.mk_message(cell, msg_type='code', meta={'polya_by': 'ai'}, **({'after': s.dlg.msg(anchor)} if anchor and s.has(anchor) else {}))
    s.cursor_id = m.id
    s.changed(m)
    return (f"BLOCKED by the sandbox: {res['blocked']}\nNothing was run. The code is now in the dialog as message {m.id} for the user to "
            "review and run themselves if they agree. Do not try another route: tell the user what you wanted to do and why, then stop.")


async def run_turn(s, prompt, emit, stopped):
    "Answer `prompt` in session `s`, streaming the reply into the message. `emit(text)` shows progress."
    dlg, info = s.dlg, model_info()
    refs = references(dlg, prompt.id)
    kernel_names = [n for n in refs.get('tools') or [] if n not in dtools.NAMES]
    dialog_names = dtools.NAMES if settings(dlg)['dialog_tools'] else [n for n in refs.get('tools') or [] if n in dtools.NAMES]

    sandbox = bool(settings(dlg)['code_tools'])
    tools, notes = dtools.schemas(dialog_names) + (SANDBOX_TOOLS if sandbox else []), []
    kernel_names = [n for n in kernel_names if not (sandbox and n in ('python', 'bash'))]
    for nm, sch in (await s.kernel.schemas(kernel_names)).items():
        if isinstance(sch, dict): tools.append(sch)
        else: notes.append(f'Tool `{nm}` is not available: {sch} It must be defined in the kernel with type hints and a docstring.')
    recs = await s.kernel.user_exprs(refs.get('vars') or [])

    items = build(dlg, prompt.id, info, vars=recs) if recs else build(dlg, prompt.id, info)
    msgs, _ = response_input(items)
    system = system_prompt(settings(dlg)['mode'], bool(tools), s.folder, s.project_notes(), sandbox)
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
                        if sandbox and name in ('python', 'bash'): text = await sandbox_call(s, name, tc.arguments or {})
                        elif name in dialog_names: text = str(await dtools.call(s, 'ai', name, tc.arguments or {}))
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
        if text or done:
            set_reply(prompt, text)
            prompt.meta.pop('polya_reply_edited', None)
    return notes
