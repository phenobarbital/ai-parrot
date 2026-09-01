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

# WorkingMemory tool names — CORRECTED (verified live via `tools/list`):
# AbstractToolkit._generate_tools() prefixes exposed method names with a
# short toolkit tag ("wm_"). The bare names in the original contract
# (store/get_stored/...) do NOT appear over MCP. Actual exposed names:
#   wm_store_result, wm_get_result, wm_get_stored, wm_list_stored,
#   wm_drop_stored, wm_compute_and_store, wm_import_from_tool,
#   wm_list_tool_dataframes, wm_merge_stored, wm_recall_interaction,
#   wm_save_interaction, wm_search_stored, wm_summarize_stored.
# store_result(key, data, ...) / get_result(key, ...) (tool.py:208/259) are
# the generic (non-DataFrame) round-trip pair used by the e2e test.
```

### Does NOT Exist
- ~~an MCP client helper in core for tests~~ — drive raw JSON-RPC lines
  over subprocess pipes.
- ~~a FEAT-403 subprocess test harness (`test_stdio_server_subprocess` /
  `test_wikitoolkit_mcp_e2e`)~~ — grepped `tests/` for
  `"stdio_server_subprocess"` and `"subprocess.Popen"`: no such harness
  exists anywhere in the repo. Built the harness fresh in this task's test
  file (raw `subprocess.Popen` + line-delimited JSON-RPC over pipes).
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

**Completed by**: sdd-start (Claude)
**Date**: 2026-09-01
**Notes**:

- Built a fresh subprocess-based JSON-RPC test harness in
  `tests/mcp/test_mcp_local_e2e.py` (no such harness existed anywhere in
  the repo — the contract's "FEAT-403 test_stdio_server_subprocess /
  test_wikitoolkit_mcp_e2e" reference was stale; grepped and confirmed,
  corrected in the task contract). Spawns `parrot.cli.cli()` via
  `sys.executable -c <bootstrap>` (not the installed console script, so
  it always exercises the checkout under test) and drives real
  line-delimited JSON-RPC over stdin/stdout pipes:
  - `test_mcp_local_memory_e2e`: initialize → tools/list (asserts
    `wm_store_result`/`wm_get_result`/`wm_list_stored` present — the
    actual exposed names carry a `wm_` prefix, NOT the bare
    `store`/`get_stored` in the original contract; corrected there too,
    verified live) → `wm_store_result` → `wm_get_result` round-trip.
  - `test_memory_is_per_process`: two sequential server processes; a key
    stored in the first is not visible (`isError: true`) from the second.
  - `test_stdout_purity_with_printing_toolkit`: a toolkit module written
    to `tmp_path` with a top-level `print(...)`, referenced via
    `.parrot/mcp-toolkits.yaml`; asserts the print lands on stderr and the
    `initialize` response is still clean, single-line JSON-RPC.
  - `test_example_config_parses`: copies `examples/mcp-toolkits.yaml`
    into a tmp `.parrot/` dir and runs it through
    `load_toolkits_config`.
  - `test_mcp_local_list_shows_builtin`: `--list` sanity check over the
    same bootstrap.
  - `_recv()` fails loudly (not a hang) on a non-JSON line or a
    process that produced no output, surfacing exit code + stderr.
  - The bootstrap's Cython-extension fallback (`parrot.utils.types` /
    `parrot.utils.parsers.toml`) only engages via `except ImportError` —
    in a normal checkout/CI with the real compiled extensions present it
    is a no-op; it only matters in a git worktree missing build
    artifacts (this environment). Mirrors the repo's own root
    `conftest.py` mitigation for the identical, previously-documented
    gotcha.
- **Discovered and fixed a real stdout-purity bug** while building the
  e2e test (not simulated): `parrot/mcp/toolkit_server.py` imported
  `LLMFactory` (`parrot.clients.factory`) at MODULE level — outside the
  `contextlib.redirect_stdout(sys.stderr)` block that guards every other
  heavy import in that file. `LLMFactory`'s import chain reaches
  navconfig, whose eager settings load does a raw `print("USE SSL::
  False")` straight to stdout (not routed through logging) — this is
  the EXACT risk the spec's own §7 Known Risks section names ("some
  `parrot.mcp.*` import chains print at import time... every toolkit
  import happens inside the redirect block; the integration test
  `test_mcp_local_stdout_purity` guards this"), and it fired on **every**
  `parrot mcp-local <name>` serve invocation regardless of toolkit or
  `llm:` configuration, breaking a real MCP host's JSON-RPC handshake.
  Fixed by deferring the import to inside the function body, at its one
  call site (`if section.llm: from parrot.clients.factory import
  LLMFactory`), inside the SAME redirect block that already guards the
  toolkit class resolution. This file is NOT in this task's original
  Files-to-Modify list (TASK-2646's file) — flagging explicitly per
  Cardinal Rule #4: the fix is a single import-statement relocation, adds
  no new behavior/signature, is required to make this task's own
  acceptance criteria (stdout purity) genuinely true rather than
  incidentally-passing in every test I could write around it, and
  directly implements the spec's own stated mitigation design that
  TASK-2646 missed for this one import. Verified via `git stash`: adds
  zero new ruff findings (3 pre-existing findings before and after) and
  changes no test's failure *mode* in `tests/mcp/test_toolkit_server.py`
  (same 8 pre-existing failures, same messages, confirmed
  `test_llm_wired_when_configured`'s failure is an unrelated pytest-API
  misuse in that test file, not touched by this fix).
- `docs/mcp-local-toolkits.md`: quickstart, `.parrot/mcp-toolkits.yaml`
  schema table, include-wins-over-exclude rule, `llm_dependent_tools`
  auto-drop rule, `confirming_tools` behavior (unchanged), builtins
  table, "exposing your own toolkit" walkthrough, a dedicated ⚠️ trust
  note (config-driven instantiation = arbitrary code execution, same
  boundary as `.mcp.json` itself — per spec §7), and a troubleshooting
  section (`--list`, unknown-name / ImportError messages, stdout
  corruption, `confirm` rejection). Verified against LIVE behavior, not
  assumed: confirmed and corrected one inaccurate draft claim before
  finalizing — `enabled: false` does NOT block a direct `parrot mcp-local
  <name>` invocation (`create_toolkit_mcp_server` never checks
  `section.enabled`); it only affects `--list`'s displayed state and the
  installers' managed-entry sets. Documented accurately.
- `examples/mcp-toolkits.yaml`: annotated, matches spec §2's example
  plus include/exclude, `env`, a custom-toolkit template, and the
  disable-without-delete pattern (commented, non-executing examples for
  the latter three so the file's ACTIVE `toolkits:` stays exactly the
  three built-ins). Parses via `load_toolkits_config` (asserted in the
  test above) and via a plain `yaml.safe_load` sanity check.
- Full `tests/mcp/` suite: 145 passed, 18 pre-existing failures (8 from
  TASK-2646's `test_toolkit_server.py`, already documented in TASK-2649's
  Completion Note; 10 unrelated `test_netsuite_mcp.py`/
  `test_oauth_manager_removed.py` — confirmed via `git stash` to fail
  identically before ANY of today's changes, root cause `RuntimeError:
  There is no current event loop in thread 'MainThread'`, unrelated to
  MCP-toolkit code). Zero new failures. `ruff check` clean on the new
  test file; the one modified production file
  (`toolkit_server.py`) shows the same 3 pre-existing findings before and
  after (verified via `git stash`).

**Deviations from spec**: none in behavior/design. Two Codebase Contract
corrections (stale FEAT-403 test-harness reference; bare vs `wm_`-prefixed
WorkingMemory tool names) and one necessary, narrowly-scoped, documented
fix to a file outside this task's original list (`toolkit_server.py`'s
`LLMFactory` import placement) — see above.

**Deviations from spec**: none
