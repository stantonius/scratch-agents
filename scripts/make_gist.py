"""Build one Markdown file that holds the whole project, for copying into a gist.

    python scripts/make_gist.py [output.md]        (default: polya-gist.md in the current folder)

The output starts with a project outline and install instructions, then every file under a
heading that gives its path. It also carries a short unpack script that turns the single file
back into the project folder. The vendored CodeMirror editor is not included (it is about
500 KB of third-party JavaScript); scripts/fetch_codemirror.sh fetches it.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE = '~' * 10          # no project file contains a line of ten tildes, so this cannot end a block early
MARK = '#### FILE: '
SKIP = ('polya/static/vendor/', 'docs/', '.gitignore')
LANG = {'.py': 'python', '.js': 'javascript', '.css': 'css', '.toml': 'toml', '.md': 'markdown', '.sh': 'bash'}

ABOUT = {
    'pyproject.toml': 'package definition and the list of libraries',
    'README.md': 'full documentation: the method, every feature, security notes, limits',
    'scripts/fetch_codemirror.sh': 'fetches the editor files into polya/static/vendor (run once)',
    'scripts/make_gist.py': 'builds this single-file copy of the project',
    'polya/__init__.py': 'version',
    'polya/__main__.py': 'lets you run `python -m polya`',
    'polya/cli.py': 'the `polya` command: options, start-up messages',
    'polya/app.py': 'the web server: pages, live updates, every action a browser can take',
    'polya/dialogs.py': 'dialogs on disk (.ipynb), settings, the welcome and SETUP templates',
    'polya/kernel.py': 'one Jupyter kernel per dialog: run code, tool calls, completion',
    'polya/helper.py': 'functions preloaded in every kernel: dialog tools, code-reading tools, the sandbox, run-in-module',
    'polya/tools.py': 'what the dialog tools do, and who may do what',
    'polya/ai.py': "the notebook AI's turn: system prompts, modes, tools, the model call",
    'polya/agent.py': 'the MCP endpoint for an outside coding agent',
    'polya/source.py': 'linking cells to files: locate, compare, diff, write back',
    'polya/render.py': 'HTML for messages',
    'polya/static/app.js': 'the browser side: keyboard, editors, panels',
    'polya/static/app.css': 'styles',
    'polya/skills/grilling/SKILL.md': "Matt Pocock's grilling skill (MIT), used by grill mode",
    'polya/skills/LICENSE-mattpocock-skills': 'its licence',
    'agent-skills/polya-explore/SKILL.md': 'skill for your coding agent: build a dialog that walks through a flow',
    'tests/run_e2e.sh': 'runs every test below',
    'tests/test_source.py': '31 edge cases for write-back (no server needed)',
    'tests/corpus_check.py': 'runs write-back over thousands of real Python files',
    'tests/fake_llm.py': 'a scripted stand-in for an LLM endpoint, for the browser tests',
    'tests/agent_bridge.py': 'drives the MCP endpoint as a coding agent would',
    'tests/e2e/_check.js': 'the checker the browser tests share',
}
ORDER = ['pyproject.toml', 'README.md', 'scripts/', 'polya/__init__.py', 'polya/__main__.py', 'polya/cli.py', 'polya/app.py', 'polya/dialogs.py',
         'polya/kernel.py', 'polya/helper.py', 'polya/tools.py', 'polya/ai.py', 'polya/agent.py', 'polya/source.py', 'polya/render.py',
         'polya/static/', 'polya/skills/', 'agent-skills/', 'tests/run_e2e.sh', 'tests/test_source.py', 'tests/corpus_check.py', 'tests/fake_llm.py',
         'tests/agent_bridge.py', 'tests/e2e/', 'tests/sample_project/']

UNPACK = r'''import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding='utf8')
out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else 'polya')
n = 0
for m in re.finditer(r'^#### FILE: (\S+)\n~{10}[^\n]*\n(.*?)^~{10}$', text, flags=re.S | re.M):
    p = out / m.group(1)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(m.group(2), encoding='utf8', newline='')
    n += 1
print(f'wrote {n} files to {out}/')
'''


def files():
    names = [f for f in subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).split('\n') if f and not f.startswith(SKIP)]
    rank = lambda f: next((i for i, o in enumerate(ORDER) if f == o or (o.endswith('/') and f.startswith(o))), len(ORDER))
    return sorted(names, key=lambda f: (rank(f), f))


def tree(names):
    lines, seen = ['polya/                      <- the project folder (any name)'], set()
    for f in sorted(names + ['polya/static/vendor/codemirror.js', 'polya/static/vendor/codemirror-extras.js', 'polya/static/vendor/codemirror.css'],
                    key=lambda f: [(0, p) if i < f.count('/') else (1, p) for i, p in enumerate(f.split('/'))]):
        parts = f.split('/')
        for d in range(1, len(parts)):
            folder = '/'.join(parts[:d])
            if folder not in seen:
                seen.add(folder)
                lines.append('  ' * d + parts[d - 1] + '/')
        note = '(not in this file: fetched by scripts/fetch_codemirror.sh)' if '/vendor/' in f else ABOUT.get(f, '')
        lines.append(f"{'  ' * len(parts)}{parts[-1]:<{max(1, 30 - 2 * len(parts))}}{'  ' + note if note else ''}".rstrip())
    return '\n'.join(lines)


def deps():
    import tomllib
    proj = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    raw = (ROOT / 'pyproject.toml').read_text().split('dependencies = [', 1)[1].split(']', 1)[0]
    rows = []
    for line in raw.strip().splitlines():
        spec, _, why = line.strip().partition('#')
        spec = spec.strip().strip(',').strip('"')
        if spec: rows.append(f'| `{spec}` | {why.strip() or "used throughout"} |')
    return proj['requires-python'], '\n'.join(rows)


def build():
    names = files()
    pyver, table = deps()
    total = sum(len((ROOT / f).read_text(encoding='utf8').splitlines()) for f in names)
    out = [f'''# Polya — the whole project in one file

A small, self-hosted notebook for working the "solve it" way: code, notes and AI prompts in one
editable document, linked to an existing Python codebase, talking only to the LLM endpoint you
configure. Built from Answer.AI's open-source libraries. Not affiliated with Answer.AI or Solveit.

This file holds {len(names)} files ({total:,} lines). `README.md`, further down, is the full
documentation. **Status:** every test passes against a scripted stand-in for a model; it has not
been run against a real model or a real coding agent. Use a branch the first time you let it
write to your repository.

## 1. Project outline

```
{tree(names)}
```

## 2. Get the files out of this document

Every file below is under a heading `{MARK}<path>` followed by a block fenced with ten tildes.
Save this document as `polya-gist.md`, save the script below as `unpack.py` next to it, and run
`python unpack.py polya-gist.md polya`. It writes each file to its path under `polya/`.

```python
{UNPACK.rstrip()}
```

(Or copy files out by hand: each block's content goes in the file named by its heading.)

## 3. Install

Needs Linux, macOS or WSL, Python {pyver}, and `curl` and `tar` for one step.

```bash
cd polya
bash scripts/fetch_codemirror.sh          # once: fetches the editor (CodeMirror 5, MIT) into polya/static/vendor
python -m venv .venv && . .venv/bin/activate
pip install .                             # installs Polya and the libraries listed below
sudo apt install ripgrep                  # optional: fast code search for the AI (it uses grep without it)
```

`pip install .` installs these, with whatever they in turn need:

| Library | What Polya uses it for |
|---|---|
{table}

If your machine cannot reach `registry.npmjs.org`, get `codemirror-5.65.21.tgz` another way and
run `CODEMIRROR_TGZ=/path/to/codemirror-5.65.21.tgz bash scripts/fetch_codemirror.sh`.

## 4. Run

```bash
export POLYA_BASE_URL=https://your-llm-gateway.example.com/v1    # LiteLLM proxy, agentgateway, ...
export POLYA_API_KEY=...                                         # read from the environment only
export POLYA_MODEL=your-model-name
polya --dir ~/dialogs/myproject --project ~/code/myproject       # then open http://127.0.0.1:5001
```

It listens on `127.0.0.1` only and has no login: it runs code, so do not expose it on a network.
To run the tests: `pip install matplotlib pandas`, have `node` with the `playwright` package and
a Chromium, then `bash tests/run_e2e.sh`.

## 5. The files
''']
    for f in names:
        body = (ROOT / f).read_text(encoding='utf8')
        assert FENCE not in body, f'{f} contains the fence'
        assert body == '' or body.endswith('\n'), f'{f} does not end with a newline'
        desc = ABOUT.get(f)
        out.append(f"{MARK}{f}\n{FENCE}{LANG.get(Path(f).suffix, 'text')}\n{body}{FENCE}\n" + (f'\n*{desc}*\n' if desc else ''))
    return '\n'.join(out), names


if __name__ == '__main__':
    target = Path(sys.argv[1] if len(sys.argv) > 1 else 'polya-gist.md')
    text, names = build()
    target.write_text(text, encoding='utf8')
    print(f'{target}: {len(names)} files, {len(text):,} characters, {len(text.splitlines()):,} lines')
