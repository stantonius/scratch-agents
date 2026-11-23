"HTML for messages. Markdown via mdhtml (paste-safe: scripts and styles render as text), code via fastpylight."
import html, re
from functools import lru_cache

import fastpylight
from aihist import fmt_tools
from mdhtml import md2mdhtml, mdhtml2html

from .dialogs import _src, msg_tokens, reply

esc = html.escape
_ansi = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
_bad_href = re.compile(r'(href|src)="\s*(javascript|vbscript|data):[^"]*"', re.I)


def strip_ansi(s): return _ansi.sub('', s)


@lru_cache(maxsize=512)
def md(src):
    if not (src or '').strip(): return ''
    try: out = str(mdhtml2html(md2mdhtml(src), auto_ids=False))
    except Exception: out = f'<pre>{esc(src)}</pre>'
    return _bad_href.sub(r'\1="#"', out)


@lru_cache(maxsize=512)
def code_html(src, lang='python'):
    try: return fastpylight.highlight_spans(src, lang)
    except Exception: return f'<pre><code>{esc(src)}</code></pre>'


def theme_css():
    "Syntax colours for light and dark, generated from fastpylight's themes."
    light = fastpylight.theme_css('github_light', 'pre code')
    dark = fastpylight.theme_css('github_dark', 'pre code')
    return f'{light}\n@media (prefers-color-scheme: dark) {{\n{dark}\n}}'


def output_html(o):
    t = o.get('output_type')
    if t == 'stream':
        cls = 'o-stream' + (' o-stderr' if o.get('name') == 'stderr' else '')
        return f'<pre class="{cls}">{esc(strip_ansi(_src(o.get("text"))))}</pre>'
    if t == 'error':
        tb = strip_ansi('\n'.join(o.get('traceback') or [])) or f"{o.get('ename')}: {o.get('evalue')}"
        return f'<pre class="o-error">{esc(tb)}</pre>'
    data = o.get('data') or {}
    if 'text/html' in data: return f'<div class="o-html">{_src(data["text/html"])}</div>'
    if 'image/svg+xml' in data: return f'<div class="o-img">{_src(data["image/svg+xml"])}</div>'
    for mime in ('image/png', 'image/jpeg', 'image/gif'):
        if mime in data: return f'<div class="o-img"><img src="data:{mime};base64,{esc(_src(data[mime]).strip())}"></div>'
    if 'text/markdown' in data: return f'<div class="o-md md">{md(_src(data["text/markdown"]))}</div>'
    if 'text/plain' in data: return f'<pre class="o-result">{esc(_src(data["text/plain"]))}</pre>'
    return ''


ICONS = dict(run='▶', edit='✎', reply='✎ reply', extract='⤓ code', hide='hide', pin='pin', up='↑', down='↓', delete='✕')
TIPS = dict(run='Run (Ctrl+Enter)', edit='Edit (Enter)', reply="Edit the AI's reply (n)", extract='Copy code blocks into code messages (w)',
            hide='Hide from / show to the AI (h)', pin='Pin: always keep in the AI context (p)', up='Move up (Alt+↑)',
            down='Move down (Alt+↓)', delete='Delete (x cuts it)')


def _btn(act): return f'<button class="act" data-act="{act}" title="{esc(TIPS[act])}">{ICONS[act]}</button>'


def msg_html(m, live=None, running=False, error=''):
    "One message. `live` is the reply text while the AI is still streaming it."
    t = m.msg_type
    cls = f'msg t-{t}' + (' is-hidden' if m.skipped else '') + (' is-pinned' if m.pinned else '') + (' is-running' if running else '')
    acts = ['run'] if t in ('code', 'prompt') else []
    acts += ['edit']
    if t == 'prompt': acts += ['reply', 'extract']
    acts += ['hide', 'pin', 'up', 'down', 'delete']
    by = (m.meta or {}).get('polya_by')
    if by in ('ai', 'agent'): cls += f' by-{by}'
    who = {'ai': ("added by AI", "Added by the notebook's AI and not edited by you since"),
           'agent': ('added by agent', 'Added by your coding agent and not edited by you since')}.get(by)
    flags = (f'<span class="flag f-by" title="{who[1]}">{who[0]}</span>' if who else '') + \
            ('<span class="flag f-pin" title="Pinned: always in the AI context">pinned</span>' if m.pinned else '') + \
            ('<span class="flag f-hide" title="Hidden from the AI">hidden from AI</span>' if m.skipped else '')
    head = (f'<div class="mhead"><span class="badge">{t}</span>{flags}'
            f'<span class="tok" title="Approximate tokens this message adds to the AI context">~{msg_tokens(m)} tok</span>'
            f'<span class="acts">{"".join(_btn(a) for a in acts)}</span></div>')

    src = m.content or ''
    if t == 'code': inp = code_html(src) if src.strip() else '<pre class="empty">(empty)</pre>'
    elif t == 'raw': inp = f'<pre class="rawtext">{esc(src)}</pre>'
    else: inp = f'<div class="md">{md(src)}</div>' if src.strip() else '<div class="md empty">(empty)</div>'

    out = ''
    if t == 'code':
        out = ''.join(output_html(o) for o in (m.output or []))
        if running and not out: out = '<div class="working">running…</div>'
    elif t == 'prompt':
        text = live if live is not None else reply(m)
        if text.strip(): out = f'<div class="reply md">{md(fmt_tools(text))}</div>'
        if running: out += '<div class="working">thinking…</div>'
        if error: out += f'<div class="o-error ai-error">{esc(error)}</div>'
    return (f'<div class="{cls}" id="m-{m.id}" data-id="{m.id}" data-type="{t}">{head}'
            f'<div class="min">{inp}</div><div class="mout">{out}</div></div>')
