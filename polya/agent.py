"""The bridge for an outside coding agent (Claude Code, Codex, …): an MCP server mounted at /mcp.

The point is that the agent and the human look at the same thing. The agent reads the dialog,
and anything it wants to try it runs *as a cell in the dialog*, in the dialog's own kernel, where
the human can read it, re-run it, edit it or delete it. Cells the agent adds are marked as its
own, and it cannot change cells it did not write.
"""
from mcpmini.core import MCPServer, create_app

from . import tools as dtools

INSTRUCTIONS = """Polya is the notebook your user works in to understand and control the code they contribute. A "dialog" is a notebook of messages (code cells with outputs, markdown notes, and prompts to the notebook's own AI), attached to a live Python kernel that has the user's project imported.

Your user wants to see what you do and why. Work like this:
- Before proposing or making a change, read the relevant dialog (view_dlg, then read_msg) to see what the user has already tried and concluded. Their notes are requirements.
- Run experiments, reproductions and checks as cells in the dialog (add_msg with msg_type='code' and run=true), NOT in your own shell or a private interpreter. A result the user cannot see in the dialog does not count as evidence.
- Keep each code cell to one small step with an output worth checking: a few lines, ending in an expression. Add a short note before a group of cells saying what you are checking and what you expect.
- Use kernel_state and source_of to see what is actually loaded in the user's kernel instead of guessing from files.
- You can change or delete only the messages you added. To suggest a change to the user's own message, add a new message with the suggestion.
- When you edit files in the repository, add a note to the dialog saying which files you changed and why, and a code cell the user can run to see the change working.
- When the user asks to explore or understand a part of the codebase ("walk me through the auth flow"), build them a dialog for it: create_dialog, then a short note saying what the flow does and where it starts, then for each step in call order a one-or-two-sentence note followed by add_source for that function, and after the first step and wherever it helps a small code cell that actually calls the code with realistic inputs (run it so they see the output). Bring in the functions that matter to the flow, not whole files. End with a note listing what you left out and open questions. Project code always goes in through add_source so the cells stay linked to the files.
- Do not flood the dialog. Remove your own cells that turned out to be dead ends, or say in a note that they were."""


def make_server():
    from . import app   # late import: the app module mounts this server

    def _s(dialog):
        s = app.get_session(dialog)
        if s is None: raise ValueError(f'No dialog named {dialog!r}. Use list_dialogs.')
        return s

    async def list_dialogs() -> str:  # One dialog name per line
        "Names of the dialogs in the user's Polya folder, with a marker on those whose kernel is running."
        return '\n'.join(n + ('  (kernel running)' if n in app.sessions and app.sessions[n].kernel.alive else '') for n in app.dialog_names()) or '(no dialogs)'

    async def view_dlg(
        dialog: str,         # Dialog name, from list_dialogs
        full: bool = False,  # True returns every message in full with outputs and AI replies; False returns one preview line per message
    ) -> str:  # The dialog, in order. Each message starts with its id.
        "Read a dialog: an outline by default, or everything with `full`."
        s = _s(dialog)
        return s.dlg.view(incl_out=True) if full else await dtools.call(s, 'agent', 'view_dlg', {})

    async def read_msg(
        dialog: str,  # Dialog name
        id: str,      # Message id
    ) -> str:  # The message with line numbers, plus its output (code) or reply (prompt)
        "Read one message in full."
        return await dtools.call(_s(dialog), 'agent', 'read_msg', dict(id=id))

    async def find_msgs(
        dialog: str,           # Dialog name
        pattern: str = '',     # Regex to search message content for
        msg_type: str = None,  # Only 'note', 'code', 'prompt' or 'raw'
    ) -> str:  # One preview line per matching message
        "Find messages in a dialog whose content matches `pattern`."
        return await dtools.call(_s(dialog), 'agent', 'find_msgs', dict(pattern=pattern, msg_type=msg_type))

    async def add_msg(
        dialog: str,             # Dialog name
        content: str,            # Text of the new message
        msg_type: str = 'note',  # 'note' (markdown) or 'code' (Python)
        after: str = '',         # Id of the message to put it after (default: the end of the dialog)
        before: str = '',        # Id of the message to put it before (instead of `after`)
        run: bool = False,       # For code: run it now in the dialog's kernel and return its output
    ) -> str:  # The new message's id, and its output if `run`
        "Add a message to the user's dialog, where they will see it marked as yours. Use this to run code: the user sees the cell and its output."
        if msg_type not in ('note', 'code'): raise ValueError("msg_type must be 'note' or 'code'")
        return await dtools.call(_s(dialog), 'agent', 'add_msg', dict(content=content, msg_type=msg_type, after=after, before=before, run=run))

    async def add_source(
        dialog: str,      # Dialog name
        symbol: str,      # Function, class or method name as it appears in the file, e.g. `order_total` or `Order.subtotal`
        file: str,        # The .py file that defines it, relative to the project folder, e.g. `acme/orders.py`
        after: str = '',  # Id of the message to put it after (default: the end of the dialog)
    ) -> str:  # The new message's id and what it is linked to
        "Bring a function, class or method from the repository into the dialog as a linked code cell. Polya copies the code from the file exactly and keeps the cell linked to it, so the user can run it, change it, see how it differs from the file, and write it back. ALWAYS use this for project code; never retype project code with add_msg."
        return await dtools.call(_s(dialog), 'agent', 'add_source', dict(symbol=symbol, file=file, after=after))

    async def create_dialog(
        dialog: str,  # Name for the new dialog: letters, digits, spaces, dots, dashes, underscores
    ) -> str:  # Confirmation
        "Create a new, empty dialog, for example to lay out one flow through the code. Fails if the name is taken."
        from .dialogs import load, valid_name
        if not valid_name(dialog): raise ValueError('Names may use letters, digits, spaces, dots, dashes and underscores.')
        path = app.CFG['dir'] / f'{dialog}.ipynb'
        if path.exists(): raise ValueError(f'A dialog named {dialog!r} already exists.')
        load(path).save()
        return f'Created dialog {dialog!r}. The user can open it at {app.CFG["url"]}/d/{dialog}'

    async def run_msg(
        dialog: str,  # Dialog name
        id: str,      # Id of a code message
    ) -> str:  # Its output as text
        "Run (or re-run) a code message in the dialog's kernel and return its output."
        return await dtools.call(_s(dialog), 'agent', 'run_msg', dict(id=id))

    async def update_msg(
        dialog: str,          # Dialog name
        id: str,              # Id of a message that you added
        content: str = None,  # New content
    ) -> str:  # Confirmation
        "Replace the content of a message you added. Messages written by the user cannot be changed."
        return await dtools.call(_s(dialog), 'agent', 'update_msg', dict(id=id, content=content))

    async def del_msg(
        dialog: str,  # Dialog name
        id: str,      # Id of a message that you added
    ) -> str:  # Confirmation
        "Delete a message you added. Messages written by the user cannot be deleted."
        return await dtools.call(_s(dialog), 'agent', 'del_msg', dict(id=id))

    async def kernel_state(
        dialog: str,  # Dialog name
    ) -> str:  # Variables with their values, then functions with their signatures
        "What is defined in the dialog's kernel right now: the user's variables and functions."
        v, f = await _s(dialog).kernel.user_items()
        hide = set(dtools.helper.__all__)
        return 'Variables:\n' + ('\n'.join(f'  {k} = {val}' for k, val in v.items()) or '  (none)') + \
               '\nFunctions:\n' + ('\n'.join(f'  {k}{sig}' for k, sig in f.items() if k not in hide) or '  (none)')

    async def source_of(
        dialog: str,  # Dialog name
        symbol: str,  # Dotted name as written in a code message, e.g. `mypkg.orders.total`
    ) -> str:  # File, line and source code
        "Source of a function, class or module exactly as the dialog's kernel has it loaded (it must already be imported there)."
        return await _s(dialog).kernel.call('source_of', dict(name=symbol))

    return MCPServer('polya', [list_dialogs, create_dialog, view_dlg, read_msg, find_msgs, add_source, add_msg, run_msg, update_msg, del_msg, kernel_state, source_of],
                     instructions=INSTRUCTIONS)


def mcp_app(token):
    "ASGI app for the bridge, served at /mcp. Requests need `Authorization: Bearer <token>`."
    inner = create_app(make_server(), token=token, path='/mcp')

    class Bridge:   # a class instance, so the router treats it as an ASGI app rather than a request handler
        async def __call__(self, scope, receive, send): await inner(scope, receive, send)
    return Bridge()
