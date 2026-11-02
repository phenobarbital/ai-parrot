---
id: FC-009
query_id: Q029
type: grep
intent: "Locate how codex is invoked as a coder backend and whether --json / the event stream is parsed."
executed_at: 2026-10-30T22:56:00Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-009 — `codex exec --json` is already streamed and parsed; the dispatcher simply never reads a usage field

## Summary

`flows/dev_loop/dispatchers/codex.py` (35.5 KB) is a mature dispatcher that "shells out to
``codex exec --json`` and streams its" events, builds the command line explicitly
(`["codex", "exec", "--cd", cwd, ... "--json", "--output-schema", schema_path, "-o", output_path]`),
spawns via `asyncio.create_subprocess_exec`, and already handles `turn.failed` / `error`
events, `codex exec review` and `codex exec resume --last` shapes. The JSON event stream is
therefore **already available and already being decoded**.

A grep for `usage|token|turn.completed|input_tokens` across all 35.5 KB of that dispatcher
returns **no usage extraction whatsoever** — the only matches are ContextVar reset tokens
(`_host_token`, `_labels_token`). `models/codex.py` likewise defines only three profile
classes and no usage model. This is the exact code-level cause of FC-005's empirical result
(codex = 660 attempt rows, 910 total input tokens). The work for the Codex seat is
**one parser on a stream that is already open**, not a new ingestion path.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 5
  symbol: `module docstring`
  excerpt: |
    dev-loop graph. Shells out to ``codex exec --json`` and streams its

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 532-544
  symbol: `command builder`
  excerpt: |
    cmd = [self.codex_bin, "exec", "--cd", cwd]
    ...
    cmd += ["--json", "--output-schema", schema_path, "-o", output_path]

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 124
  symbol: `_failure_text`
  excerpt: |
    """Return the failure text of a ``codex exec --json`` ``error``/``turn.failed`` event."""

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 383
  symbol: `error handling comment`
  excerpt: |
    # With `--json` codex reports the real failure (API 4xx, auth, quota) as an

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 583
  symbol: `process spawn`
  excerpt: |
    return await asyncio.create_subprocess_exec(

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 278-293
  symbol: `grep result for usage/token`
  excerpt: |
    _host_token = _SESSION_HOST_CTX.set(session_host)
    _labels_token = bind_labels(labels)
    ...
    -- these ContextVar reset tokens are the ONLY matches for /usage|token/
       in the whole 35.5 KB file; no input_tokens, no turn.completed usage read

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py`
  lines: 10-63
  symbol: `codex models`
  excerpt: |
    class CodexCodeDispatchProfile(BaseModel):
    class CodexCodeReviewProfile(CodexCodeDispatchProfile):
    class CodexAdversarialReviewProfile(CodexCodeDispatchProfile):
    -- no usage/token model

## Notes

- `dispatchers/` holds 13 backends (`claude.py` 64.7 KB, `llm.py` 115.5 KB, `nova.py`,
  `gemini.py`, `google_coding.py`, `mantle.py`, `moonshot.py`, `zai.py`, `grok.py`,
  `google_compat.py`, `_shared.py`, …). Any usage extraction added for codex has twelve
  siblings, so the natural home is `_shared.py`, not `codex.py` alone.
- The codex seat is 60% of all recorded attempts (FC-005), so closing this one gap moves
  usage coverage more than any other single change in the source's plan.
