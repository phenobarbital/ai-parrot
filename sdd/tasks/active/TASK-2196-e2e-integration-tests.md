# TASK-2196: Rewrite the e2e integration tests for the A2UI + narrative path

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2194
**Assigned-to**: unassigned

---

## Context

Implements **Module 8, part 3**. This task proves the feature's headline claims
end-to-end, and it is where the accepted consequence of the "replace" decision
gets paid: `packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py`
asserts the data-splice path for `FinanceReporter`, which TASK-2194 deleted, so
those tests fail by design and must be rewritten rather than patched around.

The two properties that matter most here cannot be established by unit tests
because they are pipeline-wide:

- **G-A**: `publish_recipe` on the real descriptor returns a saved recipe, not a
  `GapReport`.
- **G-E / G-H**: the same recipe replays successfully with **no** narrator
  (facts, no prose) and, when a narrator returns an invented figure, the
  artifact ships with **zero** prose rather than a wrong number.

---

## Scope

Rewrite / extend the integration suite to cover the spec §4 Integration Tests table:

- `test_publish_recipe_succeeds_not_gapreport` — **G-A**
- `test_report_profile_replay_no_narrator` — renders, numbers present, narrative
  sections absent, no exception
- `test_report_profile_replay_with_narrator` — prose appears in the rendered HTML
- `test_dashboard_profile_replay` — Infographic profile renders KPI/chart/table
  from the transformer outputs
- `test_interactive_html_renders_report_root` — regression lock on the verified
  behaviour that `Report` roots and per-section `text` already render, so a future
  satellite change cannot silently break the narrative without failing a test
- `test_scheduled_refresh_with_narrator` — `run_scheduled_refresh` over a
  narrator-bearing runner regenerates prose against fresh data
- `test_scheduled_refresh_without_system_account_fails_closed` — unprovisioned
  system account still raises `SystemAccountNotProvisioned` (no regression)
- `test_end_to_end_no_fabricated_figures` — **G-H**, the all-or-nothing guard

Also:
- Remove or rewrite every assertion in
  `test_dataagent_infographic_e2e.py` that depends on the deleted data-splice
  descriptor / `_build_section_payload`.
- Keep coverage of anything in that file that is **not** about `FinanceReporter`'s
  data-splice path — the file covers FEAT-326 Module 6 broadly; do not delete
  tests of still-valid behaviour.

**NOT in scope**:
- Unit tests for the individual modules — each dependency task owns its own.
- Any production-code change. If a test reveals a bug, fix it in the owning
  module and note it; do not paper over it in the test.
- Live LLM calls. Use a deterministic fake narrator throughout.
- Deleting `packages/ai-parrot/tests/unit/tools/test_infographic_data_splice.py` —
  the data-splice **render mode** stays supported (TASK-1883); only this agent's
  use of it is retired.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py` | MODIFY | Remove/rewrite data-splice assertions for `FinanceReporter`; keep still-valid FEAT-326 coverage |
| `packages/ai-parrot/tests/integration/test_finance_reporter_narrative_e2e.py` | CREATE | The eight integration tests above |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, NarrativeSpec
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException
from parrot.tools.infographic_sections import GapReport
from parrot.auth.system_account import (
    SystemAccountNotProvisioned, resolve_system_account_context, run_scheduled_refresh,
)
from agents.finance_reporter import FinanceReporter
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:
    def __init__(self, store, dataset_manager, *, artifact_store=None,
                 owner=None, narrator=None) -> None: ...          # narrator: TASK-2189
    async def run(self, name: str, *, params=None, pctx=None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...  # line 208
    async def dry_run(self, recipe) -> list[RecipeRunError]: ...   # line 256
class RecipeRunException(Exception):
    def __init__(self, error: RecipeRunError) -> None: ...          # line 88

# packages/ai-parrot/src/parrot/auth/system_account.py
def resolve_system_account_context(channel: str = "scheduler",
                                   account: Optional[SystemAccount] = None
                                   ) -> PermissionContext: ...      # line 90
    # raises SystemAccountNotProvisioned when PARROT_SYSTEM_ACCOUNT_ID is unset
    # (lines 110-118) and defensively when the context is falsy (lines 120-125)
async def run_scheduled_refresh(runner: Any, name: str, *, params=None,
                                recipe_owner=None, channel="scheduler",
                                account=None) -> Any: ...            # line 129
    # Takes a runner INSTANCE (docstring line 145) -> pass a narrator-bearing runner
# Env config: PARROT_SYSTEM_ACCOUNT_ID / _TENANT / _ROLES

# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
async def publish_recipe(self, name, descriptor, owner=None, delivery=None,
                         overwrite=False) -> Union[InfographicRecipe, GapReport]: ...  # line 280
    # returns GapReport when ANY section is unmapped (lines 358-363)
```

```python
# THE RENDERER BEHAVIOUR THIS TASK LOCKS IN (verified during spec research —
# no satellite change was needed, and this test makes that a contract):
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...  # 220
    def _render_top(self, comp) -> str:                      # line 261
        # Chart 263 / DataTable 265 / Infographic 267 -> else _render_via_lowering (269)
        # "Report" takes the lowering path
    def _render_via_lowering(self, comp) -> str: ...          # line 292
        # calls ReportComponent.lower (line 299); passes {} as data_model (line 306)
        # => binds MUST already be baked
    def _render_basic(self, node) -> str: ...                 # line 310
        # Text nodes -> <p class="a2ui-text a2ui-{role}">, escaped (lines 315-319)
    def _render_infographic(self, props) -> str: ...          # line 423
        # per-section text at lines 445-447: `if text is not None:` -> a2ui-body <p>

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/report.py
class ReportComponent:
    def lower(self, component, data_model) -> BasicTree: ...   # line 88
        # omits body Text when section["text"] is None   (line 105)
        # omits summary Text when props["summary"] is None (line 124)
        # root: Card(variant="report") with Text(role=title/heading/body/summary)
# => the rendered HTML for a narrated report contains class="a2ui-summary" /
#    "a2ui-body" <p> elements; without narrative those elements are ABSENT.
#    That is the assertable difference between the two replay tests.
```

```python
# agents/finance_reporter.py — AFTER TASK-2194 (read its Completion Note):
class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    narrative_skill = "budget-narrative"
    REPORT_RECIPE_NAME = "budget-variance-report"
    DASHBOARD_RECIPE_NAME = "budget-variance-dashboard"
    @classmethod
    def report_descriptor(cls) -> SectionDescriptor: ...
    @classmethod
    def dashboard_descriptor(cls) -> SectionDescriptor: ...
    async def register_datasets(self) -> None: ...     # line 73, table troc.finance_projection (81)
```

### Does NOT Exist

- ~~`FinanceReporter.budget_variance_descriptor()`~~ / ~~`_build_section_payload`~~ —
  removed by TASK-2194. Every existing assertion touching them must go.
- ~~a `days` transformer or a `/days` data_model key~~ — the A2UI profiles do not
  produce one.
- ~~`RecipeRunner` raising on a missing narrator~~ — it skips (TASK-2189). A test
  expecting an exception there is wrong.
- ~~a live LLM in the test path~~ — use a fake narrator implementing
  `async def narrate(self, facts, skill) -> Optional[str]`.
- ~~`_maybe_enhance` being involved in narrative rendering~~ — deprecated
  (FEAT-273) and unrelated.
- ~~`ai-parrot-visualizations` needing modification~~ — verified unnecessary; the
  spec has an acceptance criterion forbidding it. If a renderer test fails,
  investigate the envelope/bake side first.
- ~~`troc.finance_projection` existing in the dev database by default~~ — it is a
  seeded demo table (`examples/seed_finance_projection.py`). Integration tests
  must either seed their own fixture data or use the in-memory dataset pattern
  the existing FEAT-324 e2e test uses — check
  `packages/ai-parrot/tests/integration/infographic_recipes/test_e2e.py` for the
  established fixture approach before reaching for a live DB.

---

## Implementation Notes

### Pattern to Follow

```python
class _FakeNarrator:
    """Deterministic narrator — no LLM. Variants drive the two safety tests."""

    def __init__(self, prose: str):
        self._prose = prose

    async def narrate(self, facts, skill):
        return self._prose


DERIVABLE = "Revenue is behind budget and the gap is narrowing."
INVENTED = "Revenue is behind budget; a further $999.9M evaporated."


class TestNarrativeReplay:
    async def test_report_profile_replay_no_narrator(self, wired_agent, recipe_store, pctx):
        """G-E: no narrator -> numbers render, narrative elements absent."""
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager)
        artifact = await runner.run(FinanceReporter.REPORT_RECIPE_NAME, pctx=pctx)
        assert 'class="a2ui-summary"' not in artifact.content
        assert "a2ui-card" in artifact.content          # the report still rendered

    async def test_report_profile_replay_with_narrator(self, wired_agent, recipe_store, pctx):
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager,
                              narrator=_FakeNarrator(DERIVABLE))
        artifact = await runner.run(FinanceReporter.REPORT_RECIPE_NAME, pctx=pctx)
        assert "gap is narrowing" in artifact.content

    async def test_end_to_end_no_fabricated_figures(self, wired_agent, recipe_store, pctx):
        """G-H: an invented figure yields ZERO prose, not a wrong number."""
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager,
                              narrator=_FakeNarrator(INVENTED))
        artifact = await runner.run(FinanceReporter.REPORT_RECIPE_NAME, pctx=pctx)
        assert "999.9" not in artifact.content
        assert "behind budget" not in artifact.content   # ALL prose discarded
```

### Key Constraints

- **Always pass a real `pctx`.** A falsy `pctx` makes `DatasetManager`'s PBAC
  guards fail **open** (`runner.py:221-228`) — a test that omits it is testing an
  unsafe configuration. Build one with
  `parrot.auth.permission.build_principal_context` or the system-account resolver.
- The narrator-vs-no-narrator assertion should key off the **rendered HTML
  structure** (`a2ui-summary` / `a2ui-body` classes from
  `report.py:105,124` + `interactive_html.py:315-319`), not off a substring of
  prose that a future skill edit would change.
- `test_end_to_end_no_fabricated_figures` must assert **both** that the invented
  figure is absent **and** that the surrounding legitimate prose is also absent —
  all-or-nothing is the property, and asserting only the first would pass a
  partial-scrub implementation the spec forbids.
- For the scheduled tests, monkeypatch `PARROT_SYSTEM_ACCOUNT_ID` rather than
  relying on the developer's environment; assert the fail-closed path by unsetting it.
- Prefer the existing FEAT-324 e2e fixture style over a live database.
- If a rewritten test reveals a genuine defect in a dependency task's module, fix
  it there and record it in the Completion Note.

### References in Codebase

- `packages/ai-parrot/tests/integration/infographic_recipes/test_e2e.py` — the
  FEAT-324 load → dry_run → run walkthrough and its fixture approach
- `packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py` — the
  FEAT-326 file to rewrite
- `packages/ai-parrot/tests/outputs/a2ui/test_components_infographic_report.py` —
  golden tests for `Report`/`Infographic` lowering
- `examples/seed_finance_projection.py` — the table seeder, if a live table is needed

---

## Acceptance Criteria

- [ ] `test_publish_recipe_succeeds_not_gapreport` passes (**G-A**)
- [ ] `test_report_profile_replay_no_narrator` passes: renders, no narrative elements, no exception (**G-E**)
- [ ] `test_report_profile_replay_with_narrator` passes: prose present in the HTML
- [ ] `test_dashboard_profile_replay` passes: KPI/chart/table render from transformer outputs
- [ ] `test_interactive_html_renders_report_root` passes (regression lock)
- [ ] `test_scheduled_refresh_with_narrator` passes
- [ ] `test_scheduled_refresh_without_system_account_fails_closed` passes
- [ ] `test_end_to_end_no_fabricated_figures` passes, asserting **both** the invented figure and the legitimate prose are absent (**G-H**)
- [ ] No test performs a live LLM call
- [ ] Every `run()` call in the suite passes a real `pctx`
- [ ] `test_dataagent_infographic_e2e.py` no longer references
      `budget_variance_descriptor` or `_build_section_payload`
- [ ] Still-valid FEAT-326 coverage in that file is preserved, not deleted wholesale
- [ ] `packages/ai-parrot/tests/unit/tools/test_infographic_data_splice.py` still passes **unmodified**
- [ ] `ai-parrot-visualizations` is **unmodified** (`git diff --stat`)
- [ ] Full suite green: `pytest packages/ai-parrot/tests/integration/ -v`
- [ ] `ruff check` clean on both test files

---

## Test Specification

See the spec's §4 Integration Tests table — it is the authoritative list, and the
eight test names above match it. The fixtures needed:

```python
@pytest.fixture
async def wired_agent(artifact_store, recipe_store):
    """A configured FinanceReporter with its dataset registered."""

@pytest.fixture
async def published_recipes(wired_agent):
    """Publish BOTH profiles once; distinct names so no overwrite=True is needed."""

@pytest.fixture
def pctx():
    """A real PermissionContext — never None (runner.py:221-228 fails open on falsy)."""

@pytest.fixture
def snapshots_fixture():
    """3 snapshots x 2 divisions x 2 projects, exercising:
       - one project < -5000                       -> concentrated
       - one net-favourable division w/ a negative -> offset_by
       - one project absent at the first snapshot  -> trend None
       Mirrors the unit fixture in TASK-2186 so facts are predictable.
    """
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above — §4 Integration Tests is the
   authoritative list; §5 Acceptance Criteria states the properties being proven
2. **Check dependencies** — TASK-2194 must be in `sdd/tasks/completed/`, and
   **read its Completion Note** for the resolved descriptor design
3. **Verify the Codebase Contract** — confirm the renderer line references still
   hold; they are the basis of the structural assertions
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above.
   Expect the pre-existing FEAT-326 e2e tests to be red when you start — that is
   the state TASK-2194 intentionally left.
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2196-e2e-integration-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Defects found in dependency modules** (if any) and where they were fixed: ...
**Fixture approach**: in-memory dataset | seeded `troc.finance_projection` (and why).

**Deviations from spec**: none | describe if any
