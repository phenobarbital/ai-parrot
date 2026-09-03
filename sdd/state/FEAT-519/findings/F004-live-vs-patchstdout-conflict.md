---
id: F004
query_id: Q003,Q004
type: read
intent: Capture the documented technical reason Rich Live was abandoned in the agent REPL
executed_at: 2026-09-02T21:58:30Z
parent_id: F003
depth: 1
---

# F004 — The documented blocker: `rich.live.Live` vs `prompt_toolkit.patch_stdout()`

## Summary

Two docstrings in `renderer.py` record why the raw-write hack exists.
`patch_stdout()` replaces `sys.stdout` with a `StdoutProxy` that mangles ANSI
escapes (ESC renders as a literal `?`), so `Live`'s cursor-control sequences
(`\x1b[2K`, `\x1b[?25l`) appear as `?[2K` garbage. Two workarounds are already in
place: every `Console` is constructed with `file=sys.__stdout__,
force_terminal=True` to bypass the proxy, and streaming abandoned `Live`
altogether. This conflict is the single technical constraint that decides the
architecture of any refactor.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 69-82
  symbol: `ResponseRenderer.__init__` docstring
  excerpt: |
    The Console writes to ``sys.__stdout__`` (the original file
    descriptor) instead of ``sys.stdout``.  Inside the REPL,
    ``prompt_toolkit.patch_stdout()`` replaces ``sys.stdout``
    with a proxy that corrupts ANSI escape sequences — the ESC
    byte (``\x1b``) is rendered as a literal ``?``.

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 238-244
  symbol: `render_stream_start` docstring
  excerpt: |
    Uses direct incremental writes (``sys.stdout``) instead of
    ``rich.live.Live``.  ``Live`` emits ANSI cursor-control sequences
    (``\x1b[2K``, ``\x1b[?25l``, …) that conflict with
    ``prompt_toolkit.patch_stdout()`` — the patched stdout does not
    forward them correctly, so they render as literal ``?[2K`` garbage.

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 127-128
  symbol: `AgentREPL.__init__`
  excerpt: |
    # Bypass prompt_toolkit's StdoutProxy — see renderer.py docstring.
    self.console = Console(file=sys.__stdout__, force_terminal=True)

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 154-157
  symbol: `AgentREPL.run`
  excerpt: |
    with patch_stdout():
        while True:
            try:
                text = await session.prompt_async(prompt)

## Notes

Three separate `Console(file=sys.__stdout__, force_terminal=True)` instances
exist (`agent_repl.py:25`, `repl.py:128`, `renderer.py:80`) — no shared console,
so theming/width/record settings cannot be configured in one place.
