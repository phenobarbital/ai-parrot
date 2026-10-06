# TASK-4112: Docs — python transformers in the linked-surfaces wire doc and the QuerySource toolkit doc

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4108, TASK-4109, TASK-4111
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 / AC12. Document the final behavior once the endpoint (TASK-4108), the toolkit gate (TASK-4109) and the
renderer lane (TASK-4111) have landed, so the doc describes what shipped — not the plan.

---

## Scope

- `docs/outputs/a2ui-linked-surfaces.md`:
  - §2 wire table: `transform` row mentions the third member (`python`).
  - §3 fetch path: add the `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data` route, params-only body,
    response shape, error codes (404 unavailable, 403 guard/PBAC, 422 transform-stage codes).
  - §5: rename heading to "Transforms — DSL v1, `transform.ref` and `transform.python`"; add a subsection: registered
    name (G1), `input_alias` default `"source"`, `output` selection rule, terminal rule, post-transform 5000-row cap,
    persisted-only dynamic fetch ("saved data" otherwise), operator note: the serving process must have imported the
    transformer module (`load_transformer_module`) or requests 422 `transformer_not_registered`.
  - §6 trust model: identity rule (owner/scope → caller pctx; share-token-only → owner pctx).
- `docs/tools/querysource-toolkit.md`: one paragraph on declaring `transform.python` in `qs_build_linked_surface` /
  dashboard sources and the build-time gate.
- A doc-assertion test (pattern: `test_docs_linked_dashboard.py`).

**NOT in scope**: code changes; docstrings (done in TASK-4109).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/a2ui-linked-surfaces.md` | MODIFY | §2/§3/§5/§6 updates |
| `docs/tools/querysource-toolkit.md` | MODIFY | `transform.python` paragraph |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_docs_python_transforms.py` | CREATE | doc assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path   # stdlib; pattern from packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py:3
```

### Existing Signatures to Use
```text
docs/outputs/a2ui-linked-surfaces.md headings: ## 2 (line 13), ## 3. Fetch path and errors (90), ### Per-source refresh (120),
  ## 5. Transforms — DSL v1 and `transform.ref` (145), ## 6. Trust model (153), ## 7. Share-token viewers (159)
docs/tools/querysource-toolkit.md — exists (asserted by test_docs_linked_dashboard.py)
packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py — ROOT = Path(__file__).resolve().parents[4]
  (for packages/ai-parrot/tests/outputs/a2ui/linked/<file>.py the repo root is parents[6])
```

### Does NOT Exist
- ~~a separate python-transformers doc page~~ — extend the existing wire doc; do not create a new page.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/outputs/a2ui-linked-surfaces.md", "action": "MODIFY"},
    {"path": "docs/tools/querysource-toolkit.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_docs_python_transforms.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Re-read the merged code of TASK-4105/4107/4108/4111 for the exact route, codes and statuses — *why*: the doc must match what shipped.
2. Edit the wire doc sections in place — *why*: AC12; keep existing text intact except the §5 heading.
3. Add the toolkit paragraph.
4. Write the doc test; run the Validation Commands (the existing FEAT-610 doc test must still pass — it asserts the old routes remain).

### `docs/outputs/a2ui-linked-surfaces.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '## 5. Transforms — DSL v1 and `transform.ref`' docs/outputs/a2ui-linked-surfaces.md) -->
<!-- REPLACE the §5 heading (line 145) with: -->
## 5. Transforms — DSL v1, `transform.ref` and `transform.python`

<!-- AFTER the existing §5 body, add: -->
### `transform.python` — server-side registered transformers (FEAT-636)
<!-- FILL IN: the bullets listed in Scope (§5 bullet group) — bounded by: describe only shipped behavior; quote the
     three codes verbatim (transformer_not_registered, transform_failed, transform_invalid_output → 422) -->

<!-- FILL IN: §3 route + body + response + codes; §2 transform row; §6 identity rule — per Scope -->
```

### `docs/tools/querysource-toolkit.md` (MODIFY)
```markdown
<!-- FILL IN: one paragraph (≤ 8 lines) near the existing qs_build_linked_dashboard section: the `python` member shape,
     terminal rule, build-time gate raising InvalidConditionsError -->
```

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_docs_python_transforms.py` (CREATE)
```python
"""FEAT-636 AC12 — docs describe server-side python transformers for linked surfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]


def test_wire_doc_describes_python_transforms() -> None:
    wire = (ROOT / "docs/outputs/a2ui-linked-surfaces.md").read_text()
    for needle in (
        "transform.python",
        "/api/v1/ui/surfaces/{surface_id}/sources/{key}/data",
        "transformer_not_registered",
        "transform_failed",
        "transform_invalid_output",
        "input_alias",
        "terminal",
        "saved data",
    ):
        assert needle in wire, needle


def test_toolkit_doc_mentions_python_member() -> None:
    toolkit = (ROOT / "docs/tools/querysource-toolkit.md").read_text()
    assert "transform.python" in toolkit or '"python"' in toolkit
```

### FILL IN checklist
- [ ] wire doc §2/§3/§5/§6 edits
- [ ] toolkit doc paragraph

---

## Acceptance Criteria

- [ ] AC12 (spec): wire doc + toolkit doc document the member, endpoint, codes, identity rule and persisted-only dynamic fetch.
- [ ] Existing doc test (`test_docs_linked_dashboard.py`) still passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_docs_python_transforms.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`).
2. Confirm TASK-4108, TASK-4109 and TASK-4111 are `done` in the per-spec index.
3. Follow the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4112 linked-a2ui-recipes-transforms verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
