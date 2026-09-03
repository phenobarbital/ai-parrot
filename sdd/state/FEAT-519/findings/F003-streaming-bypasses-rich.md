---
id: F003
query_id: Q003,Q005
type: read
intent: Determine whether REPL output goes through print() or a renderer, and locate the raw stdout write
executed_at: 2026-09-02T21:58:00Z
parent_id: null
depth: 0
---

# F003 — ROOT CAUSE: the default streaming path writes raw `sys.stdout.write()`, bypassing Rich entirely

## Summary

`render_stream_chunk()` is the single place in the whole interactive CLI that
writes unformatted bytes to the terminal. Because `REPLConfig.streaming`
defaults to `True`, this raw path — not the Markdown path — is what users see by
default: no markdown, no syntax highlighting, no soft-wrap, no theming. A
repo-wide grep for `^\s*print\(` under `parrot/cli` returns **zero** matches; the
only raw writes are `renderer.py:257` and `tool_worker.py:39-41` (the latter is
an IPC result marker protocol, not display). The user's "direct print to stdout"
complaint is therefore real but localised to exactly one function.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 248-260
  symbol: `ResponseRenderer.render_stream_chunk`
  excerpt: |
    def render_stream_chunk(self, text: str) -> None:
        """Write a streamed token chunk directly to stdout."""
        import sys
        self._stream_buffer += text
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 82-85
  symbol: `REPLConfig.streaming`
  excerpt: |
    agent_name: str
    streaming: bool = True

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 185-189
  symbol: `AgentREPL.run` dispatch
  excerpt: |
    if self.config.streaming:
        await self.send_stream(text)
    else:
        response = await self.send(text)
        self.renderer.render(response)

- path: `packages/ai-parrot/src/parrot/cli/repl.py`
  lines: 256-271
  symbol: `AgentREPL.send_stream`
  excerpt: |
    async for chunk in stream:
        ...
        accumulated += text
        self.renderer.render_stream_chunk(text)

- path: `packages/ai-parrot/src/parrot/cli/tool_worker.py`
  lines: 39-41
  symbol: IPC result markers (NOT display output)
  excerpt: |
    sys.stdout.write(RESULT_BEGIN_MARKER + "\n")
    sys.stdout.write(json.dumps(payload, default=str))

## Notes

`_stream_buffer` accumulates the full text but is discarded at
`render_stream_end` (line 280) — the accumulated markdown is never re-rendered.
A minimal fix (re-render the buffer as Markdown on stream end) is available
without any new dependency.
