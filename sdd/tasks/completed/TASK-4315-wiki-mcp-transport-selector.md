# TASK-4315: Wiki MCP server: transport=auto|framework|sdk over the descriptors

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4314, TASK-4309, TASK-4310
**Assigned-to**: unassigned

---

## Context

Spec §3 M5. `create_wiki_mcp_server(root)` (mcp_server.py:373) always builds a `parrot.mcp` `StdioMCPServer`; `mcp_server.py:29` imports `create_wiki_tools` from the (now shimmed) wiki.tools.

---

## Scope

- Add keyword-only `transport` to `create_wiki_mcp_server` and `create_proxy_mcp_server`; `auto` prefers framework, falls back only on transport ImportError.
- Add `to_framework_tools(descriptors)` (lazy `parrot_tools.wiki`) and `to_sdk_server(descriptors, *, name)` (lazy `mcp` SDK) in `mcp_server.py` — `transport.py` stays free of both.
- `abuild_wiki_tools` keeps returning `WikiToolBundle` for `serve.py`; it now assembles via descriptors (plain assembly separated from wrapper construction).
- Proxy: SDK path forwards tools/list and tools/call to the remote.
- Tests: SDK local + proxy with `parrot.mcp`, `parrot.tools`, `parrot_tools` blocked via sys.meta_path; framework path unchanged; owned stores closed on shutdown/error/cancel; clean stdout.

**NOT in scope**: Golden manifest files (TASK-4316); HTTP serve.py changes (must keep working unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | transport selector + SDK server |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport_selector.py` | CREATE | selector tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.transport import OperationDescriptor, build_operation_descriptors  # TASK-4314
from parrot.mcp.local_server import StdioMCPServer  # local_server.py:54 (lazy)
from parrot.mcp.server_base import LocalServerConfig  # mcp_server.py:390 (lazy)
```

### Existing Signatures to Use
```python
# mcp_server.py: import create_wiki_tools :29; StdioMCPServer TYPE_CHECKING :34; WikiToolBundle :93; abuild_wiki_tools :105; ObsidianToolkit lazy :303
#   build_wiki_tools :321; close_bundle :352; create_wiki_mcp_server(root) :373; create_proxy_mcp_server(remote) :408; main :465
# serve.py:156 abuild_wiki_tools; :196 close_bundle — must keep working
# pyproject.toml:436 "mcp>=1.28.1,<2" (core extra)
```

### Does NOT Exist
- ~~a `transport=` parameter today~~
- ~~a fixed tool count~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport_selector.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#create_wiki_mcp_server",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#create_proxy_mcp_server",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#close_bundle"
  ]
}
```

---

## Implementation Notes

Check the installed `mcp` SDK low-level server API before writing `to_sdk_server` (stdio_server + Server.list_tools/call_tool). Map OperationResult → TextContent; is_error → isError. Never print to stdout.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Repoint import :29 to descriptors — *why*: no AbstractTool for plain assembly.
2. SDK adapter — *why*: G5.
3. Selector — *why*: deterministic, testable.
4. Lifecycle + tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.tools import create_wiki_tools' parrot/knowledge/wiki/mcp_server.py)
# AFTER/AT — anchor `from parrot.knowledge.wiki.tools import create_wiki_tools` (verified: mcp_server.py:29)
# REPLACE with:
from parrot.knowledge.wiki.transport import OperationDescriptor, build_operation_descriptors

def create_wiki_mcp_server(root: Path, *, transport: Literal["auto", "framework", "sdk"] = "auto") -> Any:
    """Build the wiki stdio MCP server on the selected transport."""
    # FILL IN: auto -> try framework (ImportError only) else sdk


def to_framework_tools(descriptors: list[OperationDescriptor]) -> list[Any]:
    """Wrap descriptors as parrot_tools.wiki AbstractTools (lazy import)."""
    # FILL IN


def to_sdk_server(descriptors: list[OperationDescriptor], *, name: str) -> Any:
    """mcp SDK low-level stdio server exposing the descriptors (lazy import)."""
    # FILL IN
# FILL IN: same transport parameter on create_proxy_mcp_server; main() gains --transport (default auto)
```
**Why**: Existing signatures stay callable positionally; the selector is additive.

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport_selector.py` (CREATE)
```python
"""MCP transport selection (FEAT-540 M5)."""
import pytest

# FILL IN: meta_path blocker fixture for parrot.mcp / parrot.tools / parrot_tools; sdk local list/call round-trip;
# framework path returns StdioMCPServer; transport='framework' with blocker -> clear ImportError; auto falls back only on ImportError;
# close_bundle closes owned stores on error/cancel; stdout carries only JSON-RPC
```
**Why**: Behavioural matrix from spec §4.

### FILL IN checklist
- [ ] selector logic
- [ ] SDK adapter + proxy forwarding
- [ ] framework adapter
- [ ] lifecycle + tests

---

## Acceptance Criteria

- [ ] SDK local/proxy work with framework modules blocked
- [ ] framework stdio + HTTP serve lifecycle tests pass
- [ ] existing `test_mcp_server*.py`, `test_proxy_stdio.py`, `test_serve_app.py` pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport_selector.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_proxy_stdio.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_serve_app.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tool_bundle.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4315 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra (attempt e7c4979d), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: transport=auto|framework|sdk added to create_wiki_mcp_server/create_proxy_mcp_server; to_framework_tools and to_sdk_server added (lazy imports); WikiToolBundle gained descriptors. Review fix 8742a6e1e: the delivered framework path registered DescriptorTool adapters instead of bundle.tools/vault_tools, breaking test_env_call_sites::test_mcp_server_uses_effective_config and test_namespaces_e2e (no `_store`; vault_ingest filtered) — restored the original registration ("framework path unchanged"). feedback_id coder-feedback:7b206cc895d325e886640107; review coder-review:ee86f27d8d41f5ebe70701cc. Selector tests need PYTHONPATH to include packages/ai-parrot-tools/src. Verification `partial`: merge-tier run = 589 passed / 7 skipped in the wiki set; the engine reported `failed` only because of pre-existing failures (Postgres/Redis unreachable, dev_loop, edge-kind enum tests, bookstore, test_mcp_server*), verified identical on a clean checkout of c57431a06 for the wiki/graphindex/bookstore/subagent-parity samples.

**Deviations from spec**: none.
