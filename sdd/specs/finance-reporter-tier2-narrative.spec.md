---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: FinanceReporter Tier-2 + Narrative Skill

**Feature ID**: FEAT-420
**Date**: 2026-08-07
**Author**: Jesus
**Status**: draft
**Target version**: next

**Prior exploration**: `sdd/proposals/finance-reporter-tier2-narrative.brainstorm.md`
(Recommended Option B — *Deterministic facts + skill-guided injected narrator*)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

FEAT-326 shipped `FinanceReporter` (`agents/finance_reporter.py`) as the example
DataAgent that re-fills the reference budget-variance dashboard from live
Postgres data. It works, but it stops at **tier 1** and covers only the *raw
data* half of the original deliverable. Three concrete gaps:

1. **Tier 2 is unreachable for this agent.** `publish_recipe()` resolves a
   section to a registered transformer by normalising the section *name*
   (`infographic_authoring.py:394-397`). `FinanceReporter`'s only section is
   named `days`, and **no `days` transformer is registered** — so
   `publish_recipe()` always returns a `GapReport` and saves nothing
   (`infographic_authoring.py:358-363`). The agent can never become a
   deterministic, replayable, schedulable recipe, which is the entire point of
   the FEAT-324 ↔ FEAT-326 pairing.

2. **The ported analysis functions are orphaned.** FEAT-324 Module 3 ported the
   math of `sdd/artifacts/executive_summary.py` into seven registered
   transformers (`parrot/outputs/a2ui/recipes/library.py`) — `day_totals`,
   `division_breakdown`, `variance_analysis`, `top_movers` plus three generic
   helpers. `FinanceReporter` **imports none of them**; it hand-rolls its own
   pandas grouping in a `_build_section_payload` override
   (`finance_reporter.py:131-185`). Two implementations of the same domain, only
   one of them reachable from a recipe.

3. **The narrative layer was never built.** `executive_summary.py` produced a
   prose executive summary alongside the dashboard (`headline_text:159`,
   `division_read:183`, `trend_clause:258`, `build_docx:272`) and
   `daily_report.py` emailed both artifacts. The port deliberately excluded all
   of it — `library.py:198-200` states the transformers carry the math "WITHOUT
   any narrative sentence generation, which is a renderer/layout concern". That
   concern was never assigned to anyone. Today the platform can compute *that*
   EBITDA variance worsened, but cannot *say* so.

**Who is affected**: finance/ops consumers of the daily budget-variance report
(they currently get numbers with no interpretation, or fall back to the
standalone `daily_report.py` script running on someone's Windows box against a
OneDrive-synced folder); and every future reporting agent, which today has no
sanctioned pattern for narrative output.

**Why now**: the deterministic replay machinery (FEAT-324) and the authoring
machinery (FEAT-326) are both merged and stable. The remaining work is
connective, and the longer `FinanceReporter` stands as the canonical example
while bypassing the transformer library, the more it teaches the wrong pattern.

### Goals

- **G-A**: Close the tier-2 path — `publish_recipe()` on `FinanceReporter`'s
  descriptor produces a saved, replayable `InfographicRecipe` instead of a
  `GapReport`.
- **G-B**: Make `FinanceReporter` consume the already-ported finance
  transformers (`day_totals`, `division_breakdown`, `variance_analysis`,
  `top_movers`) instead of its own hand-rolled pandas grouping.
- **G-C**: Add a narrative layer implemented as an **agent skill** — prose is
  authored as editable data (`.agent/skills/`), not as Python.
- **G-D**: Keep every *number* deterministic. LLM output may add prose, never
  data (FEAT-324 G3/G7).
- **G-E**: A pure replay must never fail for lack of an LLM — no narrator
  configured means facts-without-prose, not an aborted run (FEAT-324 G6).
- **G-F**: Never store or execute code in a recipe — narrative is referenced by
  *skill name*, exactly as a transform is referenced by registered name
  (FEAT-324 G1).
- **G-G**: All schema changes additive — `InfographicRecipe.schema_version`
  stays `1` and pre-existing recipes keep loading.
- **G-H**: No fabricated figures reach a rendered financial artifact.
- **G-I**: Establish reusable primitives (`Narrator` protocol, `NarrativeMixin`,
  optional bindings) rather than one-off code in one agent.

### Non-Goals (explicitly out of scope)

- **`.docx` output.** `executive_summary.build_docx` (`executive_summary.py:272`)
  is NOT ported. No `python-docx` dependency is added; `.docx` remains an *input*
  format only in `parrot/`. A separate spec if ever wanted.
- **Deterministic sentence templating in Python.** Rejected in brainstorm — see
  `proposals/finance-reporter-tier2-narrative.brainstorm.md` Option A. It would
  re-land the rigid phrasing FEAT-324 deliberately declined to port.
- **Executable skill assets.** Rejected in brainstorm Option D; it violates G1
  and `transformers.py:72-79` refuses dynamic import of user-supplied paths in
  writing. Do not reach for it.
- **Reviving `InfographicToolkit._maybe_enhance`.** Deprecated (FEAT-273 / G7,
  `infographic_toolkit.py:1502-1509`) and raw-HTML-only. Narrative goes into
  catalog-validated component `text`, a different mechanism.
- **Removing the data-splice render mode.** TASK-1883's `render_data_template`
  stays; only *this agent's use of it* is retired.
- **Email/Outlook delivery wiring.** `RenderSpec.delivery` is left
  deployment-configured (resolved question), not hardcoded to
  `daily_report.py`'s recipient list.
- **Satellite renderer work.** Verified unnecessary — see §6 Integration Points.

---

## 2. Architectural Design

### Overview

The feature splits the narrative concern along the determinism boundary, and
generalises two hardcoded seams so the A2UI component-layout path becomes
publishable.

**Deterministic facts.** A new registered transformer `narrative_facts` derives
every *judgement* the prose needs — direction flags, the top driver with a
derived urgency, per-division read *kinds* — as structured data in the
`data_model`. It is a faithful port of the *branching* inside
`headline_text`/`division_read`/`trend_clause`, minus the English. Per the
resolved question, it takes the **generic** shape: it consumes the outputs of
prior transform steps (`variance_analysis`, `top_movers`, `division_breakdown`)
rather than raw frames, so any dataset that can feed those four transformers can
feed the narrative. This requires no new machinery — `_run_gate_or_raise`
already excludes prior-step aliases from column gating
(`runner.py:432-435,440`) and `_run_transforms_or_raise` already feeds
`data_model[alias]` for them (`runner.py:460-461`).

**Skill-guided prose.** A composite skill `.agent/skills/budget-narrative/`
teaches an LLM to render those facts as prose. The facts contract and the
reference phrasing live as *assets* served by `read_skill_asset`, because
`SkillDefinition.MAX_TOKENS = 1000` with a raising validator
(`skills/models.py:74-82`) makes a single-file skill carrying all of it
impossible.

**Declarative narrative step.** `InfographicRecipe` gains an optional
`narrative` field naming a skill, the facts key to read, and the output key to
write — a *reference*, never code (G-F). `RecipeRunner.__init__` gains an
optional keyword-only `narrator`; a new **async** step runs between the
transform chain and the bind-drift check. With no narrator, the step is skipped.

**Optional bindings.** Narrative binds carry a sibling `optional: true`.
Verified safe: `is_binding_expression` is a membership test (`models.py:90`) and
`_validate_bindings` validates only the pointer shape then returns
(`models.py:102-109`), so a sibling key breaks neither detection nor validation.
Two places learn to honour it — the runner's drift check and the bake pass's
`_resolve_value`.

**Figure guard.** After generation, numbers are extracted from the prose and
checked for derivability from the facts. Any non-derivable figure discards the
**entire** narrative and falls back to the no-narrative artifact — the same
degraded state as "no narrator", so there is one fallback path, not two (G-H).

**Layout generalisation.** `SectionDescriptor` gains an optional `layout`
(`LayoutSpec`). When present `publish_recipe` uses it verbatim; when absent it
keeps today's template-based behaviour (`infographic_authoring.py:379-382`), so
existing descriptors are untouched (G-G).

**Migration.** `FinanceReporter`'s data-splice descriptor and its
`_build_section_payload` override are **replaced** by two A2UI descriptors — a
`Report` profile (executive summary) and an `Infographic` profile (dashboard).
Accepted consequence: FEAT-326's e2e example and tests assert the data-splice
path for this agent and must be rewritten.

### Component Diagram

```
                      ┌─────────────────────── deterministic ───────────────────────┐
troc.finance_projection ──→ DatasetManager ──→ frames{snapshots, df}
                                                    │
                                                    ▼
                            variance_analysis ─┐
                            top_movers ────────┤   (existing, library.py)
                            division_breakdown ┤
                            day_totals ────────┘
                                                    │  data_model[...]
                                                    ▼
                                          narrative_facts        ← Module 1 (NEW)
                                          data_model["narrative_facts"]
                      └─────────────────────────────┬───────────────────────────────┘
                                                    │
                        ┌───────────────────────────┴──── probabilistic, fenced ────┐
                        │  RecipeRunner(narrator=?)                                 │
                        │      narrator is None ─────────────→ step SKIPPED         │
                        │      narrator present:                                    │
                        │        NarrativeMixin.narrate()   ← Module 5              │
                        │          load_skill("budget-narrative") + assets          │
                        │          → LLM → prose                                    │
                        │          → figure_guard()          ← Module 4             │
                        │              fails → DISCARD all prose                    │
                        │        data_model["narrative"] = prose                    │
                        └───────────────────────────┬───────────────────────────────┘
                                                    ▼
                              _check_bind_drift_or_raise  (honours `optional`)  ← Module 2
                                                    ▼
                              _assemble_envelope_or_raise
                                 layout.component == "Infographic" → build_infographic
                                 else (e.g. "Report")             → build_surface
                                                    ▼
                              bake_envelope  (_resolve_value honours `optional`)  ← Module 2
                                                    ▼
                              interactive-html renderer  (already renders Report + text)
                                                    ▼
                                          RenderedArtifact → delivery
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/recipes/library.py` | extends | register `narrative_facts` alongside the existing seven |
| `parrot/outputs/a2ui/recipes/models.py` | modifies (additive) | new `NarrativeSpec`; `InfographicRecipe.narrative`; `schema_version` stays `1` |
| `parrot/tools/infographic_recipes/runner.py` | modifies | `narrator` ctor kwarg; new async narrative step; drift check honours `optional`; `dry_run` validates the narrative reference |
| `parrot/outputs/a2ui/baking.py` | modifies | `_resolve_value` yields absent instead of `BakeError` for optional binds |
| `parrot/outputs/a2ui/models.py` | **no change** | verified: `_validate_bindings` already tolerates sibling keys |
| `parrot/tools/infographic_sections.py` | modifies (additive) | `SectionDescriptor.layout: Optional[LayoutSpec]` (note `extra="forbid"` — must be a declared field) |
| `parrot/bots/mixins/infographic_authoring.py` | modifies | `publish_recipe` honours `descriptor.layout` instead of hardcoding at 379-382 |
| `parrot/bots/mixins/` | extends | new `NarrativeMixin` |
| `parrot/tools/infographic_recipes/` | extends | `Narrator` protocol + figure guard (G8: must NOT live under `outputs/a2ui/`) |
| `parrot/skills/` (`SkillFileToolkit`) | uses | `load_skill` / `read_skill_asset` consumed by `NarrativeMixin` |
| `.agent/skills/budget-narrative/` | new | composite skill + assets (data, append-only) |
| `agents/finance_reporter.py` | modifies | drops data-splice descriptor + `_build_section_payload`; gains two A2UI descriptors |
| `parrot/auth/system_account.py` | **no change** | verified: `run_scheduled_refresh` takes a runner *instance*, so narrator injection needs nothing here |
| `ai-parrot-visualizations` renderer | **no change** | verified: `Report` roots and per-section `text` already render |
| `examples/`, `docs/`, e2e tests | modifies | see §3 Module 8 / Module 9 |

### Data Models

```python
# parrot/outputs/a2ui/recipes/models.py — NEW, additive
class NarrativeSpec(BaseModel):
    """Declarative narrative step: a REFERENCE to a skill, never code (G1)."""
    skill: str                      # skill name resolvable in the skill registry
    facts_key: str                  # data_model key holding the deterministic facts
    output_key: str = "narrative"   # data_model key the prose is written to

# parrot/outputs/a2ui/recipes/models.py — additive field on the existing model
class InfographicRecipe(BaseModel):
    schema_version: int = 1                              # UNCHANGED (G-G)
    ...
    narrative: Optional[NarrativeSpec] = None            # NEW

# Optional binding shape (no model change required — verified)
#   {"$bind": "/narrative/headline", "optional": True}

# narrative_facts output contract (generic shape — resolved question).
# Structure only; every value is derived deterministically.
{
  "headline": {
      "rev_state": "behind" | "ahead",
      "rev_direction": "narrowing" | "widening" | "flat",
      "ebitda_direction": "improved" | "worsened" | "held_steady",
      "both_improving": bool, "both_worsening": bool, "diverging": bool,
      "first_label": str, "last_label": str,
  },
  "top_driver": {
      "division": str, "project": str, "ebitda_variance": float,
      "trend": float | None,
      "urgency": "immediate" | "confirm_trend" | "check_timing" | "none",
  } | None,
  "division_reads": [
      {"division": str,
       "kind": "on_track" | "spread" | "concentrated" | "offset_by",
       "named": [str, ...],            # the materially-negative projects
       "offsetter": str | None}        # only for kind == "offset_by"
  ],
  "watch": [ {...} ], "bright": [ {...} ],   # from top_movers, with trend labels
  "n_snapshots": int,
}
```

### New Public Interfaces

```python
# parrot/tools/infographic_recipes/narrator.py — NEW (G8-safe side)
@runtime_checkable
class Narrator(Protocol):
    """Renders deterministic facts as prose. Implementations may call an LLM."""
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        ...

# parrot/tools/infographic_recipes/figure_guard.py — NEW
def extract_figures(prose: str) -> list[str]: ...
def figures_are_derivable(prose: str, facts: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, offending_figures). All-or-nothing: caller discards ALL prose on False."""

# parrot/tools/infographic_recipes/runner.py — MODIFIED ctor (keyword-only, additive)
class RecipeRunner:
    def __init__(self, store, dataset_manager, *, artifact_store=None,
                 owner=None, narrator: Optional[Narrator] = None) -> None: ...

# parrot/bots/mixins/narrative.py — NEW
class NarrativeMixin:
    """Implements Narrator over SkillRegistryMixin: load skill (+assets) → LLM → prose."""
    narrative_skill: Optional[str] = None
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]: ...

# parrot/tools/infographic_sections.py — MODIFIED (additive field)
class SectionDescriptor(BaseModel):
    ...
    layout: Optional[LayoutSpec] = None   # NEW; when set, publish_recipe uses it verbatim

# agents/finance_reporter.py — MODIFIED classmethods
class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    @classmethod
    def report_descriptor(cls) -> SectionDescriptor: ...        # Report profile
    @classmethod
    def dashboard_descriptor(cls) -> SectionDescriptor: ...     # Infographic profile
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: `narrative_facts` transformer
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py`
- **Responsibility**: Register a `narrative_facts` transformer deriving the
  structured judgements in §2 Data Models. **Generic shape** (resolved
  question): inputs are prior-step `output_key`s (`variance_analysis`,
  `top_movers`, `division_breakdown`), not frames — therefore
  `requires_columns={}` and column gating does not apply
  (`runner.py:432-435`). Ports the *branching* of
  `executive_summary.headline_text:159-180`, `division_read:183-201`,
  `trend_clause:258-269` and the recommendation urgency at `369-382`. Preserves
  the `-5000` materiality threshold (`executive_summary.py:142`), the 2dp money
  rounding convention of its siblings, and the division-by-zero guard
  (`library.py:98`).
- **Depends on**: existing `library.py` transformers (runtime, via data_model)

### Module 2: Optional data bindings
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py`,
  `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`
- **Responsibility**: Honour a sibling `optional: True` on a `$bind`.
  `_resolve_value` (`baking.py:60-86`) yields *absent* (property omitted)
  instead of raising `BakeError` when an optional pointer does not resolve.
  `_check_bind_drift_or_raise` (`runner.py:490-510`) excludes optional pointers
  from the fatal `missing` set and logs them at INFO instead of swallowing them
  silently. **No change to `a2ui/models.py`** — verified tolerant.
- **Depends on**: nothing (independent)

### Module 3: Narrative step — model + runner + `Narrator` protocol
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py`,
  `packages/ai-parrot/src/parrot/tools/infographic_recipes/narrator.py` (new),
  `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`
- **Responsibility**: Add `NarrativeSpec` + additive
  `InfographicRecipe.narrative` (`schema_version` stays `1`). Define the
  `Narrator` protocol on the `tools/` side of the G8 boundary. Add the
  keyword-only `narrator` ctor param and an **async** narrative step in `run()`
  between `_run_transforms_or_raise` (`runner.py:249`) and
  `_check_bind_drift_or_raise` (`runner.py:250`) — note the transform step is
  *sync* while this one must be awaited. No narrator → skip. Extend `dry_run`
  (`runner.py:256`) to report a `narrative` naming an unresolvable skill.
- **Depends on**: Module 2 (both touch `_check_bind_drift_or_raise`; land 2 first)

### Module 4: Figure guard
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_recipes/figure_guard.py` (new)
- **Responsibility**: Extract numeric literals from generated prose (handling
  the reference artifact's formats: `$1.23M`, `$45.6K`, `+12.3%`, the U+2212
  minus sign used by `fmt_money`/`fmt_pct`) and verify each is derivable from
  the facts within a tolerance that accounts for the facts' 2dp rounding and the
  prose's display rounding. Returns offending figures. **All-or-nothing**: any
  failure discards the whole narrative.
- **Depends on**: Module 1 (facts contract)

### Module 5: `NarrativeMixin`
- **Path**: `packages/ai-parrot/src/parrot/bots/mixins/narrative.py` (new),
  `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` (export)
- **Responsibility**: Implement `Narrator` over `SkillRegistryMixin` — resolve
  the skill, load its body and assets (`load_skill` `tools.py:454`,
  `read_skill_asset` `tools.py:491`), prompt the agent's LLM, apply the Module 4
  guard, return prose or `None`. Cooperative mixin (mixed in *before* the agent
  class, same MRO discipline as `InfographicAuthoringMixin`). Every failure path
  — skill missing, LLM error, guard rejection — logs a warning and returns
  `None`; never raises into the runner.
- **Depends on**: Modules 3, 4, 6

### Module 6: `budget-narrative` composite skill
- **Path**: `.agent/skills/budget-narrative/SKILL.md`,
  `.agent/skills/budget-narrative/facts-schema.md`,
  `.agent/skills/budget-narrative/reference.md`
- **Responsibility**: `SKILL.md` (**must be < 1000 tokens** —
  `skills/models.py:74-82`) with valid frontmatter (`name`, `description`,
  `triggers`) instructing how to render facts as prose and to read the assets
  for the contract and phrasing. `facts-schema.md` documents the
  `narrative_facts` contract; `reference.md` carries the phrasing ported from
  `executive_summary.py:159-269` as style exemplars.
- **Depends on**: Module 1 (facts contract)

### Module 7: `SectionDescriptor.layout` + `publish_recipe`
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_sections.py`,
  `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`
- **Responsibility**: Add the additive optional `layout: Optional[LayoutSpec]`
  field (declared explicitly — `SectionDescriptor` is `extra="forbid"`). Change
  `publish_recipe` to use `descriptor.layout` verbatim when present, else keep
  today's hardcoded template `LayoutSpec` (`infographic_authoring.py:379-382`).
  Carry `narrative` through to the saved recipe when the descriptor declares
  one.
- **Depends on**: Module 3 (`NarrativeSpec` for the carry-through)

### Module 8: `FinanceReporter` migration + examples + e2e rewrite
- **Path**: `agents/finance_reporter.py`,
  `examples/budget_variance_infographic.py`,
  `examples/infographic_recipes/budget-variance-daily.yaml`,
  `packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py`
- **Responsibility**: Compose `NarrativeMixin`. **Remove**
  `budget_variance_descriptor()` (`finance_reporter.py:108`) and the
  `_build_section_payload` override (`finance_reporter.py:131-185`). Add
  `report_descriptor()` (Report root) and `dashboard_descriptor()` (Infographic
  root), both declaring `layout` with `$bind` pointers into the transformer
  outputs and `optional` narrative binds. Pass `snapshot_col="snapshot_date"`
  **explicitly** in every step's params (resolved question — the transformers
  default to `"snapshot"`, `library.py:13`, while the table exposes
  `snapshot_date`, `finance_reporter.py:44`). Leave `RenderSpec.delivery`
  deployment-configured. Rewrite the e2e test off the data-splice assertions;
  the two profiles need **distinct recipe names** (a `(name, owner)` collision
  requires `overwrite=True`, `infographic_authoring.py:321-330`).
- **Depends on**: Modules 1, 3, 5, 6, 7

### Module 9: Documentation
- **Path**: `docs/toolkits/infographic_authoring.md`,
  `docs/outputs/infographic-recipes.md`
- **Responsibility**: Document `SectionDescriptor.layout`, the declarative
  `narrative` step, narrator injection, optional bindings, the figure guard, and
  the scheduled-refresh narrative path (system account + LLM). Correct the
  authoring doc's claim that the default builder is the only programmatic seam.
- **Depends on**: all preceding modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_narrative_facts_directions` | 1 | Direction flags match the reference branching for narrowing/widening/flat × improved/worsened/held_steady |
| `test_narrative_facts_single_snapshot` | 1 | One snapshot → flat/held_steady, no trend claimed, `n_snapshots == 1` |
| `test_narrative_facts_division_read_kinds` | 1 | Emits `on_track` / `spread` / `concentrated` / `offset_by` per the reference's four branches; `offsetter` named only for `offset_by` |
| `test_narrative_facts_materiality_threshold` | 1 | Only projects with `ebitda_variance < -5000` are `named`, max 2 |
| `test_narrative_facts_new_project_trend_none` | 1 | Project absent at first snapshot → `trend is None` |
| `test_narrative_facts_urgency_branches` | 1 | `immediate` / `confirm_trend` / `check_timing` / `none` per trend sign |
| `test_narrative_facts_zero_budget_guard` | 1 | Zero budget does not raise (mirrors `library.py:98`) |
| `test_narrative_facts_consumes_prior_step_outputs` | 1 | Registered with `requires_columns={}`; gate passes when inputs are prior `output_key`s |
| `test_optional_bind_absent_omits_property` | 2 | `_resolve_value` omits instead of raising `BakeError` for an unresolved optional bind |
| `test_required_bind_absent_still_raises` | 2 | Non-optional unresolved bind still raises `BakeError` (no regression) |
| `test_drift_check_tolerates_optional` | 2 | `_check_bind_drift_or_raise` does not raise for a missing optional pointer |
| `test_drift_check_still_fails_required` | 2 | Missing required pointer still raises with the existing diagnostic |
| `test_narrative_spec_additive_schema_v1` | 3 | Recipe with `narrative` loads at `schema_version == 1`; a recipe without it still loads |
| `test_runner_without_narrator_skips_step` | 3 | `narrator=None` → run succeeds, `narrative` key absent from `data_model` |
| `test_runner_with_narrator_populates_key` | 3 | Fake narrator → prose lands at `narrative.output_key` |
| `test_runner_narrator_exception_degrades` | 3 | Narrator raising → warning logged, run still succeeds without prose |
| `test_dry_run_flags_unknown_skill` | 3 | `dry_run` reports a `narrative` naming an unresolvable skill |
| `test_figure_guard_accepts_derivable` | 4 | Prose quoting figures present in the facts passes, incl. `$1.23M` / `$45.6K` / `+12.3%` / U+2212 minus |
| `test_figure_guard_rejects_invented` | 4 | A figure absent from the facts is reported as offending |
| `test_figure_guard_rounding_tolerance` | 4 | Display rounding of a 2dp fact is not a false positive |
| `test_narrative_mixin_returns_none_on_missing_skill` | 5 | Missing skill → `None` + warning, never raises |
| `test_narrative_mixin_applies_guard` | 5 | Guard failure discards ALL prose (returns `None`), not just the offending sentence |
| `test_narrative_mixin_loads_assets` | 5 | `read_skill_asset` is consulted for the facts contract |
| `test_skill_body_under_token_cap` | 6 | `SkillDefinition` parses `SKILL.md` without tripping `MAX_TOKENS` |
| `test_skill_discovered_by_loader` | 6 | `SkillsDirectoryLoader` discovers the composite layout and sets `assets_dir` |
| `test_publish_recipe_uses_descriptor_layout` | 7 | `descriptor.layout` present → saved recipe carries it verbatim |
| `test_publish_recipe_without_layout_unchanged` | 7 | Absent → today's template-based `LayoutSpec` (regression guard) |
| `test_publish_recipe_carries_narrative` | 7 | Declared narrative reaches the saved recipe |
| `test_finance_reporter_descriptors_validate` | 8 | Both descriptors pass `validate_descriptor_datasets` against the registered dataset |
| `test_finance_reporter_passes_snapshot_col` | 8 | Every step's params set `snapshot_col="snapshot_date"` |

### Integration Tests

| Test | Description |
|---|---|
| `test_publish_recipe_succeeds_not_gapreport` | **G-A**: `publish_recipe` on `FinanceReporter`'s descriptor returns a saved `InfographicRecipe`, not a `GapReport` |
| `test_report_profile_replay_no_narrator` | Full `RecipeRunner.run()` on the Report profile with `narrator=None` → artifact renders, numbers present, narrative sections omitted, no exception |
| `test_report_profile_replay_with_narrator` | Same with a fake narrator → prose appears in the rendered HTML |
| `test_dashboard_profile_replay` | Infographic profile replays and renders KPI/chart/table from the transformer outputs |
| `test_interactive_html_renders_report_root` | Report-rooted envelope renders through `interactive-html` (regression lock on the verified behaviour) |
| `test_scheduled_refresh_with_narrator` | `run_scheduled_refresh` over a narrator-bearing runner regenerates prose against fresh data (no `system_account.py` change) |
| `test_scheduled_refresh_without_system_account_fails_closed` | Unprovisioned system account still raises `SystemAccountNotProvisioned` (no regression) |
| `test_end_to_end_no_fabricated_figures` | **G-H**: a narrator returning prose with an invented figure yields an artifact with zero prose rather than a wrong number |

### Test Data / Fixtures

```python
# Reuse the existing FEAT-324 multi-snapshot fixture shape (one frame + snapshot col).
@pytest.fixture
def snapshots_frame() -> pd.DataFrame:
    """3 snapshots × 2 divisions × 2 projects, with:
       - one project materially negative (< -5000) to trigger `concentrated`
       - one division net-favourable despite a negative project (`offset_by`)
       - one project absent at the first snapshot (trend is None)
       - one division with zero budget (division-by-zero guard)
    Columns: snapshot, division, project, rev_actual, rev_budget,
             ebitda_actual, ebitda_budget
    """

@pytest.fixture
def fake_narrator():
    """Deterministic Narrator stub — no LLM. Variants: ok / raises / invents-a-figure."""

@pytest.fixture
def narrative_facts_golden() -> dict:
    """Expected narrative_facts output for `snapshots_frame` (golden contract)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v`)
- [ ] All integration tests pass (`pytest packages/ai-parrot/tests/integration/ -v`)
- [ ] Documentation updated in `docs/` (Module 9)
- [ ] No breaking changes to existing public API
- [ ] **G-A**: `FinanceReporter.publish_recipe(...)` returns a saved
      `InfographicRecipe` (asserted, not a `GapReport`)
- [ ] **G-B**: `agents/finance_reporter.py` contains no hand-rolled aggregation —
      `_build_section_payload` override removed; every number traces to a
      registered transformer
- [ ] **G-C**: `.agent/skills/budget-narrative/` is discovered by
      `SkillsDirectoryLoader` with `assets_dir` populated, and changing prose
      style requires editing only that directory
- [ ] **G-D**: no LLM output is ever written to a `data_model` key that a
      numeric component binds to — narrative occupies its own key, bound only by
      text properties
- [ ] **G-E**: `RecipeRunner.run()` with `narrator=None` completes successfully
      on a narrative-declaring recipe and produces a renderable artifact
- [ ] **G-F**: `InfographicRecipe` stores no code — only a skill *name*; grep
      confirms no prompt/source strings persisted in a saved recipe
- [ ] **G-G**: `InfographicRecipe.schema_version == 1` unchanged, and an existing
      pre-feature recipe fixture still loads and runs
- [ ] **G-H**: a narrator returning an invented figure yields an artifact with
      **no** prose (all-or-nothing), verified by integration test
- [ ] **G-I**: `Narrator` protocol and `NarrativeMixin` carry no
      budget-variance-specific logic (a second domain could reuse them unchanged)
- [ ] `SKILL.md` parses under `SkillDefinition.MAX_TOKENS = 1000`
- [ ] `ruff check` and `mypy` clean on all changed files
- [ ] No new third-party dependency added (verified against `pyproject.toml` diff)
- [ ] `ai-parrot-visualizations` is **unmodified** (the verified no-op stays a no-op)
- [ ] `parrot/outputs/a2ui/**` still imports no agents / `DatasetManager` / LLM
      clients (G8 preserved — the `Narrator` protocol lives under
      `parrot/tools/infographic_recipes/`)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

All references below were re-verified on 2026-08-07 against `dev` at the merge
of `origin/dev` (`c3db2693d`), after the brainstorm was written.

### Verified Imports

```python
# All confirmed to resolve in the current tree:
from parrot.outputs.a2ui.recipes.transformers import (
    infographic_transformer, transformer_registry, validate_inputs,
)
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec, InfographicRecipe, LayoutSpec, RecipeRunError, RenderSpec,
    ScheduleSpec, TransformerManifest, TransformStep,
)                                     # as imported by infographic_authoring.py:40-46
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError    # infographic_authoring.py:47
from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.models import (
    BINDING_KEY, Component, CreateSurface, is_binding_expression, is_valid_pointer,
)
from parrot.outputs.a2ui.baking import BakeError, bake_envelope
from parrot.outputs.a2ui.catalog import get_component, register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, CatalogValidationError
from parrot.tools.infographic_sections import (
    GapReport, ProvenanceDescriptor, SectionDescriptor, SectionSpec,
    TransformerGap, validate_descriptor_datasets, validate_payload_shape,
)                                     # as imported by infographic_authoring.py:32-39
from parrot.tools.infographic_toolkit import (
    InfographicRenderResult, InfographicToolkit, InfographicValidationError,
)
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.skills.models import SkillDefinition
from parrot.skills.loader import SkillsDirectoryLoader
from parrot.skills.mixin import SkillRegistryMixin
from parrot.auth.system_account import resolve_system_account_context, run_scheduled_refresh
from parrot.registry import register_agent
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:
    def __init__(self, store: AbstractRecipeStore, dataset_manager: DatasetManager, *,
                 artifact_store: Any = None,      # line 199
                 owner: Any = None) -> None: ...  # line 200 / def at line 194
    async def run(self, name: str, *, params: dict[str, Any] | None = None,
                  pctx: Any | None = None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...  # line 208
    # pipeline body lines 245-254 (INSERT the narrative step between 249 and 250):
    #   245 _load_recipe / 246 _resolve_params_or_raise / 247 _fetch_frames
    #   248 _run_gate_or_raise / 249 _run_transforms_or_raise  (SYNC)
    #   250 _check_bind_drift_or_raise / 251 _assemble_envelope_or_raise
    #   252 _render_or_raise (async) / 253 _deliver_best_effort (async)
    async def dry_run(self, recipe: InfographicRecipe) -> list[RecipeRunError]: ...   # line 256
    def _run_gate_or_raise(self, recipe, frames: dict[str, pd.DataFrame]) -> None: ... # line 429
    def _run_transforms_or_raise(self, recipe, frames, resolved_params) -> dict[str, Any]: ...  # line 448 (SYNC)
    def _check_bind_drift_or_raise(self, recipe, data_model) -> None: ...  # line 490
    def _assemble_envelope_or_raise(self, recipe, data_model): ...          # line 512
    async def _render_or_raise(self, recipe, envelope) -> RenderedArtifact: ... # line 537

# CRITICAL (enables the generic narrative_facts): prior-step outputs are NOT column-gated.
#   runner.py:432-435 comment — "an input referencing a PRIOR step's dict output_key has
#   no columns to check and is validated instead at transform-execution time"
#   runner.py:440       — inputs filtered to `alias in frames` before validate_inputs
#   runner.py:460-461   — `elif alias in data_model: step_inputs[alias] = data_model[alias]`
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class TransformStep(BaseModel):      # line 79
    transformer: str
    inputs: list[str] = Field(default_factory=list)             # line 93
    params: dict[str, Any] = Field(default_factory=dict)        # line 94
    output_key: str
class LayoutSpec(BaseModel):         # line 98
    component: str
    properties: dict[str, Any] = Field(default_factory=dict)    # line 110
class RenderSpec(BaseModel):         # line 113
    profile: str = "interactive-html"                           # line 125
    theme: Optional[str] = None                                 # line 126
    delivery: Optional[dict[str, Any]] = None                   # line 127
class ScheduleSpec(BaseModel):       # line 130
    principal: str
    tenant_id: Optional[str] = None                             # line 150
    roles: list[str] = Field(default_factory=list)              # line 151
class InfographicRecipe(BaseModel):  # line 154
    schema_version: int = 1                                     # line 184  <-- MUST STAY 1
    transforms: list[TransformStep] = Field(default_factory=list)  # line 191
    layout: LayoutSpec
    render: RenderSpec = Field(default_factory=RenderSpec)         # line 193
    schedule: Optional[ScheduleSpec] = None                        # line 194
    section_descriptor: Optional[SectionDescriptor] = None         # line 196  <-- additive precedent
class RecipeRunError(BaseModel):     # line 240
    transformer: Optional[str] = None       # line 256
    dataset: Optional[str] = None           # line 257
    missing_columns: list[str] = Field(default_factory=list)  # line 258
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
BINDING_KEY = "$bind"                                              # line 50
def is_valid_pointer(pointer: str) -> bool: ...                    # line 59
def is_binding_expression(value: Any) -> bool:                     # line 79
    return isinstance(value, dict) and BINDING_KEY in value        # line 90
def _validate_bindings(value: Any) -> None: ...                    # line 93
    # lines 102-109: validates ONLY the pointer shape, then `return` (line 109).
    # VERIFIED: a sibling key such as {"optional": True} is neither rejected
    # nor stripped. No change to this module is required.
class Component(BaseModel):                                        # line 123
    model_config = ConfigDict(populate_by_name=True, extra="allow")  # line 137
    id: str; component: str                                        # lines 139-140
    properties: dict[str, Any] = Field(default_factory=dict)       # line 141
    children: list[str] = Field(default_factory=list)              # line 142
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError(Exception): ...                                    # line 31
def _resolve_value(value: Any, data_model: dict[str, Any]) -> Any: ...  # line 60
    # is_binding_expression check line 74; raises BakeError lines 78-81 on
    # jsonpointer.JsonPointerException  <-- Module 2 changes exactly this branch
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]: ...  # line 100
# jsonpointer imported lazily (lines 35-57) — satellite-only resolution (G8)
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                  component_id: str = "blk-000",
                  data_model: Optional[dict[str, Any]] = None) -> CreateSurface: ...  # line 44
def build_infographic(*, title: str, sections: Sequence[dict[str, Any]],
                      subtitle: Optional[str] = None, theme: Optional[str] = None,
                      surface_id: str = "infographic",
                      data_model: Optional[dict[str, Any]] = None) -> CreateSurface: ...  # line 151
# section item shape (docstring lines 162-163):
#   {"heading": ..., "text"?: ..., "components"?: [{"component": n, "properties": {...}}]}
# G8 note lines 11-12: imports only the a2ui core; never agents/DatasetManager/LLM clients
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/report.py
REPORT_SCHEMA  # line 31; properties: title, metadata, summary, sections[heading,text,components]
               # required: ["title", "sections"] (line 62); section requires ["heading"] (line 46)
@register_component("Report")
class ReportComponent:
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree: ...  # line 88
    # VERIFIED graceful omission — the exact behaviour Module 2 relies on:
    #   line 105: `if section.get("text") is not None:`  -> body Text node ONLY when present
    #   line 124: `if props.get("summary") is not None:` -> summary Text node ONLY when present
    #   lowers to Card(variant="report") with Text(role=title/heading/body/summary) children

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/infographic.py
INFOGRAPHIC_SCHEMA  # per-section "text": {"type": "string"} IS present
@register_component("Infographic")
class InfographicComponent:
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree: ...  # line 88
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py
_MONEY_COLUMNS = ["rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"]  # line 39
_SAFE_AGG_FUNCS = frozenset({...})                                    # line 48
def _day_totals_for(df) -> dict[str, Any]: ...                        # line 82
#   rev_variance_pct division guard: `if rev_b else 0.0`              # line 98
@infographic_transformer("day_totals", ...)         def day_totals(inputs, params)          # 105 / 120
@infographic_transformer("division_breakdown", ...) def division_breakdown(inputs, params)  # 132 / 146
@infographic_transformer("variance_analysis", ...)  def variance_analysis(inputs, params)   # 191 / 209
@infographic_transformer("top_movers", ...)         def top_movers(inputs, params)          # 253 / 270
@infographic_transformer("groupby_aggregate", ...)  def groupby_aggregate(inputs, params)   # 318 / 333
@infographic_transformer("pivot", ...)              def pivot(inputs, params)               # 346 / 362
@infographic_transformer("latest_vs_baseline", ...) def latest_vs_baseline(inputs, params)  # 375 / 389
# variance_analysis returns (lines 239-250): first_snapshot, last_snapshot, first_totals,
#   last_totals, rev_pct_change, ebitda_dollar_change, rev_direction, ebitda_direction,
#   rev_state, n_snapshots
# top_movers returns (line 315): {"worst": [...], "best": [...]}, each entry
#   {division, project, ebitda_variance, trend}; trend None when new (lines 302-306)
# snapshot_col convention: default "snapshot", overridable param (lines 9-16, 13)
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
TransformerFunc = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
def infographic_transformer(name: str, *, requires_columns=None, description="",
                            params_schema=None) -> Callable: ...        # line 164
def validate_inputs(step: TransformStep, frames: dict[str, pd.DataFrame], *,
                    recipe_name: str = "") -> list[RecipeRunError]: ...  # line ~198
class TransformerRegistry:
    def register(self, name, func, *, requires_columns=None, description="",
                 params_schema=None) -> RegisteredTransformer: ...
    def get(self, name) -> RegisteredTransformer: ...   # raises KeyError
    def manifest(self, name) -> TransformerManifest: ...
    def list(self) -> list[TransformerManifest]: ...
transformer_registry: TransformerRegistry   # module-level shared instance
# G1, lines 72-79: "there is no dynamic import of user-supplied dotted paths,
#   which would reopen the G1 'stored code' hole"  <-- do NOT add one
```

```python
# packages/ai-parrot/src/parrot/tools/infographic_sections.py
class SectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str; target: str
    datasets: List[str] = Field(default_factory=list)
    columns: Dict[str, List[str]] = Field(default_factory=dict)
    shape: Literal["records", "scalar", "mapping", "table"]
    hint: Optional[str] = None
class SectionDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")   # <-- `layout` MUST be a declared field
    template: str
    mode: Literal["jinja", "data-splice"]
    splice_marker_id: str = "report-data"
    sections: List[SectionSpec] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
def validate_descriptor_datasets(descriptor, dataset_manager) -> None: ...
def validate_payload_shape(descriptor, payload) -> None: ...
class ProvenanceDescriptor(BaseModel): ...   # descriptor, dataset_snapshots, artifact_id, tier, recipe_ref
class TransformerGap(BaseModel): ...         # section, proposed_name, suggested_source
class GapReport(BaseModel): ...              # gaps, covered
class AdhocDatasetAdapter: ...
```

```python
# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
class InfographicAuthoringMixin:
    def __init__(self, *args, infographic_toolkit=None, artifact_store=None,
                 recipe_store=None, template_dirs=None, **kwargs) -> None: ...
    async def configure(self, *args, **kwargs) -> None: ...
    async def generate_infographic(self, template: str, descriptor, params=None
                                   ) -> Tuple[InfographicRenderResult, ProvenanceDescriptor]: ...
        # validate_descriptor_datasets 151 -> _build_section_payload 153
        # -> render_data_template 156 | render_template 163 -> ProvenanceDescriptor 169
    async def _build_section_payload(self, descriptor, params) -> Tuple[Dict, Dict[str, str]]: ...  # 182
        # raises InfographicValidationError("multi_dataset_section_unsupported") at 220
    @staticmethod
    def _assemble_section(section, frames) -> Any: ...   # line 250 — reshape only, NO transformer lookup
    async def publish_recipe(self, name, descriptor, owner=None, delivery=None,
                             overwrite=False) -> Union[InfographicRecipe, GapReport]: ...  # 280
        # collision check 321-330; transformer_registry.get(tname) 338; GapReport 358-363
        # LAYOUT HARDCODED 379-382:
        #   LayoutSpec(component="Infographic", properties={"template": descriptor.template})
    @staticmethod
    def _transformer_name(section) -> str:                 # line 394
        return re.sub(r"\W+", "_", section.name).strip("_")  # line 397
    @staticmethod
    def _suggest_transformer_source(section, fn_name) -> str: ...  # line 399 (NEVER executed)
```

```python
# agents/finance_reporter.py
DEFAULT_TEMPLATE_DIR = <repo>/sdd/artifacts                       # line 41
FINANCE_DATASET = "finance_projection"                            # line 43
FINANCE_COLUMNS = ["snapshot_date", "division", "project", "rev_actual",
                   "rev_budget", "ebitda_actual", "ebitda_budget"]  # lines 44-52
@register_agent(name="finance_reporter")                          # line 55
class FinanceReporter(InfographicAuthoringMixin, PandasAgent):     # line 56
    agent_id = "finance_reporter"                                  # line 59
    llm = "google:gemini-3.5-flash"                                # line 60
    TEMPLATE_NAME = "budget_variance_dashboard_Template.html"      # line 62
    async def register_datasets(self) -> None: ...                 # line 73 (table at line 81)
    async def configure(self, app=None, queries=None) -> None: ... # line 99
    @classmethod
    def budget_variance_descriptor(cls) -> SectionDescriptor: ...  # line 108  <-- REMOVE (Module 8)
    async def _build_section_payload(self, descriptor, params): ... # line 131  <-- REMOVE (Module 8)
```

```python
# packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                        # line 53
    name: str; description: str; triggers: List[str]     # lines 59-61
    source: SkillSource = SkillSource.AUTHORED           # line 62
    priority: int = 90                                   # line 63
    version: str = "1.0"                                 # line 64
    category: Optional[str] = None                       # line 65
    template_body: str                                   # line 66
    token_count: int                                     # line 67
    file_path: Path                                      # line 68
    assets_dir: Optional[Path] = Field(default=None)     # line 69 (composite only)
    MAX_TOKENS: ClassVar[int] = 1000                     # line 74  <-- HARD CAP
    @field_validator("token_count")                      # line 76 -> RAISES above cap

# packages/ai-parrot/src/parrot/skills/tools.py
class SkillFileToolkit(AbstractToolkit):                          # line 371
    async def list_skill_commands(self) -> ToolResult: ...        # line 413
    async def load_skill(self, name: str) -> ToolResult: ...      # line 454
    async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult: ...  # line 491
def create_skill_tools(...)                                       # line 635

# packages/ai-parrot/src/parrot/skills/loader.py
class SkillsDirectoryLoader:
    def __init__(self, paths: List[Path], logger: Optional[Logger] = None) -> None: ...
    async def discover(self) -> List[SkillDefinition]: ...
    async def load_into(self, registry: SkillFileRegistry) -> int: ...
# layouts: single-file {dir}/{name}.md | composite {dir}/{name}/SKILL.md + assets

# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:
    enable_skill_registry: bool = True
    skill_paths: List[Path] = []          # recommended [Path(".agent/skills/")]
    inject_skills_into_prompt: bool = True
    async def get_skill_context(self, query, max_skills, max_tokens): ...
```

```python
# packages/ai-parrot/src/parrot/auth/system_account.py
def resolve_system_account_context(channel: str = "scheduler",
                                   account: Optional[SystemAccount] = None
                                   ) -> PermissionContext: ...     # line 90
async def run_scheduled_refresh(runner: Any, name: str, *, params=None,
                                recipe_owner=None, channel="scheduler",
                                account=None) -> Any: ...           # line 129
# Takes a runner INSTANCE -> narrator injection needs NO change here.
# Docstring line 142: "RecipeRunner is NEVER modified and pctx=None is NEVER forwarded"
```

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
# VERIFIED — no satellite change needed for either narrative profile:
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...  # 220
    def _render_top(self, comp) -> str: ...        # line 261
        # Chart 263 / DataTable 265 / Infographic 267 -> else _render_via_lowering (269)
        # "Report" therefore takes the lowering path (docstring line 19 lists Report)
    def _render_via_lowering(self, comp) -> str: ...  # line 292 -> ReportComponent.lower (299)
        # NOTE line 306: passes `{}` as data_model — binds MUST already be baked
    def _render_basic(self, node: BasicNode) -> str: ...  # line 310
        # Text nodes rendered at 315-319 with role -> CSS class, text HTML-escaped
    def _render_infographic(self, props) -> str: ...      # line 423
        # per-section text honoured at 445-447: `if text is not None:` -> a2ui-body <p>
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `narrative_facts` | `variance_analysis` / `top_movers` / `division_breakdown` outputs | prior-step `output_key` as `TransformStep.inputs` | `runner.py:460-461`, gate exclusion `runner.py:432-435,440` |
| `narrative_facts` | `transformer_registry` | `@infographic_transformer("narrative_facts", requires_columns={})` | `transformers.py:164` |
| `NarrativeSpec` | `InfographicRecipe` | additive optional field | `models.py:196` (additive precedent) |
| narrative step | `RecipeRunner.run()` | `await` between lines 249 and 250 | `runner.py:245-254` |
| `Narrator` | `RecipeRunner.__init__` | keyword-only `narrator=None` | `runner.py:194-206` |
| optional bind | `_check_bind_drift_or_raise` | exclude optional pointers from `missing` | `runner.py:490-510` |
| optional bind | `_resolve_value` | omit instead of `BakeError` | `baking.py:60-86` (raise at 78-81) |
| optional bind | `is_binding_expression` / `_validate_bindings` | **no change** — sibling key tolerated | `models.py:90`, `models.py:102-109` |
| absent narrative | `ReportComponent.lower` | already omits absent `text`/`summary` | `report.py:105`, `report.py:124` |
| absent narrative | `_render_infographic` | already omits absent section `text` | `interactive_html.py:445-447` |
| `Report` root | `_assemble_envelope_or_raise` | non-`Infographic` → `build_surface` | `runner.py:524-530` |
| `Report` root | `interactive-html` | `_render_top` → `_render_via_lowering` | `interactive_html.py:269,292` |
| `NarrativeMixin` | `SkillFileToolkit` | `load_skill` / `read_skill_asset` | `tools.py:454`, `tools.py:491` |
| `SectionDescriptor.layout` | `publish_recipe` | replaces the hardcoded `LayoutSpec` | `infographic_authoring.py:379-382` |
| narrator-bearing runner | `run_scheduled_refresh` | runner instance passed in; **no change** | `system_account.py:129,145` |

### Does NOT Exist (Anti-Hallucination)

- ~~`transformer_registry.get("days")`~~ — **no `days` transformer is registered.**
  Root cause of the tier-2 gap. The seven registered names are exactly:
  `day_totals`, `division_breakdown`, `variance_analysis`, `top_movers`,
  `groupby_aggregate`, `pivot`, `latest_vs_baseline`.
- ~~`SectionSpec.transform`~~ / ~~`SectionSpec.transformer`~~ — no such field;
  `SectionSpec` is `extra="forbid"`.
- ~~`SectionDescriptor.layout`~~ — does not exist yet (Module 7 adds it);
  `extra="forbid"` means it must be declared, not passed through.
- ~~`SectionDescriptor.mode == "a2ui"`~~ / ~~`"component"`~~ — `mode` is
  `Literal["jinja", "data-splice"]` only. **Do not add a mode**; the A2UI path
  is expressed via `layout`, not via `mode`.
- ~~`InfographicRecipe.narrative`~~ / ~~`NarrativeSpec`~~ — do not exist yet (Module 3).
- ~~`RecipeRunner(narrator=...)`~~ — no such parameter today; ctor is
  `(store, dataset_manager, *, artifact_store=None, owner=None)`.
- ~~any LLM step inside `RecipeRunner`~~ — `run()` lines 245-254 contain no LLM call.
- ~~`parrot.bots.mixins.NarrativeMixin`~~ / ~~`Narrator`~~ — do not exist.
- ~~`InfographicAuthoringMixin._build_layout_spec`~~ — no such hook; the layout
  is hardcoded inline at `infographic_authoring.py:379-382`.
- ~~any `.docx` renderer or `python-docx` dependency in `parrot/`~~ — `.docx`
  appears only as an *input* format (loaders, `doc_converter`, notifications
  attachment allowlist). `executive_summary.build_docx` was never ported.
  **Out of scope (§1 Non-Goals).**
- ~~`executive_summary.headline_text` / `division_read` / `trend_clause` ported
  anywhere~~ — only the *math* reached `library.py`; all phrasing is unported.
- ~~importable `sdd.artifacts.executive_summary`~~ — `sdd/artifacts/*.py` are
  standalone reference artifacts, NOT package modules. Port, never import
  (`library.py:3-5`).
- ~~packaged skills inside `ai-parrot`~~ — zero `.md` skills ship in `packages/`;
  skills live as repo data in `.agent/skills/` (20+ present).
- ~~a reusable narrative skill that already covers this~~ —
  `.agent/skills/data-storytelling/SKILL.md` exists but is generic,
  auto-generated boilerplate about matplotlib/pandas presentation; it consumes no
  facts contract and is **not** a substitute.
- ~~`InfographicToolkit._maybe_enhance` as the narrative seam~~ — exists at
  `infographic_toolkit.py:1474` but is **deprecated** (FEAT-273 / G7, warning at
  1502-1509) and raw-HTML-only. Do not revive.
- ~~`FinanceReporter` using any transformer from `library.py`~~ — imports none
  today (verified zero occurrences).
- ~~a renderer change in `ai-parrot-visualizations`~~ — **verified unnecessary.**
  `Report` roots and per-section `text` already render. Touching the satellite
  is out of scope and an acceptance criterion forbids it.
- ~~`a2ui/models.py` change for optional bindings~~ — **verified unnecessary.**
  `_validate_bindings` tolerates sibling keys.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Cooperative mixins**: `NarrativeMixin` follows the
  `InfographicAuthoringMixin` / `ModelSwitchingMixin` pattern — mixed in
  **before** the agent class, pops its own kwargs, always chains
  `super().__init__()` / `super().configure()`.
- **Transformers are pure**: `(inputs, params) -> dict`. No clocks, no I/O, no
  randomness. `narrative_facts` must be byte-reproducible for a given input.
- **Registration by import side effect**: `library.py` is imported by
  `recipes/__init__.py`; do not add a dynamic-import registration path (G1).
- **Additive Pydantic changes only**: new fields are `Optional` with defaults;
  `schema_version` untouched. `SectionDescriptor`/`SectionSpec` are
  `extra="forbid"`, so every new field must be declared.
- **G8 one-way imports**: the `Narrator` protocol and the figure guard live under
  `parrot/tools/infographic_recipes/`, never under `parrot/outputs/a2ui/`.
  `outputs/a2ui/**` must keep importing no agents, no `DatasetManager`, no LLM
  clients (`builders.py:11-12`).
- **Degrade, never abort, on the probabilistic path**: mirror the established
  `_maybe_enhance` posture (`infographic_toolkit.py:1523-1548`) — log a WARNING
  and fall back to the deterministic output on any narrative failure.
- **Google-style docstrings + strict type hints**; `self.logger`, never `print`.
- **Money rounding**: 2dp for money metrics, matching `library.py`'s stated
  convention (lines 18-20).

### Known Risks / Gotchas

- **A confidently wrong characterisation of a correct number.** The figure guard
  catches invented *figures*, not a wrong *reading* of a real one. This is the
  residual risk the fence does not close; it is why the guard's fallback is
  "ship without prose" rather than "ship the prose anyway", and why review of the
  skill's phrasing rules matters. Accepted, documented, monitorable.
- **`_run_transforms_or_raise` is sync; the narrative step is async.** Do not
  fold narrative into the transform loop — insert a separate awaited step.
- **`_render_via_lowering` passes `{}` as data_model** (`interactive_html.py:306`).
  Binds inside a `Report` are resolved by the bake pass, not the renderer, so the
  optional-bind change **must** land in `baking.py` or optional narrative binds
  will still explode at render time.
- **`snapshot_col` mismatch.** The transformers default to `"snapshot"`
  (`library.py:13`); the table exposes `snapshot_date`
  (`finance_reporter.py:44`). Resolved: pass `snapshot_col="snapshot_date"`
  **explicitly in every step's params**. Forgetting it in one step yields a
  silent single-snapshot read (`day_totals` falls back to whole-frame totals),
  not an error — so the test asserting explicit params is load-bearing.
- **`variance_analysis` raises without a snapshot column** (`library.py:215-216`)
  — the only one of the four that hard-fails; ordering and params matter.
- **Two profiles need distinct recipe names.** `(name, owner)` collision raises
  unless `overwrite=True` (`infographic_authoring.py:321-330`).
- **`SKILL.md` token cap is enforced at discovery**, not at authoring time — a
  too-long body makes the skill silently *absent* (loader logs a warning and
  skips, never crashes), which would look like "narrative stopped working". Keep
  the body lean and put substance in assets.
- **FEAT-326's e2e example/tests will fail by design** once Module 8 lands. That
  is the accepted consequence of "replace"; rewriting them is in-scope work, not
  a regression to route around.
- **`ProvenanceDescriptor` must never record prose-generation code or the prompt**
  — it records datasets/params/mapping/snapshots only. Narrative adds a skill
  *name* at most.
- **Untracked repo files** (`docs/flex_program_report (39).html`,
  `docs/viba-troc-intelligence-system-architecture.pdf`) predate this work and
  are unrelated — do not stage them.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pandas` | existing | `narrative_facts` transformer; already allowed in `outputs/a2ui/recipes` per G8 |
| `jsonpointer` | existing (lazy, satellite) | `$bind` resolution in the bake pass (`baking.py:35-57`) |
| — | — | **No new third-party dependency.** The narrator uses the agent's existing `AbstractClient`; `python-docx` is explicitly NOT added. |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Rationale**: the independent clusters are small (one transformer, one skill
  directory, one additive model field) while the coupled core — recipe model +
  runner step + bake-pass optional binds + narrator protocol — is the bulk of
  the work and cannot be split without agents guessing at each other's
  contracts. Modules 2 and 3 both edit `_check_bind_drift_or_raise`; Modules 3,
  5 and 7 all depend on `NarrativeSpec`. One worktree with tasks in dependency
  order is cheaper than coordinating four worktrees around two shared files.
- **Parallelisable if ever needed** (not recommended for a first pass): Module 1
  (`library.py` only), Module 6 (`.agent/skills/`, data only, append-only so it
  cannot collide), and Module 2 (`baking.py` + one runner method) are mutually
  independent.
- **Ordering constraint**: Module 8 (`FinanceReporter` + e2e rewrite) must land
  **last**, after the layout and narrative contracts are final. Module 9 (docs)
  follows it.
- **Cross-feature dependencies**: none blocking. Touches FEAT-324
  (`outputs/a2ui/recipes/**`, `tools/infographic_recipes/**`) and FEAT-326
  (`bots/mixins/infographic_authoring.py`, `tools/infographic_sections.py`,
  `agents/finance_reporter.py`) — both merged. Shared-file risk concentrates on
  `outputs/a2ui/recipes/models.py` and `outputs/a2ui/baking.py`; run
  `/sdd-status` for in-flight A2UI/recipe specs before starting.
- **Worktree creation** (after task decomposition):
  ```bash
  git worktree add -b feat-420-finance-reporter-tier2-narrative \
    .claude/worktrees/feat-420-finance-reporter-tier2-narrative HEAD
  ```

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

**Resolved in brainstorm** (carried forward; each is reflected in the spec body):

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`,
  `base_branch: dev`. → frontmatter
- [x] How to reconcile deterministic narrative logic with a skill being LLM
  instructions — *Resolved in brainstorm*: deterministic `narrative_facts`
  transformer emits structured judgements; the skill teaches the LLM to render
  them as prose. → §2 Overview, Modules 1 & 6
- [x] Which render path closes tier 2 — *Resolved in brainstorm*: migrate to the
  A2UI component layout (not a `days` data-splice transformer). → §2 Overview,
  Module 8
- [x] Narrative behaviour on a scheduled, user-less refresh — *Resolved in
  brainstorm*: regenerate with the LLM under the system account, so prose never
  goes stale against refreshed numbers. → §4 `test_scheduled_refresh_with_narrator`,
  §6 (`system_account.py` unchanged)
- [x] Is a `.docx` executive summary in scope — *Resolved in brainstorm*: no.
  → §1 Non-Goals, §6 Does NOT Exist
- [x] How LLM prose enters a deterministic `data_model` — *Resolved in
  brainstorm*: a declarative `narrative` step (skill name + facts key + output
  key — a reference, never code) plus an optional injected `narrator`; absent
  narrator skips the step. → §2 Data Models, Module 3
- [x] Runner behaviour when `/narrative` is absent — *Resolved in brainstorm*:
  declared-optional binds; the drift check tolerates them and the renderer omits
  the section. Replay never fails for lack of an LLM. → Module 2, criterion G-E
- [x] How to generalise `publish_recipe`'s hardcoded `LayoutSpec` — *Resolved in
  brainstorm*: additive optional `layout` field on `SectionDescriptor`; absent
  means today's template-based behaviour. → Module 7
- [x] Fate of the existing data-splice descriptor and reference template —
  *Resolved in brainstorm*: **replace**. `FinanceReporter` becomes A2UI-only;
  FEAT-326's e2e example and tests are rewritten. The data-splice render mode
  itself stays. → §1 Non-Goals, Module 8, §7 Known Risks
- [x] Where the narrative skill lives and in what shape — *Resolved in
  brainstorm*: composite `.agent/skills/budget-narrative/` with `SKILL.md` +
  facts-contract and reference-phrasing assets — required anyway by the
  1000-token body cap. → Module 6
- [x] Who implements the narrator — *Resolved in brainstorm*: a `Narrator`
  protocol plus a reusable `NarrativeMixin` over `SkillRegistryMixin`;
  `FinanceReporter` composes it. → §2 New Public Interfaces, Modules 3 & 5
- [x] Where narrative renders in the A2UI layout — *Resolved in brainstorm*:
  both, as two publishable profiles — a `Report` root (executive summary) and an
  `Infographic` root (dashboard). → Module 8
- [x] Guardrail against LLM-fabricated figures — *Resolved in brainstorm*:
  post-generation numeric derivability check; any non-derivable figure discards
  the whole narrative and falls back to the no-narrative artifact. → Module 4,
  criterion G-H
- [x] Column-name mismatch (`snapshot` vs `snapshot_date`) — *Resolved in
  brainstorm*: explicit params. → Module 8, §7 Known Risks
- [x] Should `narrative_facts` be finance-specific or generic — *Resolved in
  brainstorm*: take the generic shape (facts derived from the
  `variance_analysis` + `top_movers` + `division_breakdown` outputs). → Module 1;
  feasibility verified at `runner.py:432-435,440,460-461`
- [x] Delivery / `RenderSpec.delivery` recipients — *Resolved in brainstorm*:
  configured per-deployment, not hardcoded. → §1 Non-Goals, Module 8

**Resolved by verification during spec research** (2026-08-07):

- [x] Does `a2ui/models._validate_bindings` reject a binding carrying a sibling
  `optional` key? — *Resolved by verification*: **No.** It validates only the
  pointer shape then returns (`models.py:102-109`), and `is_binding_expression`
  is a membership test (`models.py:90`). The sibling-key encoding is safe and
  `a2ui/models.py` needs no change. → Module 2, §6
- [x] Does the `interactive-html` renderer already render `Report` roots and
  per-section `text`? — *Resolved by verification*: **Yes, fully.** `Report`
  takes the lowering path (`interactive_html.py:269,292`), `Text` nodes render at
  `310-319`, Infographic section `text` at `445-447`, and
  `ReportComponent.lower` already omits absent `text`/`summary`
  (`report.py:105,124`). **No `ai-parrot-visualizations` work is needed** — this
  is now an acceptance criterion. → §6 Integration Points

**Still open:**

- [ ] Which LLM serves the narrator? `FinanceReporter.llm` is
  `"google:gemini-3.5-flash"` (`finance_reporter.py:60`) — adequate for prose,
  but the figure guard's tolerance should be calibrated to whatever model
  actually runs. Deferrable to implementation: `NarrativeMixin` uses the agent's
  configured client, so this is a tuning decision, not a design blocker —
  *Owner: Jesus*
- [ ] Should the figure guard's tolerance be configurable per recipe, or a fixed
  constant? A fixed constant is simpler and harder to weaken by accident;
  configurable helps if a division's magnitudes differ wildly. Decide during
  Module 4 — *Owner: implementing agent*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-07 | Jesus | Initial draft from `finance-reporter-tier2-narrative.brainstorm.md` (Option B); two brainstorm open questions closed by verification during research |
