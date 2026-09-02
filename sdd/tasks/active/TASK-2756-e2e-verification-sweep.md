# TASK-2756: End-to-end verification — the three failing e2e tests pass unmodified

**Feature**: FEAT-499 — A2UI optional-binding lowering (`parrot_optional` reaches the wire)
**Spec**: `sdd/specs/a2ui-optional-binding-lowering.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2753, TASK-2754, TASK-2755
**Assigned-to**: unassigned

---

## Context

Closes spec §5. The whole feature exists because three FinanceReporter e2e tests fail on
`dev` today, and they are the acceptance gate: they must pass **without editing the test
file and without editing `agents/finance_reporter.py`'s layouts**. Deleting the
`/narrative` bindings would make them green while destroying the thing the Report profile
is for — that is explicitly a Non-Goal.

This task also adds the one integration test the earlier tasks cannot cover on their own
(both serving routes agreeing on a render failure) and establishes that no NEW failures
were introduced.

---

## Scope

- Run the three named e2e tests and confirm they pass with no edits to the test file or to
  the agent's descriptors.
- Add an integration test covering a failing-render surface GET across BOTH routes.
- Run the FEAT-470 v1.0 wire-conformance suite and confirm it is still green.
- Diff the full-suite result against the recorded pre-change baseline and confirm no NEW
  failures.
- Record the evidence under `artifacts/logs/` per CLAUDE.md.

**NOT in scope**: implementing any of the fixes (TASK-2753/2754/2755); fixing the
pre-existing unrelated failures listed below; any change to `agents/finance_reporter.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py` | MODIFY | Both-routes render-failure case |
| `artifacts/logs/feat-499-verification.log` | CREATE | Evidence of the runs |
| `packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py` | **DO NOT MODIFY** | The acceptance gate — must pass as-is |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `84932e839` (2026-09-02).

### Verified Imports
```python
# The e2e suite's own fixtures — reuse, do not rebuild:
#   packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py
#     recipe_store   (line 155)   — FileRecipeStore on tmp_path
#     wired_agent    (line 160)   — FinanceReporter(artifact_store=..., recipe_store=...)
#     published_report_recipe     (line 187)
#     published_dashboard_recipe  (line 196)
#     _FakeNarrator with DERIVABLE / INVENTED prose constants
from parrot.tools.infographic_recipes.runner import RecipeRunner
```

### Existing Signatures to Use
```python
# The three failing tests (DO NOT EDIT — they are the gate):
#   TestFinanceReporterNarrativeE2E::test_report_profile_replay_no_narrator      line 224
#   TestFinanceReporterNarrativeE2E::test_dashboard_profile_replay               line 248
#   TestFinanceReporterNarrativeE2E::test_end_to_end_no_fabricated_figures       line 276

# Current failure, identical for all three:
#   parrot.tools.infographic_recipes.runner.RecipeRunException:
#     Unresolvable data-model path '/narrative': member 'narrative' not found in {...}
#   raised at runner.py:654 (_render_or_raise), from baking.py:140 (_resolve_value)

# The agent's layouts — READ for context, DO NOT EDIT:
#   agents/finance_reporter.py  report_descriptor()    — binds summary + sections[0].text -> /narrative
#   agents/finance_reporter.py  dashboard_descriptor() — binds "Top Movers" text -> /narrative
#   both declare metadata={"extensions": {"parrot_optional": ["/narrative"]}}
```

### Does NOT Exist
- ~~a `--baseline` flag on pytest~~ — compare runs manually against the recorded list below.
- ~~`agents/finance_reporter.py` needing any change~~ — its layouts already declare
  `parrot_optional` correctly. If it looks like the agent needs editing, the core fix is
  wrong.
- ~~a single command that runs "the conformance suite"~~ — locate the FEAT-470 wire
  conformance tests (`grep -rl "agent_to_renderer" packages/*/tests`) before assuming a path.

---

## Implementation Notes

### Key Constraints
- **`test_dashboard_profile_replay` going green does NOT mean the feature works.** The
  `Infographic` layout is intercepted and is fixed by TASK-2753 alone;
  `test_report_profile_replay_no_narrator` exercises the LOWERED path and is the one that
  proves TASK-2754. Report both explicitly.
- `test_end_to_end_no_fabricated_figures` is the FEAT-420 G-H case: the figure guard
  correctly discards an invented figure, `/narrative` is then absent, and the render must
  still succeed. Confirm from the log that the guard actually fired
  (`Narrative figure guard rejected ... ['$999.9M']`) rather than the test passing because
  the narrator silently succeeded.
- Verify `ssr-html` and `pdf` too, not just `interactive-html` — those lanes are only
  covered by TASK-2754's unit tests otherwise.

### Pre-existing failures — EXCLUDE from the baseline, do NOT fix here
On `dev` @ `84932e839`, `packages/ai-parrot/tests/unit/bots/` already fails independently
of this feature:
- `test_pandasagent_stale_data_variables.py` — 3 tests; fail in isolation too
- `test_infographic_authoring_mixin.py::TestGenerateInfographic::test_validation_gate_blocks_before_render`
  — passes in isolation, fails in a full-directory run (test-ordering pollution)
- `test_flex_dashboard_agent.py::TestAgentConstruction::test_working_memory_and_infographic_toolkits_attached`
  — same ordering pollution

### References in Codebase
- `agents/flex_dashboard.py:553-575` — the FEAT-491 note documenting this exact bug and its
  workaround. Once this feature lands, that note is stale and the workaround (never binding
  `/narrative`) becomes optional. Flag it for follow-up; do NOT change it here.
- `agents/finance_reporter.py` — `publish_profile_surface()`'s `.. warning::` block
  references this spec and should be re-checked once the fix lands.

---

## Acceptance Criteria

- [ ] `test_report_profile_replay_no_narrator` passes, test file unmodified
- [ ] `test_dashboard_profile_replay` passes, test file unmodified
- [ ] `test_end_to_end_no_fabricated_figures` passes, with the figure guard confirmed to
      have fired in the log
- [ ] `agents/finance_reporter.py` is byte-identical to its pre-task state
- [ ] Both serving routes return the same 422 for a failing-render surface
- [ ] The FEAT-470 v1.0 wire-conformance suite is green
- [ ] `pytest packages/ai-parrot/tests/ packages/ai-parrot-server/tests/` shows no NEW
      failures vs. the pre-existing set listed above
- [ ] Evidence saved to `artifacts/logs/feat-499-verification.log`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py (additions)

class TestSurfaceGetRenderFailure:
    async def test_rest_route_returns_422(self, client, unrenderable_surface):
        resp = await client.get(f"/api/v1/ui/surfaces/{unrenderable_surface}",
                                headers={"Accept": "text/html"})
        assert resp.status == 422

    async def test_mirror_route_returns_the_same(self, client, unrenderable_surface):
        resp = await client.get(
            f"/api/v1/agents/finance_reporter/a2ui/surfaces/{unrenderable_surface}",
            headers={"Accept": "text/html"},
        )
        assert resp.status == 422
```

Verification commands:
```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py -v
git diff --exit-code agents/finance_reporter.py \
  packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py
pytest packages/ai-parrot/tests/ packages/ai-parrot-server/tests/ -q
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2753, TASK-2754 and TASK-2755 must all be in
   `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the three test names and line numbers
4. **Update status** in `sdd/tasks/index/a2ui-optional-binding-lowering.json` → `"in-progress"`
5. **Run and verify** — do not edit the gate tests to make them pass
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2756-e2e-verification-sweep.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
