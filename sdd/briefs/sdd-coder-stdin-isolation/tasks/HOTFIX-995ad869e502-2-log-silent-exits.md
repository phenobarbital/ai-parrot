# HOTFIX-995ad869e502-2: Make the stdio server's two silent exits observable

**Feature**: BRIEF-995ad869e502 — MCP-served subprocesses must not inherit the JSON-RPC stdin socket
**Spec**: `sdd/briefs/sdd-coder-stdin-isolation.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`issue:995ad869e502` took four occurrences and a full forensic pass to diagnose
because the server leaves no trace when it goes: the serve loop breaks on stdin
EOF and returns, and the SIGTERM handler calls `os._exit(0)` — neither says
anything. From the host's side both look identical to a crash, which is why OOM,
segfault and a native rebuild all had to be ruled out one by one before the real
path was found.

Per the brief's decision 2, the loop must still exit on a genuine EOF (refusing
would orphan the server when the host is really gone). What changes is only that
each exit announces which path it took.

This task is independent of HOTFIX-995ad869e502-1 and shares no file with it.

---

## Scope

- Log one line when the serve loop ends because stdin reached EOF, naming the
  path and how many request handlers are still in flight.
- Log one line in the SIGTERM handler immediately before `os._exit(0)`.
- Make both lines distinguishable from each other and from the existing
  `"Stdio MCP server stopped"` line, so a host log can tell "the host closed our
  stdin" apart from "we were signalled".
- Cover both with tests.

**NOT in scope**: any change to *when* the server exits (no EOF grace period, no
in-flight guard, no retry) — see the brief's decision 2; the subprocess `stdin`
kwargs (HOTFIX-995ad869e502-1); the duplicate `StdioMCPServer` in
`packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py`
(`issue:7a366d6004de`); the logging configuration in `_configure_stderr_logging`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/local_server.py` | MODIFY | Log before the stdin-EOF `break` |
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | MODIFY | Log before `os._exit(0)` |
| `packages/ai-parrot/tests/mcp/test_local_server.py` | MODIFY | Assert the EOF line |
| `packages/ai-parrot/tests/mcp/test_local_server_concurrency.py` | MODIFY | Assert the in-flight count in the EOF line |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED in this worktree (base `origin/dev`, HEAD `8e7d19e57`) with
> `test -e <path> && sed -n '<line>p' <path>`.

### Verified Imports

```python
# Both modules already have everything needed — no new import.
# local_server.py already binds `self.logger` (configured at lines 50-51).
# local_cli.py already has `logger = logging.getLogger(__name__)` and `os`.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer:
    self._inflight: set["asyncio.Task[None]"]      # line 67
    drain_timeout_s                                # see line 60 comment
    async def start(self):                         # line 70
        # line 87 (verbatim): line = await loop.run_in_executor(None, sys.stdin.readline)
        # line 88 (verbatim): if not line:
        # line 89 (verbatim): break
        # line 110 (verbatim): self.logger.info("Stdio MCP server stopped")
    async def _drain(self) -> None:                # line 174
        # counts pending with: {t for t in self._inflight if not t.done()}   # line 176

_INFLIGHT_DRAIN_SECONDS = 5.0                      # line 33

# packages/ai-parrot/src/parrot/mcp/local_cli.py
async def _serve_with_shutdown(server: "StdioMCPServer") -> None:   # line 32
    async def _on_sigterm() -> None:               # line 70
        # line 78 (verbatim): logger.exception("Error while shutting down mcp-local on SIGTERM")
        # line 79 (verbatim): finally:
        # line 80 (verbatim): os._exit(0)
```

### Does NOT Exist

- ~~`StdioMCPServer.inflight_count`~~ / ~~`.pending_requests`~~ — count it from
  `self._inflight` the way `_drain` does (line 176).
- ~~a structured-event emitter on this server~~ — it logs through `self.logger`
  only; do not add telemetry here.
- ~~`print(...)`~~ — forbidden by `.claude/rules/codebase-conventions.md`, and
  stdout is the JSON-RPC channel.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/local_server.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/local_cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_local_server.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_local_server_concurrency.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.start",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer._drain"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `self.logger` on this server writes to **stderr** (`local_server.py:50-51`,
  `propagate = False`); stdout is the JSON-RPC channel and must stay untouched.
- The EOF line must be emitted *before* `_drain()` runs, so it reports the
  in-flight count at the moment the channel closed rather than after draining.
- The SIGTERM line must be emitted before `os._exit(0)` and must survive the
  `except Exception` above it — put it in the `finally`, immediately before the
  exit, so it is written whether or not `server.stop()` raised.
- `os._exit()` skips logging handler flush; use `logging.shutdown()` or an
  explicit `handler.flush()` if the test shows the line can be lost.

---

## Implementation Blueprint

### Steps (in order)

1. Add the EOF log line in `start()` — *why*: names the one path that produced
   four undiagnosable disconnects.
2. Add the SIGTERM log line in `_on_sigterm` — *why*: distinguishes "we were
   signalled" from "our stdin closed", which the host log cannot tell apart.
3. Assert both in tests, including the in-flight count.

### `packages/ai-parrot/src/parrot/mcp/local_server.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'if not line:' packages/ai-parrot/src/parrot/mcp/local_server.py)
# AFTER — replace the bare `break` at line 89 (verified: local_server.py:88-89)
                    if not line:
                        self.logger.info(
                            "stdin reached EOF (host closed the JSON-RPC channel); "
                            "stopping with %s request handler(s) in flight",
                            len([t for t in self._inflight if not t.done()]),
                        )
                        break
```

**Why this shape**: this is the exact line that ended four runs without a word.
Reporting the in-flight count distinguishes an orderly host shutdown (0 in
flight) from a channel that died under a running tool call, which is the
`issue:995ad869e502` signature. The existing
`self.logger.info("Stdio MCP server stopped")` at line 110 stays — it marks the
end of `_drain`, not the reason.

### `packages/ai-parrot/src/parrot/mcp/local_cli.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'os._exit(0)' packages/ai-parrot/src/parrot/mcp/local_cli.py)
# AFTER — insert above `os._exit(0)` inside the existing `finally:` (verified: local_cli.py:79-80)
        finally:
            logger.info("mcp-local received SIGTERM; exiting immediately")
            os._exit(0)
```

**Why**: `os._exit(0)` is indistinguishable from a crash in the host's log. One
line turns it into a fact.

### FILL IN checklist

- [ ] `test_local_server.py`: drive `start()` with a stdin stub that returns
      `""`, capture logs with `caplog`, assert the EOF line and that the server
      still exits.
- [ ] `test_local_server_concurrency.py`: EOF while one handler is in flight,
      assert the line reports a non-zero in-flight count.
- [ ] SIGTERM line: assert it is reached; `os._exit` must be patched so the test
      process survives.

---

## Acceptance Criteria

- [ ] Reaching stdin EOF logs exactly one line naming the EOF path and the
      in-flight handler count.
- [ ] The SIGTERM handler logs exactly one line before `os._exit(0)`, even when
      `server.stop()` raised.
- [ ] The two lines, and the existing `"Stdio MCP server stopped"`, are mutually
      distinguishable in a host log.
- [ ] Exit *timing* and *conditions* are unchanged: the loop still breaks on EOF
      and the handler still exits immediately (no grace period, no guard).
- [ ] Nothing is written to stdout.
- [ ] No linting errors: `ruff check` on both modified source files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/mcp/test_local_server.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_local_server_concurrency.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/mcp/test_local_server.py (additions)
import logging

import pytest


class TestSilentExitObservability:
    @pytest.mark.asyncio
    async def test_stdin_eof_is_logged_with_inflight_count(self, monkeypatch, caplog):
        """issue:995ad869e502: the EOF exit must not be silent."""
        # FILL IN: build the server the way this module's other tests do, stub
        # sys.stdin.readline to return "", run start() to completion
        with caplog.at_level(logging.INFO):
            ...
        assert any("stdin reached EOF" in r.message for r in caplog.records)
        assert any("in flight" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_sigterm_path_is_logged_before_exit(self, monkeypatch, caplog):
        """The SIGTERM exit must announce itself before os._exit(0)."""
        exited: list[int] = []
        monkeypatch.setattr("os._exit", exited.append)
        # FILL IN: drive parrot.mcp.local_cli._serve_with_shutdown and deliver SIGTERM
        assert exited == [0]
        assert any("received SIGTERM" in r.message for r in caplog.records)
```
