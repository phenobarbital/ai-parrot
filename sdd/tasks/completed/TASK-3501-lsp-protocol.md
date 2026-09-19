# TASK-3501: Implement bounded LSP framing and a scripted fake server

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3499
**Assigned-to**: unassigned

## Context

Implement M2 of the approved specification: implement bounded lsp framing and a scripted fake server. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Implement async Content-Length framing over byte streams with 8 KiB header and 8 MiB frame caps, strict JSON-RPC validation and request/response/notification discrimination.
- Provide internal reader/writer helpers for session ownership; preserve request IDs and never conflate JSON characters with UTF-8 bytes.
- Create a deterministic subprocess fake server that can initialize, respond, interleave diagnostics/configuration/progress, fragment writes, flood stderr, delay/omit messages and refuse shutdown.
- Test malformed/oversized frames, multiple frames per read, Unicode lengths, premature EOF and cancellation without real Pyright or network access.

**NOT in scope**: Toolkit methods, Pyright configuration, worktree hashing and model calls.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/protocol.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/fake_server.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_protocol.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.mcp.local_server import StdioMCPServer` — verified in `packages/ai-parrot/src/parrot/mcp/local_server.py`; use only where relevant.

### Existing Signatures to Use

- `StdioMCPServer` — `packages/ai-parrot/src/parrot/mcp/local_server.py:36`: existing MCP stdio server uses line-delimited JSON; it is not an LSP Content-Length client.
- `StdioMCPServer.start` — `packages/ai-parrot/src/parrot/mcp/local_server.py:44`: async start(self); stdin currently uses run_in_executor, so cancellation alone may leave executor shutdown waiting.
- `StdioMCPServer.stop` — `packages/ai-parrot/src/parrot/mcp/local_server.py:80`: async stop(self); sets the running flag, without owned toolkit cleanup.

### Dependency-produced contracts

- TASK-3499 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/__init__.py`, `packages/ai-parrot-tools/src/parrot_tools/lsp/models.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

### Does NOT Exist

- The files marked CREATE are new task deliverables; do not assume their modules or exports already exist.
- Files marked MODIFY that are created by a prerequisite must be verified after that prerequisite lands.
- No existing LSP client, persistent diagnostic baseline API or five-arm pilot harness is established by the references above.
- Do not assume generic MCP transport implements LSP framing, or AST line spans provide identifier columns.
- Verify any additional symbol before use; do not invent provider adapters or methods.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/protocol.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/fake_server.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_protocol.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.start",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.stop"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3499 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `Private framing helpers in protocol.py, consumed by PyrightSession; no public agent-facing API.`
- `fake_server.py is a test process fixture with explicit argv-selected scenarios and deterministic transcripts.`

1. Implement independent bounded read/write helpers and protocol error mapping using models from the dependency.
2. Build the fake child fixture using the same byte-level protocol contract but independent expected frames in tests.
3. Test fragmentation and interleaving through actual subprocess pipes, including invalid headers and early EOF.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Implement async Content-Length framing over byte streams with 8 KiB header and 8 MiB frame caps, strict JSON-RPC validation and request/response/notification discrimination.
- [ ] Provide internal reader/writer helpers for session ownership; preserve request IDs and never conflate JSON characters with UTF-8 bytes.
- [ ] Create a deterministic subprocess fake server that can initialize, respond, interleave diagnostics/configuration/progress, fragment writes, flood stderr, delay/omit messages and refuse shutdown.
- [ ] Test malformed/oversized frames, multiple frames per read, Unicode lengths, premature EOF and cancellation without real Pyright or network access.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_protocol.py -q`

## Test Specification

- `test_framing_and_interleaving`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_unicode_content_length_counts_bytes`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_oversized_and_malformed_frames`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_fake_child_fault_scenarios`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Implemented async Content-Length LSP framing in `protocol.py`: `read_message`/`write_message` with an 8 KiB
header cap and 8 MiB frame cap (checked before the body is read, so an oversized declared length never forces
an unbounded read), strict JSON-RPC 2.0 validation, and request/response/notification discrimination via a
frozen `ParsedMessage` dataclass. Content-Length is always computed/consumed from the UTF-8-encoded body bytes,
never the decoded string length. `LSPFailure("protocol_error", ...)` covers malformed/oversized frames and
invalid JSON-RPC shapes; `LSPFailure("server_crashed", ...)` covers premature EOF. Added `build_request`/
`build_notification`/`build_response` helpers preserving request-id type exactly. All symbols are module-public
but intentionally unexported from `parrot_tools/lsp/__init__.py` — no public agent-facing API, consumed by
`PyrightSession` (session.py, TASK-3502, not touched here). `fake_server.py` is a standalone scripted subprocess
fixture with its OWN independent, synchronous Content-Length reader/writer (deliberately not importing
`protocol.py`, so protocol.py's framing is verified against an independent implementation); scenarios:
happy_path, fragmented_writes, flood_stderr, delay_response, omit_response, refuse_shutdown, early_eof,
malformed_header, oversized_header.

Validation: `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest
packages/ai-parrot-tools/tests/lsp/test_protocol.py -q` → 30 passed, no warnings (pyproject's
`filterwarnings = ["error", ...]` passed cleanly — no leaked subprocess/ResourceWarning). `black -l 120` and
`ruff check` clean on all three files.

Post-merge regression (`select_tests --tier merge`): 98 passed (`dev_loop/sdd_coder` + `packages/ai-parrot/tests/mcp`),
78 passed/1 deselected (`packages/ai-parrot-tools/tests/lsp` + `tool_optimizations/integration`), 15 passed
(`tests/mcp/test_toolkit_server.py`).

Coder-feedback patterns checked: hasattr-duck-typing — not applicable (message discrimination uses explicit
dict-key presence checks, ordered specific-before-generic, with the fallthrough raising rather than
mis-classifying). unisolated-real-home-in-tests — not applicable (no test touches `$HOME`/`PARROT_HOME`/XDG;
only I/O is spawning the repo-relative `fake_server.py` fixture as a subprocess).
unscoped-removal-reuses-full-uninstall-helper — not applicable (all functions are new).

Scope note: `protocol.py` implements only the framing/discrimination layer as scoped — no request-id-to-future
routing, timeouts, method-not-found responses, `applyEdit` rejection, or session/process lifecycle; those
remain TASK-3502 (session.py)'s responsibility. `fake_server.py` already answers `workspace/configuration` and
emits `publishDiagnostics`/`$/progress` in anticipation of TASK-3502/3503 reusing this fixture — today's
`test_protocol.py` only exercises it through raw framing, not session/toolkit semantics.

No code review deferred findings for this delivery. No correction feedback filed (no confirmed defect found).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a (not reported by native
Agent dispatch) · Tokens: 173754 (subagent_tokens, per completion notification).
