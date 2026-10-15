# TASK-4316: Golden MCP manifests for the configuration matrix

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4315
**Assigned-to**: unassigned

---

## Context

Spec §3 M5 / §4. Golden manifests (names, canonical schemas, descriptions, mount conditions) for both transports per configuration: minimal local, ledger, decisions, schema present/absent, federated namespaces, bulk on/off, vault configured, remote proxy.

---

## Scope

- Create `tests/knowledge/wiki/test_mcp_manifest_golden.py` comparing framework and SDK manifests against JSON goldens; regenerate only with `--update-golden`.
- Create the golden JSON files under `tests/knowledge/wiki/golden/mcp_manifests/`.
- Capture the baseline from the pre-refactor surface (existing `test_tool_surface_golden.py` names) and assert equality.

**NOT in scope**: Changing any tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py` | CREATE | golden comparison |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/README.md` | CREATE | how goldens are regenerated; one JSON per configuration is written next to it |

Note (amended): the ten generated `golden/mcp_manifests/<config>.json` files (bulk_off, bulk_on, decisions, federated, ledger, minimal_local, remote_proxy, schema_absent, schema_present, vault) are deliverables of this task; kept out of the table so the test selector does not treat them as pytest targets.

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.mcp_server import build_wiki_tools, create_wiki_mcp_server  # existing golden test imports these
from parrot.knowledge.wiki.transport import build_operation_descriptors  # TASK-4314
```

### Existing Signatures to Use
```python
# tests/knowledge/wiki/test_tool_surface_golden.py — LOCAL_NO_LEDGER / LEDGER / BULK name lists (FEAT-569 baseline)
```

### Does NOT Exist
- ~~a `--update-golden` option today (add it to this test module via pytest_addoption in a local fixture — not in conftest.py)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/README.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#build_wiki_tools"
  ]
}
```

---

## Implementation Notes

Do not edit conftest.py (would make this task affect others). Use an env var `UPDATE_GOLDEN=1` instead of a CLI option.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Write the comparison test — *why*: S11.
2. Generate goldens once with UPDATE_GOLDEN=1 on a clean tree — *why*: baseline.
3. Assert both transports match.

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py` (CREATE)
```python
"""Golden MCP manifests per configuration (FEAT-540 M5)."""
import json
import os
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden" / "mcp_manifests"
CONFIGS = ["minimal_local", "ledger", "decisions", "schema_present", "schema_absent", "federated", "bulk_on", "bulk_off", "vault", "remote_proxy"]


@pytest.mark.parametrize("config", CONFIGS)
@pytest.mark.parametrize("transport", ["framework", "sdk"])
def test_manifest_matches_golden(config: str, transport: str, tmp_path) -> None:
    # FILL IN: build the configuration, list tools on the transport, canonicalise [{name, description, schema}] sorted by name
    # FILL IN: if os.environ.get('UPDATE_GOLDEN') == '1': write GOLDEN / f'{config}.json' (framework only); else compare
    ...
```
**Why**: Both transports compare to the same golden.

### `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/README.md` (CREATE)
```markdown
# MCP manifest goldens (FEAT-540)

Regenerate: `UPDATE_GOLDEN=1 pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q` on a clean tree, then review the diff.
```
**Why**: Documents the regeneration contract.

### FILL IN checklist
- [ ] per-configuration builders
- [ ] canonicalisation
- [ ] golden generation + commit of the JSON files

---

## Acceptance Criteria

- [ ] goldens exist for every configuration
- [ ] framework and SDK manifests both equal the goldens
- [ ] names match the FEAT-569 baseline

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4316 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra (attempt d31a3a22), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: test_mcp_manifest_golden.py (21 tests: 10 configurations x framework/sdk transports against one golden each, plus a frozen minimal tool surface) + README with the UPDATE_GOLDEN=1 regeneration recipe + ten generated golden JSONs. The fidelity gate flagged the ten JSONs as undeclared (spec gap: the README itself says one JSON per configuration is written); they were committed and the task note amended. Engine quirk: the merge-tier selector passes every changed file under tests/ (README.md, *.json) to pytest as a target, so the engine run exits 4 "not found"; the real tests were run directly instead: golden + transport selector = 25 passed. No review corrections.

**Deviations from spec**: ten golden JSON files added to the declared scope.
