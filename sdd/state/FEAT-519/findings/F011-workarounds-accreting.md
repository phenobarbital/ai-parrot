---
id: F011
query_id: Q017
type: git_log
intent: Record two commits that landed on this exact surface DURING the research run and what they imply
executed_at: 2026-09-02T22:35:00Z
parent_id: F004
depth: 1
---

# F011 — Two fixes landed on this surface mid-research; both are new workarounds around the same seam, and the root cause is untouched

## Summary

While this research ran, `HEAD` on `dev` advanced by two commits authored the
same evening, both targeting the CLI console. Neither changes
`render_stream_chunk`'s raw `sys.stdout.write` — instead each adds another
compensating layer around the `Rich`/`patch_stdout()` seam. There are now
**three** stacked workarounds for one unaddressed design conflict:
(1) every Console bypasses the proxy via `file=sys.__stdout__`,
(2) `_BlockingSafeFile` retries writes that raise `BlockingIOError` because
`patch_stdout()` puts the fd in non-blocking mode, and
(3) `_mute_stream_loggers()` raises console log handlers to WARNING for the
duration of a stream so log lines stop interleaving with streamed tokens.
This is direct evidence for hypothesis 2: the surface is accreting point fixes
because there is no presentation seam to fix properly.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 27-49
  symbol: `_mute_stream_loggers` (added by 3b5e4fed5)
  excerpt: |
    # Minimum level enforced on console handlers while streaming tokens, so
    # that DEBUG/INFO messages from the LLM client don't interleave with the
    # streamed text the user is reading.
    _STREAM_LOG_FLOOR = logging.WARNING

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 247,279
  symbol: `AgentREPL.send_stream` mute/restore bracket
  excerpt: |
    saved_levels = _mute_stream_loggers()
    ...
    _restore_stream_loggers(saved_levels)

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 22-33
  symbol: `_BlockingSafeFile` (added by 7c2790044)
  excerpt: |
    When ``prompt_toolkit.patch_stdout()`` puts ``sys.__stdout__`` into
    non-blocking mode, a large ``Rich.Console.print()`` can overflow the
    kernel pipe buffer and raise ``BlockingIOError`` (errno 11 / EAGAIN).
    This wrapper catches the error, waits briefly for the fd to drain,
    and retries

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 80-82
  symbol: `ResponseRenderer.__init__`
  excerpt: |
    self.console = Console(
        file=_BlockingSafeFile(sys.__stdout__), force_terminal=True
    )

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 248-260
  symbol: `render_stream_chunk` — UNCHANGED by both commits
  excerpt: |
    def render_stream_chunk(self, text: str) -> None:
        """Write a streamed token chunk directly to stdout."""
        ...
            sys.stdout.write(text)

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 154-163
  symbol: bot cleanup on exit (added by 7c2790044)
  excerpt: |
    if hasattr(bot, "cleanup") and callable(bot.cleanup):
        try:
            await bot.cleanup()

## Notes

Commits (author Jesus, 2026-09-02):
- `3b5e4fed5` "fix over REPL of CLI agents" — repl.py +42 lines (log muting)
- `7c2790044` "fixing the usage of LLMs in CLI console" — renderer.py +42
  (`_BlockingSafeFile`), agent_repl.py +11 (cleanup), plus client changes
  outside this feature's scope.

Log interleaving during streaming is a **new symptom** not named in the original
request; it is a further consequence of streaming tokens outside a managed
render region.
