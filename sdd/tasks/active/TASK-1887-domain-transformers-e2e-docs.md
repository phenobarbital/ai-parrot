# TASK-1887: Domain transformers, budget_variance e2e fixture, docs

**Feature**: FEAT-326 — DataAgent Infographic — Infographic Authoring for Data Agents
**Spec**: `sdd/specs/dataagent-infographic.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1882, TASK-1883, TASK-1884, TASK-1885, TASK-1886
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-326 — the proof that the whole feature works end to end on the real use case:
the budget variance daily report. Ports the two analysis functions from
`sdd/artifacts/executive_summary.py` into **registered transformers** (making tier-2
publication of this report possible), builds the e2e fixtures, and writes the docs.

---

## Scope

- Port `day_totals(rows)` (`executive_summary.py:40-51`) and `division_breakdown(rows)`
  (`executive_summary.py:54-71`) into `@infographic_transformer`-registered pure functions
  (transformer signature: `(inputs: dict, params: dict) -> dict` — see
  `transformers.py:57`). Payload row format: `[division, project, revActual, revBudget,
  ebitdaActual, ebitdaBudget]`.
- Register them where existing transformers live (check
  `parrot/outputs/a2ui/recipes/library.py` and any existing `@infographic_transformer` call
  sites for placement convention).
- Fixtures (spec §4): `budget_variance_template_dir` (copies
  `sdd/artifacts/budget_variance_dashboard_Template.html` into a tmp `template_dirs` root —
  the deployed dir is gitignored; `sdd/artifacts/` IS versioned), `sample_snapshot_csvs`
  (3 files `financial_projection_extract_YYYYMMDD.csv`, column layout of
  `daily_report.py:64-73`), `local_artifact_store`
  (`ConversationSQLiteBackend` + `OverflowStore` over the local file manager).
- Integration tests (spec §4): `test_e2e_budget_variance_one_shot` (CSV → DatasetManager →
  tier-1 → HTML on disk with spliced `{"days": {...}}`), `test_e2e_publish_and_replay`
  (tier-2 publish → `RecipeRunner.run(name, pctx=system_account_ctx)` reproduces with fresh
  data), `test_e2e_delivery_config` (`RenderSpec.delivery` carried; replay reaches the
  `deliver_artifact` path — mock delivery provider).
- Docs in `docs/`: mixin usage, descriptor contract, data-splice mode, publish/gap-report
  flow, system-account provisioning pointer.

**NOT in scope**: changes to any module implemented by TASK-1882..1886 beyond bug-fix-level
adjustments discovered by the e2e tests (note them in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py` (or the verified convention site) | MODIFY | Register `day_totals`, `division_breakdown` |
| `packages/ai-parrot/tests/fixtures/` (per existing conventions) | CREATE | CSVs + template fixture helpers |
| `packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py` | CREATE | The 3 e2e tests |
| `docs/toolkits/infographic_authoring.md` | CREATE | Feature documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage import ConversationSQLiteBackend, OverflowStore  # storage/__init__.py:21,17
from parrot.storage.backends import build_overflow_store             # local FS default
from parrot.tools.infographic_sections import SectionDescriptor      # TASK-1882
from parrot.bots.mixins import InfographicAuthoringMixin             # TASK-1884
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
def infographic_transformer(name, ...): ...        # line 164 — registration decorator
# RegisteredTransformer.__call__(inputs: dict[str, Any], params: dict[str, Any]) -> dict  # line 57
# Registry is idempotent for the SAME function; raises for a DIFFERENT one (~line 103).

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:
    async def run(self, name: str, *, params=None, pctx=None,
                  recipe_owner=None) -> RenderedArtifact: ...   # line 208
# ALWAYS pass the system-account pctx from TASK-1886 — falsy pctx fails OPEN.

# Reference analysis code to port (sdd/artifacts/executive_summary.py:40-51):
def day_totals(rows: list) -> dict:
    rev_a = sum(r[2] for r in rows); rev_b = sum(r[3] for r in rows)
    eb_a = sum(r[4] for r in rows); eb_b = sum(r[5] for r in rows)
    return {"rev_actual": rev_a, "rev_budget": rev_b,
            "rev_variance": rev_a - rev_b,
            "rev_variance_pct": (rev_a - rev_b) / rev_b * 100 if rev_b else 0,
            "ebitda_actual": eb_a, "ebitda_budget": eb_b,
            "ebitda_variance": eb_a - eb_b}
# division_breakdown(rows): executive_summary.py:54-71 (same row format).
# Payload consumed by the template: {"days": {"YYYYMMDD": [rows...]}}
# (daily_report.py:155-182 build_report_data). CSV columns: daily_report.py:64-73.

# Template splice anchor (verified):
# sdd/artifacts/budget_variance_dashboard_Template.html:106
#   <script type="application/json" id="report-data">
# File size 259,581 bytes > OverflowStore.INLINE_THRESHOLD (200 KB, overflow.py:34)
# ⇒ the rendered artifact MUST appear on the local filesystem (assert in e2e).
```

### Does NOT Exist
- ~~registered transformers `day_totals` / `division_breakdown`~~ — created HERE; today they
  are plain functions in `sdd/artifacts/executive_summary.py` only.
- ~~`tests/integration/test_dataagent_infographic_e2e.py`~~ — created HERE; check
  `packages/ai-parrot/tests/` layout (unit/ vs integration/) and conftest conventions first.
- ~~a versioned deployed template directory~~ — gitignored by decision; tests copy from
  `sdd/artifacts/` `(verify .gitignore templates/ rule at line 245 still applies)`.

---

## Implementation Notes

### Key Constraints
- Transformers must be PURE (no I/O, no globals) — that is the registry's contract.
- Adapt the ported functions to the registered-transformer calling convention
  `(inputs, params) -> dict` without changing their math; unit-test against hand-computed
  values from a tiny row set.
- e2e tests must not hit real LLMs: drive `generate_infographic` with a mocked/scripted agent
  or call the underlying flow with pre-built section datasets (the toolkit + descriptor path
  is what's under test, not the model).
- Local persistence in tests: point `PARROT_OVERFLOW_LOCAL_PATH` (or the store fixtures) at
  `tmp_path` — never write outside pytest tmp dirs.

### References in Codebase
- `packages/ai-parrot/tests/test_infographic_render_template.py` — toolkit test conventions
- `docs/toolkits/infographic_toolkit.md` — doc style to match

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] Unit + integration tests pass:
  `pytest packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py -v`
- [ ] No linting errors on new/modified files (`ruff check`)
- [ ] `day_totals`/`division_breakdown` resolvable by name in the transformer registry
- [ ] One-shot e2e: HTML lands on local disk, payload `{"days": ...}` spliced, template
  otherwise intact
- [ ] Publish+replay e2e: `RecipeRunner.run` with system-account pctx reproduces the artifact
  with fresh CSVs
- [ ] Delivery e2e: recipe carries `RenderSpec.delivery`; replay reaches the delivery path
- [ ] Docs page created and linked per `docs/` conventions

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py
class TestBudgetVarianceE2E:
    async def test_e2e_budget_variance_one_shot(self, budget_variance_template_dir,
                                                sample_snapshot_csvs, local_artifact_store): ...
    async def test_e2e_publish_and_replay(self, ...): ...
    async def test_e2e_delivery_config(self, ...): ...

class TestDomainTransformers:
    def test_day_totals_matches_reference_math(self): ...
    def test_division_breakdown_matches_reference_math(self): ...
    def test_registered_by_name(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** (TASK-1882..1886 ALL in `completed/`);
3. **Verify the Codebase Contract** (tests layout, transformer placement convention);
4. **Update index** → `"in-progress"`; 5. **Implement**; 6. **Verify criteria**;
7. **Move file to completed/**; 8. **Update index** → `"done"`; 9. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
