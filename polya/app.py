"The Polya web app: a FastHTML server holding live dialogs, their kernels, and the AI turns."
import asyncio, json, os, secrets, shutil, time
from pathlib import Path
from urllib.parse import urlparse

from aihist import dlg2md, msgs2py
from fasthtml.common import (H1, H2, A, Body, Button, Div, FastHTML, Form, Head, Html, Input, Label, Li, Link, Main, Meta, NotStr,
                             Option, P, Script, Select, Span, Style, Title, Ul)
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, agent, ai, source as so, tools as dtools
from .dialogs import (MODES, MSG_TYPES, SETUP, add_stream_output, fenced_blocks, load, make_setup, make_welcome, msg_tokens, reply, set_reply,
                      settings, setup_parts, valid_name)
from .kernel import Kernel
from .render import code_html, msg_html, theme_css

STATIC = Path(__file__).parent / 'static'
CFG = dict(dir=Path(os.environ.get('POLYA_DIR', 'dialogs')), url='http://127.0.0.1:5001', project=None)
TOKEN = secrets.token_urlsafe(24)   # lets a dialog's own kernel call back into this server
AGENT_TOKEN = os.environ.get('POLYA_AGENT_TOKEN') or secrets.token_urlsafe(24)   # for an outside coding agent, over /mcp
sessions = {}


# ---------------------------------------------------------------- live dialog state
class Session:
    "A dialog that is open in the server: its messages, its kernel, and the browsers watching it."
    def __init__(self, name):
        self.name = name
        self.dlg = load(CFG['dir'] / f'{name}.ipynb')
        self.folder = CFG['dir'].resolve()
        env = dict(POLYA_URL=CFG['url'], POLYA_DIALOG=name, POLYA_TOKEN=TOKEN)
        cwd = self.folder
        if CFG['project']:      # work inside the user's codebase: start there and make it importable
            cwd = Path(CFG['project']).resolve()
            env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(cwd), os.environ.get('PYTHONPATH', '')]))
        # The SETUP dialog's code runs at every kernel start (but not for the SETUP dialog itself, where you run it by hand).
        self.kernel = Kernel(cwd, env, setup=None if name == SETUP else (lambda: setup_parts(self.folder)[0]))
        self.subs = set()
        self.lock = asyncio.Lock()      # one code run or AI turn at a time, in order
        self.stop = False
        self.current_id = self.cursor_id = None
        self.running, self.live, self.errors = set(), {}, {}
        self.tasks = set()

    # -- lookups
    def has(self, id):
        return any(m.id == id for m in self.dlg.messages)

    def prev_id(self, m):
        ms = self.dlg.messages
        i = ms.index(m)
        return ms[i - 1].id if i else ''

    # -- telling browsers
    def broadcast(self, ev):
        data = json.dumps(ev)
        for q in list(self.subs): q.put_nowait(data)

    def html(self, m):
        return msg_html(m, live=self.live.get(m.id), running=m.id in self.running, error=self.errors.get(m.id, ''), link=self.src_info(m))

    # -- cells linked to the codebase
    @property
    def project(self): return str(Path(CFG['project']).resolve()) if CFG['project'] else None

    def src_info(self, m):
        "For a linked cell: its link plus how it compares with the file right now. None for an ordinary cell."
        src = (m.meta or {}).get('polya_src')
        if not src or m.msg_type != 'code': return None
        st, _ = so.status(src, m.content or '', self.project)
        return dict(src, status=st, label=so.LABELS[st])

    async def add_source(self, symbol, file='', after=None):
        "Add a code message holding `symbol`'s source, copied from its file and linked to it."
        symbol, file, module = (symbol or '').strip(), (file or '').strip(), ''
        if not symbol: raise ValueError('Name the function, class or method to bring in.')
        if file: path, qual = so.resolve(file, self.project), symbol
        else:
            d = await self.kernel.definition(symbol)
            if 'error' in d: raise ValueError(f"{d['error']} Or pass `file` to locate it without importing.")
            if d['kind'] not in ('function', 'class') or not d.get('file'):
                raise ValueError(f'`{symbol}` is a {d["kind"]}, not a function or class with source in a file.')
            path, qual, module = Path(d['file']), d['qualname'], d.get('module') or ''
        link, code = so.link(path, qual, self.project)
        if not link['module']: link['module'] = module
        m = self.dlg.mk_message(code, msg_type='code', meta={'polya_src': link}, **({'after': self.dlg.msg(after)} if after else {}))
        self.changed(m)
        return m

    def code_for(self, m):
        "What actually gets sent to the kernel for `m`: a linked cell runs inside its own module."
        src = (m.meta or {}).get('polya_src')
        if not src or not src.get('module'): return m.content
        qual = src.get('qualname') or ''
        if src.get('kind') == 'new':
            owner = src['after'].rsplit('.', 1)[0] + '.' if '.' in (src.get('after') or '') else ''
            qual = owner + (so.def_name(m.content) or 'new')
        return f"__polya_inmod({src['module']!r}, {qual!r}, {m.content!r})"

    def push(self, m):
        if self.has(m.id): self.broadcast(dict(op='upsert', id=m.id, after=self.prev_id(m), html=self.html(m)))

    def dialog_names(self): return dialog_names()

    def other(self, name):
        "The session for another dialog in the same folder (opening it if need be)."
        o = get_session(name)
        if o is None: raise ValueError(f'No dialog named {name!r} in this folder. Use list_dialogs to see the names.')
        return o

    def project_notes(self): return '' if self.name == SETUP else setup_parts(self.folder)[1]

    def status(self):
        self.broadcast(dict(op='status', busy=bool(self.running), alive=self.kernel.alive, setup_error=self.kernel.setup_error,
                            tokens=sum(msg_tokens(m) for m in self.dlg.messages if not m.skipped)))

    def save(self): self.dlg.save()

    def changed(self, m):
        "A message was added or edited: save and show it."
        self.save(); self.push(m); self.status()

    def remove(self, m):
        self.dlg.remove_msgs([m])
        for d in (self.live, self.errors): d.pop(m.id, None)
        self.save(); self.broadcast(dict(op='delete', id=m.id)); self.status()

    def spawn(self, coro):
        t = asyncio.create_task(coro)
        self.tasks.add(t); t.add_done_callback(self.tasks.discard)
        return t

    # -- running things
    async def exec_code(self, m):
        "Run code message `m` now, streaming its outputs to browsers. Returns True if it ran without error."
        m.output = []
        self.running.add(m.id); self.push(m); self.status()
        last = 0
        try:
            async for jm in self.kernel.run(self.code_for(m)):
                add_stream_output(m, jm)
                if time.monotonic() - last > 0.08: self.push(m); last = time.monotonic()
        except Exception as e:
            m.output = (m.output or []) + [dict(output_type='error', ename=type(e).__name__, evalue=str(e),
                                                 traceback=[f'{type(e).__name__}: {e}', 'The kernel may have died; it will restart on the next run.'])]
            await self.kernel.shutdown()
        finally:
            self.running.discard(m.id)
            self.changed(m)
        return not any(o.get('output_type') == 'error' for o in m.output or [])

    async def exec_sandboxed(self, m):
        "Run a code message the AI wrote through the kernel's sandbox, showing the result as its output."
        m.output = []
        self.running.add(m.id); self.push(m)
        try: res = await self.kernel.sandbox('python', m.content)
        except Exception as e: res = {'error': f'{type(e).__name__}: {e}'}
        finally: self.running.discard(m.id)
        if 'result' in res:
            m.output = [dict(output_type='stream', name='stdout', text=res['result'] + '\n')]
            text = res['result']
        elif 'blocked' in res:
            text = f"Blocked by the sandbox: {res['blocked']}"
            m.output = [dict(output_type='error', ename='SandboxBlocked', evalue=res['blocked'],
                             traceback=[text, 'This cell was not run. If you agree with what it does, run it yourself (Ctrl+Enter).'])]
            text += '\nThe cell was not run. It is in the dialog for the user to review and run themselves if they agree.'
        else:
            text = res.get('error', 'failed')
            m.output = [dict(output_type='error', ename='Error', evalue=text, traceback=[text])]
        self.changed(m)
        return text

    async def run_code(self, m):
        self.running.add(m.id); self.push(m)    # show it as queued straight away
        async with self.lock:
            if not self.has(m.id): return False
            self.current_id = self.cursor_id = m.id
            try: return await self.exec_code(m)
            finally: self.current_id = self.cursor_id = None

    def queue_run(self, m): self.spawn(self.run_code(m))

    async def run_prompt(self, m):
        self.errors.pop(m.id, None)
        self.running.add(m.id); self.live[m.id] = ''; self.push(m)
        async with self.lock:
            if not self.has(m.id): return
            self.stop, self.current_id, self.cursor_id, last = False, m.id, m.id, [0.0]

            def emit(text):
                self.live[m.id] = text
                if time.monotonic() - last[0] > 0.08: self.push(m); last[0] = time.monotonic()
            self.status()
            try:
                notes = await ai.run_turn(self, m, emit, lambda: self.stop)
                if notes: self.errors[m.id] = '\n'.join(notes)
            except Exception as e:
                self.errors[m.id] = f'The model request failed — {type(e).__name__}: {str(e)[:1500]}\n(model: {ai.model_cfg(self.dlg)["model"]}, endpoint: {os.environ.get("POLYA_BASE_URL", "provider default")})'
            finally:
                self.running.discard(m.id); self.live.pop(m.id, None)
                self.current_id = self.cursor_id = None
                self.changed(m)

    def run_plan(self, scope='all', id=None):
        """(to_run, skipped) for Run all / above / below.

        Only code messages are ever run this way. Prompts are never re-sent: their replies are part of the
        document. Code the AI wrote that you have not run or edited yourself is skipped too, so a bulk run
        cannot execute something you have not looked at.
        """
        ms = list(self.dlg.messages)
        if scope in ('above', 'below') and id and self.has(id):
            i = ms.index(self.dlg.msg(id))
            ms = ms[:i] if scope == 'above' else ms[i:]     # like Jupyter: above excludes the selected cell, below includes it
        code = [m for m in ms if m.msg_type == 'code' and (m.content or '').strip()]
        skipped = [m for m in code if (m.meta or {}).get('polya_by') == 'ai']
        return [m for m in code if m not in skipped], skipped

    async def run_all(self, todo):
        self.stop = False
        for m in todo:
            if self.stop or not self.has(m.id): break
            if not await self.run_code(m): break

    async def interrupt(self):
        self.stop = True
        await self.kernel.interrupt()

    async def restart(self):
        self.stop = True
        await self.kernel.shutdown()
        self.status()


def get_session(name):
    if name not in sessions:
        if not valid_name(name) or not (CFG['dir'] / f'{name}.ipynb').exists(): return None
        sessions[name] = Session(name)
    return sessions[name]


def dialog_names():
    CFG['dir'].mkdir(parents=True, exist_ok=True)
    return sorted((p.stem for p in CFG['dir'].glob('*.ipynb') if valid_name(p.stem)), key=str.lower)


# ---------------------------------------------------------------- app
def _same_origin(req):
    "POSTs must come from this app's own pages (or from a kernel holding the token)."
    if req.method != 'POST': return True
    if secrets.compare_digest(req.headers.get('x-polya-token', ''), TOKEN): return True
    origin = req.headers.get('origin')
    return bool(origin) and urlparse(origin).netloc == req.headers.get('host')


async def guard(req):
    if not _same_origin(req): return PlainTextResponse('Cross-origin request refused', status_code=403)


async def _shutdown():
    for s in list(sessions.values()): await s.kernel.shutdown()

app = FastHTML(default_hdrs=False, secret_key=secrets.token_hex(16), before=guard, on_shutdown=[_shutdown],
               routes=[Mount('/static', StaticFiles(directory=STATIC), name='static'),
                       Route('/mcp', endpoint=agent.mcp_app(AGENT_TOKEN), methods=['GET', 'POST', 'DELETE'])])
rt = app.route


def J(**kw): return JSONResponse(kw)


def page(title, *body, cls='', data=None):
    v = __version__
    head = Head(Meta(charset='utf-8'), Meta(name='viewport', content='width=device-width, initial-scale=1'), Title(title),
                Link(rel='stylesheet', href=f'/static/vendor/codemirror.css?v={v}'), Link(rel='stylesheet', href=f'/static/app.css?v={v}'),
                Style(NotStr(theme_css())))
    return Html(head, Body(*body, cls=cls, **(data or {})), lang='en')


@rt('/')
def home():
    names = dialog_names()
    if not names:
        make_welcome(CFG['dir'] / 'welcome.ipynb')
        names = dialog_names()
    rows = [Li(A(n, href=f'/d/{n}', cls='dname'),
               Span('runs at every kernel start', cls='pill setup') if n == SETUP else '',
               Span('kernel running', cls='pill') if n in sessions and sessions[n].kernel.alive else '',
               Span(cls='grow'),
               Form(Button('Duplicate', cls='ghost'), method='post', action=f'/d/{n}/duplicate'),
               Form(Button('Delete', cls='ghost danger'), method='post', action=f'/d/{n}/delete',
                    onsubmit=f"return confirm('Delete dialog {n}? This removes the file.')"))
            for n in names]
    cfg = ai.model_cfg(load(CFG['dir'] / f'{names[0]}.ipynb')) if names else {}
    return page('Polya', Main(
        H1('Polya'), P('Solve problems in small, verified steps — with code, notes and an AI that sees what you see.', cls='lede'),
        Form(Input(name='name', placeholder='New dialog name', required=True, pattern=r'[\w][\w\-. ]*', autofocus=True),
             Button('Create dialog', cls='primary'), method='post', action='/new', cls='newdlg'),
        H2('Dialogs'), Ul(*rows, cls='dlist'),
        '' if SETUP in names else Form(Button('Create project setup', cls='ghost'), Span(' — code that runs when any kernel starts, and standing notes for the AI', cls='fine'),
                                         method='post', action='/setup', cls='setupform'),
        P(f"Kernels start in: {Path(CFG['project']).resolve() if CFG['project'] else CFG['dir'].resolve()}", cls='fine'),
        P(f"Dialogs are .ipynb files in {CFG['dir'].resolve()}. ",
          f"AI requests go to: {os.environ.get('POLYA_BASE_URL') or 'the provider default for the model'} (default model {os.environ.get('POLYA_MODEL') or cfg.get('model', '')}).",
          cls='fine'),
        cls='home'), cls='homebody')


@rt('/new', methods=['POST'])
async def new(req):
    name = ((await req.form()).get('name') or '').strip()
    if not valid_name(name): return PlainTextResponse('Names may use letters, digits, spaces, dots, dashes and underscores.', status_code=400)
    path = CFG['dir'] / f'{name}.ipynb'
    if not path.exists(): load(path).save()
    return RedirectResponse(f'/d/{name}', status_code=303)


@rt('/setup', methods=['POST'])
def create_setup():
    make_setup(CFG['dir'])
    return RedirectResponse(f'/d/{SETUP}', status_code=303)


@rt('/d/{name}/delete', methods=['POST'])
async def delete_dialog(name: str):
    if not valid_name(name): return PlainTextResponse('Bad name', status_code=400)
    if (s := sessions.pop(name, None)): await s.kernel.shutdown()
    (CFG['dir'] / f'{name}.ipynb').unlink(missing_ok=True)
    return RedirectResponse('/', status_code=303)


@rt('/d/{name}/duplicate', methods=['POST'])
def duplicate(name: str):
    src = CFG['dir'] / f'{name}.ipynb'
    if not valid_name(name) or not src.exists(): return PlainTextResponse('No such dialog', status_code=404)
    if name in sessions: sessions[name].save()
    i = 2
    while (dst := CFG['dir'] / f'{name} {i}.ipynb').exists(): i += 1
    shutil.copy(src, dst)
    return RedirectResponse(f'/d/{dst.stem}', status_code=303)


HELP = [
    ('Moving around', [('↑ ↓  or  k j', 'select previous / next message'), ('Home / End', 'first / last message'), ('/', 'jump to the editor at the bottom'), ('Esc', 'leave an editor (saves)')]),
    ('Writing', [('Enter', 'edit the selected message'), ('n', "edit the AI's reply (an edited reply locks the prompt against re-sending)"), ('a / b', 'new message above / below'),
                 ('Ctrl+Shift+J/K/L', 'make it code / note / prompt (or Alt+J/K/L)'), ('1 – 6', 'make a note a heading of that level'), ('Tab', 'complete code from the live kernel'), ('Ctrl+click a name', 'go to its definition (also right-click, or F12 in an editor)')]),
    ('Running', [('Ctrl+Enter', 'run code, or send a prompt to the AI'), ('Shift+Enter', 'run and move to the next message'), ('Alt+Enter', 'in the bottom editor: send a prompt and stay in prompt mode'),
                 ('r', 'run all code messages (never re-sends prompts)'), ('Shift+A / Shift+B', 'run the code messages above / from here down'), ('Shift+S', 'stop the running code or AI reply'), ('Shift+R', 'restart the kernel'), ('Backspace', "clear a code message's output")]),
    ('Dialog engineering', [('w', "copy the AI's code blocks into code messages"), ('h', 'hide a message from the AI / show it again'), ('p', 'pin a message so it always stays in the AI context'),
                            ('x / c / v', 'cut / copy / paste messages (works across dialogs)'), ('Alt+↑ / Alt+↓', 'move a message up / down')]),
]


@rt('/d/{name}')
def dialog(name: str):
    s = get_session(name)
    if s is None: return RedirectResponse('/', status_code=303)
    st = settings(s.dlg)
    msgs = ''.join(s.html(m) for m in s.dlg.messages)
    header = Div(
        A('Polya', href='/', cls='brand', title='All dialogs'), Span(name, cls='dtitle'),
        Span(Span(cls='dot'), Span('kernel idle', id='ktext'), id='kstat', cls='kstat'),
        Span(cls='grow'),
        Label('Mode', Select(*[Option(m, value=m, selected=(m == st['mode'])) for m in MODES], id='mode'),
              title='basic: the AI answers, one small step at a time. grill: the AI interviews you about your plan or your understanding, round by round, before anything is written.'),
        Label(Input(type='checkbox', id='dtools', checked=st['dialog_tools']), 'AI can edit dialog',
              title='Give the AI tools to add, edit and find messages in this dialog. Code it writes is run only by you, or in the sandbox if the next box is ticked.', cls='chk'),
        Label(Input(type='checkbox', id='ctools', checked=st['code_tools']), 'AI can run code',
              title='Give the AI a python tool and a bash tool that run in this kernel inside a sandbox: no network, no subprocesses, writes only under /tmp, read-only shell commands. Blocked code is left as a cell for you to run.', cls='chk'),
        Label('Model', Input(id='model', value=st['model'], placeholder=os.environ.get('POLYA_MODEL') or 'default', size=16),
              title='Model name sent to your endpoint for this dialog (empty = POLYA_MODEL)'),
        Button('Run all', id='runall', title='Run every code message from the top (r). Prompts are never re-sent. Shift+A / Shift+B run the code above / from the selected message down.'),
        Button('Stop', id='stop', title='Stop the running code or AI reply (Shift+S)'),
        Button('Restart', id='restart', title='Restart the kernel: all variables are lost (Shift+R)'),
        Select(Option('Export…', value=''), Option('Notebook (.ipynb)', value='ipynb'), Option('Markdown (.md)', value='md'),
               Option('Python script (.py)', value='py'), id='export'),
        Button('Changes', id='chgbtn', title='Cells linked to files that differ from them: review the diffs and write them back'),
        Button('Vars', id='sidetoggle', title='Show the outline and live variables'),
        Button('?', id='helpbtn', title='Keyboard shortcuts (?)'),
        cls='top')
    composer = Div(
        Div(*[Button(t, cls='ctype', data_type=t, title=f'Next message is a {t} message') for t in ('code', 'note', 'prompt')],
            Span(id='chint', cls='chint'), Span(cls='grow'), Span('', id='ctx', cls='ctx', title='Approximate size of what the AI sees'),
            Button('Add', id='csend', cls='primary'), cls='cbar'),
        Div(id='ceditor'), id='composer')
    helpdlg = Div(Div(H2('Keyboard shortcuts'), *[Div(H2(sec, cls='hsec'), *[Div(Span(k, cls='key'), Span(d)) for k, d in rows], cls='hgroup') for sec, rows in HELP],
                      P('In any message: an ampersand then a function name in backticks gives that function to the AI as a tool; '
                        'a dollar sign then an expression in backticks shows the AI its value.', cls='fine'),
                      Button('Close', id='helpclose'), cls='helpbox'), id='help', hidden=True)
    return page(f'{name} · Polya', header,
                Div(Main(NotStr(msgs), id='msgs'), Div(Div(H2('Outline'), Div(id='outline'), H2('Variables'), Div(id='vars'), H2('Functions'), Div(id='funcs')), id='side', hidden=True), cls='work'),
                composer, helpdlg,
                Div(Div(Button('←', id='dback', title='Back'), Span(id='dtitle'), Span(cls='grow'),
                        Button('Insert as code', id='dcode', title='Copy this source into a code message you can run and change (it redefines the name in this kernel only)'),
                        Button('Insert as note', id='dnote', title='Put this source in a note so the AI sees it'),
                        Button('✕', id='dclose', title='Close (Esc)'), cls='dhead'),
                    Div(id='dmeta', cls='dmeta'), Div(id='dbody', cls='dbody'), id='defn', hidden=True),
                Div(id='banner', hidden=True),
                Div(Div(id='mbox', cls='mbox'), id='modal', hidden=True), Div(id='ctxmenu', hidden=True),
                Script(src=f'/static/vendor/codemirror.js?v={__version__}'), Script(src=f'/static/vendor/codemirror-extras.js?v={__version__}'),
                Script(src=f'/static/app.js?v={__version__}'), cls='dlgbody', data={'data-dialog': name})


@rt('/d/{name}/events')
async def events(name: str, req):
    s = get_session(name)
    if s is None: return PlainTextResponse('No such dialog', status_code=404)
    q = asyncio.Queue()
    s.subs.add(q)

    async def gen():
        try:
            yield 'retry: 1500\n\n'
            s.status()
            while True:
                try: data = await asyncio.wait_for(q.get(), 15)
                except asyncio.TimeoutError:
                    yield ': ping\n\n'
                    continue
                yield f'data: {data}\n\n'
        finally: s.subs.discard(q)
    return StreamingResponse(gen(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _raw(m):
    return dict(id=m.id, type=m.msg_type, content=m.content or '', reply=reply(m), hidden=bool(m.skipped), pinned=bool(m.pinned),
                reply_edited=bool((m.meta or {}).get('polya_reply_edited')))


@rt('/d/{name}/msg/{id}/raw')
def msg_raw(name: str, id: str):
    s = get_session(name)
    if s is None or not s.has(id): return J(error='No such message')
    return J(**_raw(s.dlg.msg(id)))


@rt('/d/{name}/do', methods=['POST'])
async def do(name: str, req):
    "Every edit a browser makes arrives here as {op, ...}."
    s = get_session(name)
    if s is None: return J(error='No such dialog')
    b = await req.json()
    op, mid = b.get('op'), b.get('id')
    m = s.dlg.msg(mid) if mid and s.has(mid) else None
    if mid and m is None: return J(error='That message no longer exists')

    def start(msg):
        if msg.msg_type == 'code':
            # Running a cell yourself is how you accept it: it stops being "added by AI/agent".
            if msg.meta.pop('polya_by', None): s.save()
            s.spawn(s.run_code(msg))
        elif msg.msg_type == 'prompt':
            # A reply you edited by hand is yours. Re-sending the prompt would overwrite it, so it is refused.
            if msg.meta.get('polya_reply_edited'):
                return 'You edited this reply, so the prompt will not be re-sent. To ask again, clear the reply first (press n, delete the text, Esc), or copy the prompt into a new message.'
            s.spawn(s.run_prompt(msg))
        return None

    if op == 'add':
        typ = b.get('type', 'code')
        if typ not in MSG_TYPES: return J(error='Bad type')
        kw = {}
        if b.get('before') and s.has(b['before']): kw['before'] = s.dlg.msg(b['before'])
        elif b.get('after') and s.has(b['after']): kw['after'] = s.dlg.msg(b['after'])
        nm = s.dlg.mk_message(b.get('content', ''), msg_type=typ, **kw)
        s.changed(nm)
        if b.get('run'): start(nm)
        return J(id=nm.id)
    if op == 'update':
        if 'type' in b and b['type'] in MSG_TYPES and b['type'] != m.msg_type:
            keep = reply(m) if m.msg_type == 'prompt' else ''
            m.msg_type = b['type']
            if b['type'] != 'code': m.meta.pop('polya_src', None)
            if keep and b['type'] == 'prompt': set_reply(m, keep)
        if 'content' in b:
            if b['content'] != m.content: m.meta.pop('polya_by', None)   # you edited it: it is yours now
            m.content = b['content']
        if 'reply' in b and m.msg_type == 'prompt' and b['reply'] != reply(m):
            set_reply(m, b['reply'])
            if b['reply'].strip(): m.meta['polya_reply_edited'] = True    # locked: see `start`
            else: m.meta.pop('polya_reply_edited', None)                  # cleared: it can be asked again
        if 'hidden' in b: m.skipped = int(bool(b['hidden']))
        if 'pinned' in b: m.pinned = int(bool(b['pinned']))
        s.changed(m)
        err = start(m) if b.get('run') else None
        return J(id=m.id, error=err) if err else J(id=m.id)
    if op == 'run':
        err = start(m)
        return J(id=m.id, error=err) if err else J(id=m.id)
    if op == 'delete':
        if m.id in s.running: return J(error='That message is running. Stop it first.')
        s.remove(m); return J(ok=True)
    if op == 'clear':
        if m.msg_type == 'code' and m.id not in s.running: m.output = []; s.changed(m)
        return J(ok=True)
    if op == 'move':
        ms = s.dlg.messages
        i = ms.index(m); j = i + (1 if b.get('dir') == 'down' else -1)
        if 0 <= j < len(ms):
            other = ms[j]
            s.dlg.move_msgs([m.id], **({'after': other.id} if j > i else {'before': other.id}))
            s.save(); s.push(m); s.push(other)
        return J(ok=True)
    if op == 'add_source':
        try: nm = await s.add_source(b.get('symbol') or b.get('qualname', ''), b.get('file', ''), after=b['after'] if b.get('after') and s.has(b['after']) else None)
        except Exception as e: return J(error=str(e))
        return J(id=nm.id)
    if op in ('src_diff', 'src_apply', 'src_revert', 'src_target', 'src_unlink'):
        src = (m.meta or {}).get('polya_src')
        try:
            if op == 'src_target':      # say where a new piece of code should go
                path = so.resolve(str(b.get('file', '')).strip(), s.project)
                if not so.in_project(path, s.project): return J(error='Choose a .py file inside the project folder (start Polya with --project).')
                after = str(b.get('after') or '')
                if path.exists() and after and so.find(path, after) is None: return J(error=f'`{after}` is not in {b.get("file")}.')
                if not path.exists() and not b.get('create'): return J(error=f'{b.get("file")} does not exist. Tick "create the file" to make it.')
                if not path.exists(): path.parent.mkdir(parents=True, exist_ok=True); path.write_text('', encoding='utf8')
                m.meta['polya_src'] = dict(file=so.relative(path, s.project), qualname='', module=so.module_name(path, s.project), sha='', kind='new', after=after)
                s.changed(m); return J(ok=True)
            if not src: return J(error='This cell is not linked to a file.')
            if op == 'src_unlink': m.meta.pop('polya_src', None); s.changed(m); return J(ok=True)
            st, fsrc = so.status(src, m.content or '', s.project)
            name = f"{src['file']} :: {src.get('qualname') or so.def_name(m.content) or 'new code'}"
            if op == 'src_diff':
                where = f" (new: goes {'after ' + src['after'] if src.get('after') else 'at the end of the file'})" if st == 'new' else ''
                return J(status=st, label=so.LABELS[st], name=name + where, diff=so.udiff(fsrc or '', m.content or '', src.get('qualname') or 'new code'))
            if op == 'src_revert':
                if fsrc is None: return J(error='There is no version in the file to go back to.')
                m.content, m.output = fsrc, []
                src['sha'] = so.sha(fsrc); m.meta.pop('polya_by', None)
                s.changed(m); s.spawn(s.run_code(m))     # put the file's version back in memory too
                return J(ok=True)
            m.meta['polya_src'] = so.apply(src, m.content or '', s.project, force=bool(b.get('force')))
            m.meta.pop('polya_by', None)
            s.changed(m)
            for o in s.dlg.messages:      # other cells linked to the same file may have moved or changed status
                if o is not m and (o.meta or {}).get('polya_src', {}).get('file') == src['file']: s.push(o)
            return J(ok=True, written=name)
        except so.SourceError as e: return J(error=str(e))
    if op == 'extract':
        blocks = fenced_blocks(reply(m))
        after, ids = m, []
        for code in blocks:
            after = s.dlg.mk_message(code, msg_type='code', after=after)
            s.changed(after); ids.append(after.id)
        return J(ids=ids)
    if op == 'paste':
        after, ids = (s.dlg.msg(b['after']) if b.get('after') and s.has(b['after']) else None), []
        for item in b.get('msgs') or []:
            typ = item.get('type') if item.get('type') in MSG_TYPES else 'note'
            nm = s.dlg.mk_message(item.get('content', ''), msg_type=typ, **({'after': after} if after else {}))
            if typ == 'prompt' and item.get('reply'):
                set_reply(nm, item['reply'])
                if item.get('reply_edited'): nm.meta['polya_reply_edited'] = True
            nm.skipped, nm.pinned = int(bool(item.get('hidden'))), int(bool(item.get('pinned')))
            s.changed(nm); after = nm; ids.append(nm.id)
        return J(ids=ids)
    if op == 'settings':
        st = settings(s.dlg)
        if b.get('mode') in MODES: st['mode'] = b['mode']
        if 'model' in b: st['model'] = str(b['model']).strip()[:200]
        if 'dialog_tools' in b: st['dialog_tools'] = bool(b['dialog_tools'])
        if 'code_tools' in b: st['code_tools'] = bool(b['code_tools'])
        s.save(); return J(ok=True)
    if op == 'runall':
        todo, skipped = s.run_plan(b.get('scope', 'all'), mid)
        s.spawn(s.run_all(todo))
        return J(ok=True, count=len(todo), skipped=len(skipped))
    if op == 'stop': await s.interrupt(); return J(ok=True)
    if op == 'restart': await s.restart(); return J(ok=True)
    return J(error=f'Unknown op {op!r}')


@rt('/d/{name}/vars')
async def variables(name: str):
    s = get_session(name)
    if s is None or s.running: return J(vars={}, funcs={}, busy=True)
    v, f = await s.kernel.user_items()
    hide = set(dtools.helper.__all__)
    return J(vars=v, funcs={k: sig for k, sig in f.items() if k not in hide})


@rt('/d/{name}/definition', methods=['POST'])
async def definition(name: str, req):
    "Go to definition: where a name used in a code message comes from, with its source."
    s = get_session(name)
    b = await req.json()
    if s is None: return J(error='No such dialog')
    if s.running and not s.kernel.sidecar: return J(error='The kernel is busy. Try again when it is idle.')
    d = await s.kernel.definition(str(b.get('name', ''))[:300], str(b.get('ctx', ''))[:300])
    if 'error' not in d:
        d['html'] = code_html(d['source']) if d['source'] else ''
        if d.get('file') and Path(d['file']).is_file():
            d['rel'] = so.relative(d['file'], s.project)
            d['linkable'] = d['kind'] in ('function', 'class')
            # A link that opens the file at that line in VS Code (through the WSL remote when running under WSL).
            wsl = os.environ.get('WSL_DISTRO_NAME')
            d['open'] = (f"vscode://vscode-remote/wsl+{wsl}{d['file']}:{d['line']}" if wsl else f"vscode://file{d['file']}:{d['line']}")
    return J(**d)


@rt('/d/{name}/changes')
def changes(name: str):
    "Every linked cell that differs from its file, with the diff: what 'Apply' would write."
    s = get_session(name)
    if s is None: return J(error='No such dialog')
    items, linked = [], 0
    for m in s.dlg.messages:
        info = s.src_info(m)
        if not info: continue
        linked += 1
        if info['status'] == 'sync': continue
        _, fsrc = so.status(m.meta['polya_src'], m.content or '', s.project)
        items.append(dict(id=m.id, file=info['file'], qualname=info.get('qualname') or so.def_name(m.content) or 'new code', status=info['status'],
                          label=info['label'], after=info.get('after', ''), diff=so.udiff(fsrc or '', m.content or '', info.get('qualname') or 'new code')))
    return J(items=items, linked=linked, project=s.project or '')


@rt('/d/{name}/symbols')
def file_symbols(name: str, file: str = ''):
    "For choosing where new code goes: the project's .py files, and the functions and classes in one of them."
    s = get_session(name)
    if s is None or not s.project: return J(files=[], symbols=[], error='Start Polya with --project to write code into files.')
    root, files = Path(s.project), []
    skip = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.tox', 'build', 'dist', '.mypy_cache'}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip and not d.startswith('.')]
        files += [str(Path(dp, f).relative_to(root)) for f in fns if f.endswith('.py')]
        if len(files) > 3000: break
    syms = []
    if file:
        try: syms = so.symbols(so.resolve(file, s.project))
        except so.SourceError: pass
    return J(files=sorted(files), symbols=syms)


@rt('/d/{name}/complete', methods=['POST'])
async def complete(name: str, req):
    s = get_session(name)
    b = await req.json()
    if s is None or s.running: return J(matches=[], start=b.get('pos', 0))
    matches, start = await s.kernel.complete(b.get('code', ''), b.get('pos', 0))
    return J(matches=list(matches)[:60], start=start)


@rt('/d/{name}/export/{fmt}')
def export(name: str, fmt: str):
    s = get_session(name)
    if s is None: return PlainTextResponse('No such dialog', status_code=404)
    s.save()
    if fmt == 'ipynb': body, typ = Path(s.dlg.path_).read_text(encoding='utf8'), 'application/x-ipynb+json'
    elif fmt == 'md': body, typ = dlg2md(s.dlg), 'text/markdown'
    elif fmt == 'py': body, typ = msgs2py(s.dlg.messages, full=True), 'text/x-python'
    else: return PlainTextResponse('Unknown format', status_code=404)
    return Response(body, media_type=typ, headers={'Content-Disposition': f'attachment; filename="{name}.{fmt}"'})


@rt('/api/tool', methods=['POST'])
async def api_tool(req):
    "Dialog tools called from inside a dialog's own kernel (see polya/helper.py)."
    if not secrets.compare_digest(req.headers.get('x-polya-token', ''), TOKEN): return JSONResponse(dict(error='Bad token'), status_code=403)
    b = await req.json()
    s = get_session(b.get('dialog', ''))
    if s is None: return J(error='No such dialog')
    try: return J(result=await dtools.call(s, 'kernel', b.get('name'), b.get('args') or {}))
    except Exception as e: return J(error=f'{type(e).__name__}: {e}')
