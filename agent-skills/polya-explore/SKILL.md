---
name: polya-explore
description: Build a Polya dialog that walks the user through one flow or area of this codebase (for example "explore the auth flow", "show me how an order total is computed"), using the polya MCP tools. Use when the user asks to explore, understand, trace or be walked through part of the code in Polya.
---

The user wants to understand a part of this codebase by running it and changing it, not by reading a summary. Build them a Polya dialog for it. They will work through it cell by cell, edit functions to see what happens, and write their changes back to the files from Polya.

You need the `polya` MCP server connected. If its tools are missing, say so and stop.

## Find the flow first

Before touching Polya, work out the flow in the repository with your own tools: the entry point, the functions it calls in order, and where the data comes from. Read the code; do not guess. Leave out anything that is not on the path the user asked about.

## Build the dialog

1. `create_dialog` with a short name for the flow (`auth-flow`). If it exists, ask whether to add to it or pick another name.
2. `add_msg` a note: one paragraph saying what the flow does, where it starts, and the order of the steps as a numbered list of function names.
3. For each step, in call order:
   - `add_msg` a note of one or two sentences: what this function is responsible for and what to notice in it.
   - `add_source` with the function's name and file. **Project code always goes in with `add_source`, never typed into `add_msg`.** Polya copies it from the file exactly and keeps the cell linked to the file, which is what lets the user see what they changed and write it back. One function, method or small class per cell. Give the method name (`Order.subtotal`), not the whole class, unless the class is short.
4. After the entry point, and wherever it helps, `add_msg` a code cell with `run=true` that actually calls the code with small realistic inputs, so the user sees real output. If the flow needs a database, network service or credentials, do not fake results: add a note saying what is needed, and build the smallest stand-in you can (an in-memory object, a fixture the project already has) in a clearly labelled code cell.
5. Finish with a note: what you left out and why, and two or three things worth trying ("change X in `validate_token` and re-run the cell above").

## Rules

- Keep it to what one person can work through in a sitting: usually 5 to 15 linked cells. If the flow is bigger, split it and tell the user what the other dialogs would cover.
- Do not edit the repository's files while building an exploration dialog.
- Do not change the code in a linked cell. It must match the file when the user first sees it.
- When you are done, give the user the dialog's link and a two-line summary. The dialog is the deliverable.
