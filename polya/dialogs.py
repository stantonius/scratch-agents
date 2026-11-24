"Dialogs on disk: thin helpers over `aidialog` (Answer.AI's dialog model, stored as .ipynb)."
import re
from pathlib import Path

import aidialog.dlgskill  # noqa: F401  (adds find_msgs and friends to Dialog)
from aidialog.dialog import Dialog, prompt_output
from aidialog.ipynb import read_ipynb
from aihist import count_tokens

MSG_TYPES = ('code', 'note', 'prompt', 'raw')
MODES = ('basic', 'grill')
SETUP = 'SETUP'   # a dialog with this name configures every other dialog in the folder
_name_re = re.compile(r"^[\w][\w\-. ]{0,80}$")


def valid_name(name): return bool(_name_re.match(name or '')) and '..' not in name


def settings(dlg):
    "Per-dialog settings, kept in the notebook's metadata."
    s = dlg.meta.setdefault('polya', {})
    if s.get('mode') not in MODES: s['mode'] = 'basic'
    s.setdefault('model', '')
    s.setdefault('dialog_tools', False)
    s.setdefault('code_tools', False)
    return s


def load(path):
    path = Path(path)
    if path.exists(): dlg = read_ipynb(path, name=path.stem)
    else:
        dlg = Dialog(name=path.stem)
        dlg.path_ = str(path)
    settings(dlg)
    return dlg


def setup_parts(folder):
    "(code, notes) of the folder's SETUP dialog: code runs when a kernel starts, notes go to the AI in every dialog."
    path = Path(folder) / f'{SETUP}.ipynb'
    if not path.exists(): return [], ''
    try: ms = read_ipynb(path, name=SETUP).messages
    except Exception: return [], ''
    # Belt and braces: anything in SETUP still marked as written by the notebook's AI is ignored until you run or edit it.
    ms = [m for m in ms if (m.meta or {}).get('polya_by') != 'ai' and not m.skipped and (m.content or '').strip()]
    code = [m.content for m in ms if m.msg_type == 'code']
    notes = '\n\n'.join(m.content for m in ms if m.msg_type == 'note')
    return code, notes


SETUP_TEMPLATE = [
    ('note', """# Project setup

This dialog configures every other dialog in this folder.

- **Code messages here run each time a kernel starts or restarts**, before anything else. Use them for imports you always want, `autoreload`, environment variables, and test doubles for things that are not available on your machine (databases, queues, internal services).
- **Notes here are given to the AI in every dialog**, like a standing brief. Write down what the project is, its conventions, and its vocabulary. Hide a note (`h`) to keep it for yourself.

Edit and test it like any dialog. Changes apply to other dialogs the next time their kernel restarts."""),
    ('code', "# Pick up edits to the project's files without restarting the kernel\n%load_ext autoreload\n%autoreload 2"),
    ('note', "## About this project\n\n*(Replace this: what the codebase does, the main packages, naming conventions, how tests are run.)*"),
    ('code', "# Stand-ins for things you can't reach from here. For example:\n# import os\n# os.environ['DATABASE_URL'] = 'sqlite:///:memory:'"),
    ('code', "# What the AI's sandboxed tools may do beyond the defaults (see 'AI can run code'). For example:\n# sandbox_cmds('pytest')          # let its bash tool run the tests\n# sandbox_dirs('./scratch')       # let it write under this folder as well as /tmp\n# sandbox_allow(my_fetch_docs)    # trust one of your functions to use the network"),
]


def make_setup(folder):
    dlg = load(Path(folder) / f'{SETUP}.ipynb')
    if not dlg.messages:
        for typ, src in SETUP_TEMPLATE: dlg.mk_message(src, msg_type=typ)
        dlg.save()
    return dlg


def reply(m): return (m.ai_res or '') if m.msg_type == 'prompt' else ''


def set_reply(m, text): m.output = prompt_output(text) if text else []


def add_stream_output(m, jmsg):
    "Add a kernel output message to `m`, joining consecutive chunks of the same stream."
    c = jmsg['content']
    if jmsg['header']['msg_type'] == 'clear_output': return m.clear_output(wait=c.get('wait', False))
    out = m.output or []
    if jmsg['header']['msg_type'] == 'stream' and out and out[-1].get('output_type') == 'stream' and out[-1].get('name') == c['name']:
        out[-1]['text'] = _src(out[-1]['text']) + c['text']
        m.clear_out_cache()
    else: m.add_output(jmsg)


def _src(s): return ''.join(s) if isinstance(s, list) else (s or '')


def msg_tokens(m):
    n = count_tokens(m.content or '')
    if m.msg_type == 'prompt': n += count_tokens(reply(m))
    elif m.msg_type == 'code' and m.output: n += count_tokens(m.ai_output or '')
    return n


def fenced_blocks(md):
    "Code in fenced blocks (python or unlabelled), skipping saved tool-call blocks."
    res = []
    for info, body in re.findall(r'^```([^\n]*)\n(.*?)^```[ \t]*$', md or '', flags=re.S | re.M):
        lang = info.strip().split(' ')[0].lower()
        if '{.' in info: continue
        if lang in ('', 'python', 'py', 'python3', 'ipython'): res.append(body.rstrip('\n'))
    return res


WELCOME = [
    ('note', """# Welcome to Polya

A **dialog** is one continuous conversation between three parties:

- you and **yourself** — *notes* (markdown, like this one)
- you and **the computer** — *code* (Python, in a kernel that keeps its state)
- you and **the AI** — *prompts* (the AI sees everything above the prompt, exactly as you do)

The method comes from George Pólya's *How to Solve It* (1945): **understand the problem → devise a plan → carry out the plan in small, verified steps → look back.** It is the opposite of asking an AI for 300 lines you don't understand.

Click a message to select it, press `Enter` to edit it, `Ctrl+Enter` to run it. Press `?` for all shortcuts."""),
    ('note', """## 1. Understand the problem, then plan

We have two columns of numbers and want the first column, sorted. Plan:

1. Split the text into lines
2. Grab the first number on each line
3. Sort"""),
    ('code', "x = '3   4\\n4   3\\n2   5\\n1   3\\n3   9\\n3   3'\nx"),
    ('note', "## 2. Carry out the plan — one or two lines at a time\n\nRun each step and *look at the output* before writing the next one. Press `r` to run them all."),
    ('code', "lines = x.splitlines()\nlines"),
    ('code', "l1 = [int(o.split()[0]) for o in lines]\nl1"),
    ('code', "sorted(l1)"),
    ('note', "Only once every piece has been seen working do we stack them into a function:"),
    ('code', "def get_list(x):\n    lines = x.splitlines()\n    return sorted(int(o.split()[0]) for o in lines)\n\nget_list(x)"),
    ('note', """## 3. Ask the AI for *one step*, not the whole thing

Switch the editor at the bottom to **prompt** and ask something small, like the prompt below (select it and press `Ctrl+Enter` to send it). The AI's code arrives in fenced blocks and is **not run**: select the prompt and press `w` to turn the blocks into code messages that you read, edit and run yourself.

If the AI goes off track, don't argue with it. **Edit its reply** (`n`), **hide** the message from it (`h`), or delete it (`x`). A tidy dialog keeps the AI useful — that is *dialog engineering*."""),
    ('prompt', "I now want the second column as well, as a second sorted list. What's the smallest change to `get_list` that would do it? Just a hint first please."),
    ('note', """## 4. Any Python function can be a tool

Write a function with type hints and a docstring, then mention it in any message as an ampersand followed by its name in backticks. The AI can then call it — and so can you. A dollar sign followed by an expression in backticks shows the AI its current value. The prompt below uses both."""),
    ('code', "def total_distance(a: list[int], b: list[int]) -> int:\n    \"Sum of absolute differences between paired items of `a` and `b`\"\n    return sum(abs(p - q) for p, q in zip(a, b))"),
    ('prompt', "Use &`total_distance` on the two sorted columns of $`x` and tell me the result."),
    ('note', """## 5. Let the AI work *in* the dialog

Tick **AI can edit dialog** in the header and the AI gets tools to add, edit and find messages (`add_msg`, `update_msg`, `find_msgs`, …). They are ordinary functions that you can call from code too — try `add_msg('hello from code', 'note')` in a code message. Cells the AI writes are marked *added by AI*, and it does not run them: you do.

Tick **AI can run code** and the AI also gets a `python` tool and a `bash` tool that run in your kernel inside a sandbox: it can read, compute and call your functions, but it has no network, cannot start programs, can write only under `/tmp`, and its shell commands are read-only. Anything the sandbox blocks is left as a cell for you to read and run yourself if you agree.

Use these for chores — *"add a heading above each step"*, *"check which files import this module"* — while you stay the one who decides what the next step is."""),
    ('note', """## 6. Working on real code

- **See where a name comes from**: hold `Ctrl` and click any name in a code message. You get its source, file and line; `Ctrl`+click inside that source to keep following it. *Insert as code* copies the definition into a cell you can run and change line by line.
- **Grill mode** (header): instead of answering, the AI interviews you about your plan, or about what a piece of code does, one round of questions at a time, with a recommended answer for each.
- **Project setup**: from the dialog list, *Create project setup* makes a `SETUP` dialog. Its code runs whenever a kernel starts; its notes go to the AI in every dialog.
- **Your coding agent** can connect to this notebook (the start-up message shows how). What it runs then appears here as cells marked *added by agent*, and it cannot change cells you wrote."""),
]


def make_welcome(path):
    dlg = load(path)
    for typ, src in WELCOME: dlg.mk_message(src, msg_type=typ)
    dlg.save()
    return dlg
