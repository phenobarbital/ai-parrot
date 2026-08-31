# TASK-2650: End-to-end integration tests, docs, and example config

**Feature**: FEAT-485 — Expose Toolkits as Local MCP
**Spec**: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2644, TASK-2645, TASK-2646, TASK-2647, TASK-2648, TASK-2649
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 + §4 Integration Tests. Closes the feature: prove the
whole path works over real stdio JSON-RPC with a real toolkit
(WorkingMemory — no heavy deps), document the config format and exposure
guide, and ship an example config.

---

## Scope

- CREATE integration tests:
  - `test_mcp_local_memory_e2e`: spawn `parrot mcp-local memory` as a
    subprocess (cwd = tmp project root); send JSON-RPC lines on stdin:
    `initialize`, `tools/list` (assert WorkingMemory tools like `store`,
    `get_stored`, `list_stored` present), `tools/call` on `store` then
    `get_stored`; assert every stdout line parses as JSON-RPC (stdout
    purity) and responses match ids.
  - `test_mcp_local_stdout_purity`: a stub toolkit whose module prints at
    import time → the print lands on stderr, never stdout.
- CREATE `docs/mcp-local-toolkits.md`: config reference
  (`.parrot/mcp-toolkits.yaml` schema, include-wins rule, `llm:` wiring,
  builtins table, env passthrough), "expose your toolkit to Claude
  Code/Codex" guide, troubleshooting (`--list`, ImportError messages), and
  the trust note (config-driven instantiation executes code named by
  config — same trust boundary as `.mcp.json` itself).
- CREATE `examples/mcp-toolkits.yaml`: annotated example matching spec §2.
- Verify the full acceptance-criteria list in spec §5 and check off what
  this task proves.

**NOT in scope**: enabling the entries in THIS repo's `.mcp.json` (user
decision post-merge); new runner features.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/mcp/test_mcp_local_e2e.py` | CREATE | subprocess JSON-RPC tests |
| `docs/mcp-local-toolkits.md` | CREATE | config reference + guide |
| `examples/mcp-toolkits.yaml` | CREATE | annotated example config |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Test-side only: stdlib subprocess/json. The server side under test:
from parrot.mcp.toolkit_server import create_toolkit_mcp_server  # TASK-2646
# CLI invocation: `parrot mcp-local memory` (console script parrot =
# parrot.cli:cli — packages/ai-parrot/pyproject.toml:163)
```

### Existing Signatures to Use
```python
# JSON-RPC dialect handled by the server —
# packages/ai-parrot/src/parrot/mcp/local_server.py:84-120 (_handle_request):
#   methods: "initialize", "tools/list", "tools/call",
#            "notifications/initialized" (notification — NO response)
#   response: {"jsonrpc": "2.0", "id": <id>, "result": ...} or
#             {"jsonrpc": "2.0", "id": <id>, "error": {"code": -32603, ...}}
#   transport: ONE JSON object per line on stdin/stdout (line 53-66)

# WorkingMemory tool names (parrot/tools/working_memory/tool.py):
#   store(194), get_stored(248), list_stored(362), drop_stored(242), ...

# Reference e2e pattern: FEAT-403's integration test
#   test_stdio_server_subprocess / test_wikitoolkit_mcp_e2e — grep
#   tests/ for "stdio_server_subprocess" and mirror the harness if present.
```

### Does NOT Exist
- ~~an MCP client helper in core for tests~~ — drive raw JSON-RPC lines
  over subprocess pipes (or reuse the FEAT-403 test harness if found).
- ~~`docs/mcp-local-toolkits.md`~~, ~~`examples/mcp-toolkits.yaml`~~ —
  created here.
- ~~WorkingMemory persistence across processes~~ — asserting the OPPOSITE
  is part of the e2e test (two consecutive processes share nothing).

---

## Implementation Notes

### Key Constraints
- Subprocess tests must set a generous-but-bounded timeout and kill the
  child on teardown (no orphaned servers in CI).
- Run the subprocess with the venv's `parrot` binary
  (`sys.executable`-relative or shutil.which within the venv).
- Docs follow the existing docs/ style; the trust note is REQUIRED (spec
  §7 Known Risks).
- The e2e test doubles as the spec §5 verification for: bare-install
  serving, stdout purity, per-process ephemerality.

---

## Acceptance Criteria

- [ ] `test_mcp_local_memory_e2e` passes: initialize → tools/list →
      store → get_stored round-trip over real subprocess stdio
- [ ] Every stdout line the server emits parses as JSON-RPC
- [ ] Two consecutive server processes share no memory state
- [ ] Import-time prints from a stub toolkit land on stderr only
- [ ] `docs/mcp-local-toolkits.md` covers schema, include-wins, llm wiring,
      builtins, troubleshooting, trust note
- [ ] `examples/mcp-toolkits.yaml` parses via `load_toolkits_config`
- [ ] Full suite green: `pytest tests/mcp/ -v`; ruff clean

---

## Test Specification

```python
# tests/mcp/test_mcp_local_e2e.py
import json, subprocess

def _rpc(proc, payload): ...  # write line, read matching-id response line

def test_mcp_local_memory_e2e(tmp_path): ...
def test_memory_is_per_process(tmp_path): ...
def test_stdout_purity_with_printing_toolkit(tmp_path): ...
def test_example_config_parses():
    from parrot.mcp.toolkit_config import load_toolkits_config
    ...
```

---

## Agent Instructions

1. **Read the spec** — §5 Acceptance Criteria is the checklist this task closes
2. **Check dependencies** — TASK-2644…2649 all in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/expose-toolkits-as-local-mcp.json` → `"in-progress"`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index** → `"done"`, **fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
