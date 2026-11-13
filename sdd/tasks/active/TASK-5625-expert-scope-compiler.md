# TASK-5625: Scope loader, compile_scope and bundled scopes

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5624
**Assigned-to**: unassigned

---

## Context

Spec §2.3 / Module 5, AC8–AC9. `compile_scope` is pure: ScopeGrid → `FlowDefinition` with `expert_stage` nodes, `pipeline` expanded into a chain with gate edges, mob followed by its synthesis.

---

## Scope

- Create `experts/grid/loader.py` (`load_scopes(agents_dir, *, bundled_dir=BUNDLED_SCOPES_DIR)`; workspace shadows bundled by scope name) and `experts/grid/compiler.py` (`compile_scope(grid, *, registry)`).
- Validate: experts exist (registry), capability fits (a stage with a gate's `pre_review` expert needs `review`), gate kinds registered, no cycles.
- Add bundled scopes `security-patch.yaml` (intake: cve-analyst subagent → gate approval → plan: cve-remediation subagent) and `sdd-review.yaml` (match tags [security], mob of cve-analyst — spec §8 Q2 default) under `parrot/experts/bundled/scopes/`.
- Add `"parrot.experts.bundled"` package-data glob `scopes/*.yaml` in packages/ai-parrot/pyproject.toml.
- Golden-file test.

**NOT in scope**: Running flows (TASK-5627).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/grid/loader.py` | CREATE | loader |
| `packages/ai-parrot/src/parrot/experts/grid/compiler.py` | CREATE | compiler |
| `packages/ai-parrot/src/parrot/experts/bundled/scopes/security-patch.yaml` | CREATE | bundled scope |
| `packages/ai-parrot/src/parrot/experts/bundled/scopes/sdd-review.yaml` | CREATE | bundled scope |
| `packages/ai-parrot/pyproject.toml` | MODIFY | package-data |
| `packages/ai-parrot/tests/experts/test_scope_compiler.py` | CREATE | golden tests |
| `packages/ai-parrot/tests/experts/fixtures/security_patch_flow.json` | CREATE | golden FlowDefinition |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.experts.grid.models import ScopeGrid, ExpertStageConfig, ScopeGridError, ScopeGridErrorCode  # TASK-5620
from parrot.experts.loader import BUNDLED_EXPERTS_DIR  # verified: loader.py:18
from parrot.bots.flows.core.gates.kinds import is_registered  # TASK-5612
import parrot.experts.stages  # noqa: F401 — registers expert_stage (TASK-5624)
```

### Existing Signatures to Use
```python
class NodeDefinition(BaseModel)  # bots/flows/flow/definition.py:~155 — id, type: str, label, agent_ref, instruction, max_retries, config: Dict[str, Any], pre_actions, post_actions, metadata, position
class EdgeDefinition  # definition.py:~246 — read it for predicate/gate-edge fields
# pyproject.toml:1052 "parrot.experts.bundled" = ["*/expert.yaml", "*/persona.md", "*/identity/*.md", "*/knowledge/*.md", "*/rules/*.md", "*/adr/*.md"]
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~A `gate` node type~~ — none exists; express gates as the stage node's own `gate` config + an edge predicate on gate approval (read EdgeDefinition first) — FILL IN.
- `scopes/` is NOT a bundle dir: make sure `discover_expert_bundles` ignores it (read loader.py) — add a test.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/grid/loader.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/grid/compiler.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/bundled/scopes/security-patch.yaml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/bundled/scopes/sdd-review.yaml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_scope_compiler.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/experts/fixtures/security_patch_flow.json",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Read definition.py NodeDefinition/EdgeDefinition and loader.py discovery.
2. Write loader/compiler/scopes.
3. Golden test + error tests + loader-ignores-scopes test.

### Blocks

```python
# packages/ai-parrot/src/parrot/experts/grid/compiler.py  (CREATE)
"""Scope grid → FlowDefinition (FEAT-890 M5). Pure: no I/O, no LLM."""
from __future__ import annotations
from parrot.experts.grid.models import ScopeGrid, ScopeGridError, ScopeGridErrorCode

def compile_scope(grid: ScopeGrid, *, registry: "ExpertRegistry") -> "FlowDefinition":
    """Raise ScopeGridError(UNKNOWN_EXPERT|CAPABILITY_MISMATCH|UNKNOWN_GATE_KIND|CYCLE)."""
    # FILL IN
```
```toml
# packages/ai-parrot/pyproject.toml (MODIFY) — anchor `"parrot.experts.bundled" = [` (verified: pyproject.toml:1052; occurrences: 1)
# FILL IN: append "scopes/*.yaml" to that list
```
**Why**: editing pyproject makes this task exclusive (parallel: false).

### FILL IN checklist
- [ ] edge/gate encoding
- [ ] registry existence check API
- [ ] golden fixture

---

## Acceptance Criteria

- [ ] AC8.
- [ ] Bundled scopes load; `test_bundled_wheel.py` still passes.

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_scope_compiler.py -q`
- `pytest packages/ai-parrot/tests/experts/test_bundled_wheel.py -q`
- `pytest packages/ai-parrot/tests/experts/test_loader_view.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5625 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
