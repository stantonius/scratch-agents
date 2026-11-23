"`polya` command: start the server."
import os
from pathlib import Path

from fastcore.script import call_parse


@call_parse
def main(
    dir: str = 'dialogs',       # Folder holding the dialog .ipynb files (created if missing); kernels start here
    host: str = '127.0.0.1',    # Address to listen on. Keep 127.0.0.1 unless you understand the risk: anyone who can reach it can run code
    port: int = 5001,           # Port to listen on
    model: str = None,          # Default model name to send to the endpoint (or set POLYA_MODEL)
    base_url: str = None,       # Base URL of your LLM endpoint, e.g. https://llm-gateway.example.com/v1 (or set POLYA_BASE_URL)
    api: str = None,            # Wire format the endpoint speaks: openai_chat (default with a base URL), openai, anthropic or gemini (or set POLYA_API)
    kernel: str = None,         # Jupyter kernelspec to run code with (default 'py' = ipymini; 'python3' = ipykernel if installed)
    project: str = None,        # Your codebase: kernels start in this folder with it on the import path (default: kernels start in `dir`)
):
    "Start Polya. The API key is read from POLYA_API_KEY (never passed on the command line)."
    for k, v in (('POLYA_MODEL', model), ('POLYA_BASE_URL', base_url), ('POLYA_API', api), ('POLYA_KERNEL', kernel)):
        if v: os.environ[k] = v
    import secrets, uvicorn
    Path(dir).mkdir(parents=True, exist_ok=True)
    # The coding agent's token is kept between runs so its MCP configuration keeps working.
    tokfile = Path(dir) / '.polya-agent-token'
    if not tokfile.exists():
        tokfile.touch(mode=0o600)
        tokfile.write_text(secrets.token_urlsafe(24))
    os.environ['POLYA_AGENT_TOKEN'] = tokfile.read_text().strip()
    from . import app as server
    server.CFG['dir'] = Path(dir)
    server.CFG['project'] = project
    server.CFG['url'] = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    print(f"Polya: {server.CFG['url']}   dialogs: {server.CFG['dir'].resolve()}")
    print(f"AI endpoint: {os.environ.get('POLYA_BASE_URL') or '(provider default for the model)'}   "
          f"model: {os.environ.get('POLYA_MODEL') or 'claude-sonnet-5-5'}   key: {'set' if os.environ.get('POLYA_API_KEY') else 'POLYA_API_KEY not set'}")
    print(f"Kernels start in: {Path(project).resolve() if project else server.CFG['dir'].resolve()}")
    print(f"Coding agent (MCP): {server.CFG['url']}/mcp   token in {tokfile}")
    print(f'  claude mcp add --transport http polya {server.CFG["url"]}/mcp -H "Authorization: Bearer $(cat {tokfile.resolve()})"')
    uvicorn.run(server.app, host=host, port=port, log_level='warning')
