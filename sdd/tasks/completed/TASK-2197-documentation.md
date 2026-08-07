# TASK-2197: Documentation — layout field, narrative step, optional binds

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2186, TASK-2187, TASK-2188, TASK-2189, TASK-2190, TASK-2191, TASK-2192, TASK-2193, TASK-2194, TASK-2195, TASK-2196
**Assigned-to**: unassigned

---

## Context

Implements **Module 9** of the spec, and satisfies the acceptance criterion
"Documentation updated in `docs/`".

Two existing documents make claims this feature invalidates:

- `docs/toolkits/infographic_authoring.md` states *"The default programmatic build
  shapes each section's declared datasets/columns per `SectionSpec.shape`;
  override `_build_section_payload` ... for richer transformations"* — after
  FEAT-420 there is a **declarative** alternative (`SectionDescriptor.layout`) and
  the canonical example agent no longer overrides that hook at all.
- `docs/outputs/infographic-recipes.md` documents the recipe schema and the
  `budget-variance-daily.yaml` walkthrough line by line, neither of which mention
  the `narrative` block, optional bindings, or narrator injection.

This task also documents the one thing a reader most needs and cannot infer: the
**determinism boundary** — which parts of a rendered artifact are guaranteed and
which are best-effort prose, and what happens when the LLM is unavailable.

---

## Scope

Update `docs/toolkits/infographic_authoring.md`:
- Document `SectionDescriptor.layout` (`LayoutSpec`): present → used verbatim by
  `publish_recipe`; absent → the legacy template-based behaviour.
- Document `SectionDescriptor.narrative` (`NarrativeSpec`).
- Correct the "override `_build_section_payload`" framing to present the
  declarative layout as the first-class option for the A2UI path.
- Update the tier-2 section: a descriptor whose section names match registered
  transformers now yields a saved recipe rather than a `GapReport`, and explain
  that section **names** are the resolution key.
- Note that `FinanceReporter` is now A2UI-only and no longer demonstrates
  data-splice (while the render mode itself remains supported).

Update `docs/outputs/infographic-recipes.md`:
- Document the top-level `narrative:` block and that it stores a **skill name,
  never code** (G1), with `schema_version` still `1`.
- Document narrator injection: `RecipeRunner(..., narrator=...)`, and that
  `run_scheduled_refresh` needs no change because it takes a runner instance.
- Document **optional bindings** (`{"$bind": ..., "optional": true}`) and the
  degrade-not-fail contract.
- Document the figure guard: all-or-nothing, and its stated limitation (it catches
  invented figures, not mis-characterisations).
- Update the `budget-variance-daily.yaml` walkthrough to match TASK-2195's edits.
- Document the `snapshot_col` gotcha: the transformers default to `"snapshot"`,
  `troc.finance_projection` exposes `snapshot_date`, and a missing param fails
  **silently** into whole-frame totals.

Add a short **"Determinism boundary"** subsection (one place, linked from the
other) stating plainly: every number traces to a registered transformer; prose is
best-effort; no narrator or a guard rejection means facts-without-prose, never a
failed run.

**NOT in scope**:
- Any code change. If a doc claim cannot be made true, the bug belongs to the
  owning module's task — record it, do not "fix" it in prose.
- Writing the skill's own content (TASK-2191 owns `SKILL.md` and its assets).
- A migration guide for external consumers — `FinanceReporter` is an example
  agent, not public API.
- Rewriting `docs/api/infographic_render.md` unless a statement in it became false.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/toolkits/infographic_authoring.md` | MODIFY | `layout` + `narrative` descriptor fields; corrected tier-1/tier-2 framing |
| `docs/outputs/infographic-recipes.md` | MODIFY | `narrative:` block, narrator injection, optional binds, figure guard, updated YAML walkthrough, `snapshot_col` gotcha |

---

## Codebase Contract (Anti-Hallucination)

> Documentation must describe **what shipped**, not what the spec proposed. Read
> the implementations and the dependency tasks' Completion Notes before writing.

### Verified Imports (to quote in docs)

```python
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec
from parrot.tools.infographic_recipes.narrator import Narrator
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.bots.mixins import NarrativeMixin
from parrot.auth.system_account import run_scheduled_refresh
```

### Existing Signatures to Use

```python
# Shapes to document (confirm each against the shipped code first):
class NarrativeSpec(BaseModel):        # outputs/a2ui/recipes/models.py (TASK-2188)
    skill: str; facts_key: str; output_key: str = "narrative"
class InfographicRecipe(BaseModel):
    schema_version: int = 1                        # line 184 — UNCHANGED, say so
    narrative: Optional[NarrativeSpec] = None      # TASK-2188
    section_descriptor: Optional[SectionDescriptor] = None   # line 196
class SectionDescriptor(BaseModel):    # tools/infographic_sections.py
    model_config = ConfigDict(extra="forbid")
    mode: Literal["jinja", "data-splice"]          # UNCHANGED — layout is not a mode
    layout: Optional[LayoutSpec] = None            # TASK-2193
    narrative: Optional[NarrativeSpec] = None      # TASK-2193
class RecipeRunner:
    def __init__(self, store, dataset_manager, *, artifact_store=None,
                 owner=None, narrator=None) -> None: ...     # TASK-2189
@runtime_checkable
class Narrator(Protocol):
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]: ...
```

```markdown
<!-- docs/toolkits/infographic_authoring.md — THE CLAIM TO CORRECT (verified present): -->
"The default programmatic build shapes each section's declared datasets/columns
per `SectionSpec.shape`; override `_build_section_payload` (or drive the agent's
pandas REPL tools conversationally) for richer transformations."

<!-- Also verify/update these existing statements: -->
- the tier-2 section describing "Partial coverage -> returns a GapReport"
  (still true, but the reader needs to know how to ACHIEVE full coverage:
   section names must match registered transformer names)
- "Templates for this mode are registered via `template_dirs`" (still true for
  data-splice; note it no longer applies to FinanceReporter's profiles)
- the scheduled-refresh section (system account) — extend it with the narrator
```

```
# Facts to state precisely (all verified during spec research):
- section->transformer resolution key: the section NAME, normalised
  (infographic_authoring.py:336, _transformer_name at 394-397)
- registered transformers: day_totals, division_breakdown, variance_analysis,
  top_movers, groupby_aggregate, pivot, latest_vs_baseline, narrative_facts
- descriptor.params is shared by ALL generated TransformSteps
  (infographic_authoring.py:352)
- snapshot_col default "snapshot" (library.py:13) vs snapshot_date
  (finance_reporter.py:44); variance_analysis RAISES without the column
  (library.py:215-216), the other three degrade silently
- Report/Infographic already render per-section `text`; absent text/summary is
  omitted (report.py:105,124; interactive_html.py:445-447) -> no renderer work
- skill bodies are capped at 1000 cl100k_base tokens
  (skills/models.py:74-82, parsers.py:93) -> composite skills with assets
- an over-cap or unparseable skill is logged and SKIPPED, so narrative silently
  disappears rather than erroring
```

### Does NOT Exist

- ~~a `days` transformer~~ — never registered; do not document one.
- ~~`SectionDescriptor.mode == "a2ui"`~~ — the A2UI path is selected by `layout`,
  not by a mode value. Do not imply otherwise.
- ~~`InfographicAuthoringMixin._build_layout_spec`~~ — the descriptor field was
  chosen instead; do not document a hook.
- ~~`.docx` output / `python-docx`~~ — explicitly out of scope (spec §1
  Non-Goals). Do not promise it, and if any doc implies the executive summary is
  a Word document, correct it.
- ~~`_maybe_enhance` as the narrative mechanism~~ — deprecated (FEAT-273) and
  raw-HTML-only. Do not present it as related.
- ~~`NarrativeSpec` carrying a prompt, template, or model~~ — it does not, by
  design (G1 + provider-agnostic). Say so explicitly.
- ~~a guarantee that the narrative is deterministic or reproducible~~ — it is
  not. Do not claim byte-identical replay for prose; only the data is deterministic.
- ~~any change to `ai-parrot-visualizations`~~ — verified unnecessary; do not
  document a renderer upgrade.

---

## Implementation Notes

### Key Constraints

- **Read the shipped code, not the spec.** Several implementation details were
  left to the implementing agents (the circular-import approach in TASK-2193, the
  LLM seam in TASK-2192, the descriptor input design in TASK-2194). Their
  Completion Notes are authoritative. Documenting the spec's draft shape where it
  diverged is the main failure mode of this task.
- **Be honest about the limitation.** The figure guard catches invented figures,
  not confident mis-characterisations of correct ones. The spec accepts this
  explicitly (§7 Known Risks); the docs must too, without burying it.
- Keep the existing house style of both documents (they use `---` section rules,
  fenced examples, and a "See also" tail).
- Every code example must be copy-pasteable and match a real signature.
- Where a behaviour is a *gotcha* rather than a feature (the `snapshot_col`
  silent fallback, the skipped over-cap skill), put it under an explicit
  "Gotchas" heading — a reader scanning for pitfalls should find them without
  reading the whole page.
- Cross-link rather than duplicate: the determinism-boundary explanation lives in
  one document and is linked from the other.

### References in Codebase

- `docs/toolkits/infographic_authoring.md` — the FEAT-326 authoring doc to update
- `docs/outputs/infographic-recipes.md` — the FEAT-324 recipes doc to update
- `docs/migration/feat-273-a2ui-deprecations.md` — the deprecation note to
  reference when explaining why narrative is *not* the enhance lane
- `examples/infographic_recipes/budget-variance-daily.yaml` — must match the
  walkthrough after TASK-2195
- All eleven dependency tasks' Completion Notes in `sdd/tasks/completed/`

---

## Acceptance Criteria

- [ ] `SectionDescriptor.layout` is documented with both branches (present → verbatim; absent → legacy template `LayoutSpec`)
- [ ] `SectionDescriptor.narrative` is documented
- [ ] The "override `_build_section_payload` for richer transformations" claim is corrected
- [ ] Tier-2 docs explain that the section **name** is the transformer-resolution key, and how to achieve full coverage
- [ ] The top-level `narrative:` recipe block is documented, stating it holds a skill **name, never code**
- [ ] `schema_version` is documented as still `1` (additive change)
- [ ] Narrator injection via `RecipeRunner(..., narrator=...)` is documented
- [ ] It is stated that `run_scheduled_refresh` needs no change (takes a runner instance)
- [ ] Optional bindings (`{"$bind": ..., "optional": true}`) are documented with the degrade-not-fail contract
- [ ] The figure guard is documented, **including** its stated limitation
- [ ] A "Determinism boundary" subsection exists and is cross-linked from the other document
- [ ] The `snapshot_col` gotcha is documented, including that three of four transformers fail **silently**
- [ ] The 1000-token skill cap and the silent-skip failure mode are documented
- [ ] It is stated that no `ai-parrot-visualizations` change was needed
- [ ] No doc claims `.docx` output, a `days` transformer, an `a2ui` mode, or deterministic prose
- [ ] The `budget-variance-daily.yaml` walkthrough matches the file as TASK-2195 left it
- [ ] Every code example matches a real, current signature (spot-checked against the tree)
- [ ] Markdown lints/renders cleanly; internal links resolve

---

## Test Specification

Documentation has no automated tests. Verification is by review:

1. **Signature spot-check** — for each code example, `grep` the referenced symbol
   and confirm the signature matches.
2. **Link check** — every relative link in the two changed files resolves.
3. **YAML walkthrough check** — read the walkthrough side by side with
   `examples/infographic_recipes/budget-variance-daily.yaml`; every referenced
   line/block exists.
4. **Anti-claim check** — `grep -i` the two documents for `docx`, `days`
   transformer, `mode: a2ui`, and any phrasing promising reproducible prose;
   confirm none appear except as an explicit non-goal.

Optionally add a lightweight docs test if the repo has a precedent for one
(check for an existing docs-link or example-parity test before creating a new pattern).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above in full — §1 Non-Goals and §7 Known
   Risks contain the statements the docs must faithfully reproduce
2. **Check dependencies** — all eleven prior tasks must be in
   `sdd/tasks/completed/`. **Read every one of their Completion Notes** before
   writing: they record where implementation diverged from the spec's draft.
3. **Verify the Codebase Contract** — spot-check each signature you intend to
   quote against the shipped code
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Write** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met, including the anti-claim check
7. **Move this file** to `sdd/tasks/completed/TASK-2197-documentation.md`
8. **Update index** → `"done"`, and set the index's `completed_at`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-07
**Notes**: Updated both documents per scope.

`docs/toolkits/infographic_authoring.md`:
- Added a top-of-doc pointer to the new narrative layer and the
  determinism-boundary contract.
- Added a `### layout and narrative (FEAT-420, both optional)` subsection
  under "The section descriptor contract" documenting `SectionDescriptor
  .layout`/`.narrative` with a copy-pasteable example, both branches of
  `layout` (present → verbatim; absent → legacy template `LayoutSpec`),
  and `narrative`'s pass-through-unchanged behaviour.
- Corrected the "override `_build_section_payload`" claim: scoped it
  explicitly to the tier-1/data-splice path and added a paragraph naming
  `SectionDescriptor.layout` as the first-class declarative alternative
  for the tier-2/A2UI path.
- Extended "Tier 2 — publication": explained that "full coverage" is a
  per-section check keyed on the section's normalised `name`
  (`re.sub(r"\W+", "_", name).strip("_")`), that there is no partial
  save (one unmapped section anywhere downgrades the whole publish to a
  `GapReport`), and how to reach full coverage. Documented that
  `descriptor.layout`/`.narrative` are carried through unchanged on a
  full-coverage publish, and the `data_sources` exclusion for aliases
  that are actually prior transform steps' `output_key`s (TASK-2196's
  bugfix).
- Added a "Reference implementation" paragraph naming
  `agents/finance_reporter.py`'s `FinanceReporter` and stating it is now
  A2UI-only (no longer demonstrates tier-1/data-splice), while the
  data-splice render mode itself remains fully supported.
- Extended "Scheduled refresh — the system account" with a paragraph
  confirming `run_scheduled_refresh` needs no change for narration (it
  takes a `RecipeRunner` instance; injection happens once at
  construction).
- Extended "See also" with a cross-link to
  `docs/outputs/infographic-recipes.md` §6 and the FEAT-420 spec path.

`docs/outputs/infographic-recipes.md`:
- Concepts (§1): added a `narrative` bullet to "A recipe is pure data";
  extended the transformers table to eight rows (`narrative_facts`) with
  a note on the prior-step-output_key columns-gate exemption.
- Walkthrough (§2): inserted the `narrative_facts` transform block, the
  `text: {$bind: "/narrative", optional: true}` layout example, and the
  top-level `narrative:` block, each annotated in place, matching
  `examples/infographic_recipes/budget-variance-daily.yaml` exactly
  (verified line-by-line against the file as TASK-2195 left it).
- §5 (`RecipeRunError`): documented that an `optional: true` pointer
  never raises at `stage="layout"`, and that `dry_run` additionally
  treats `narrative.output_key` as a valid bindable key.
- Added new `## 6. Narrative (FEAT-420)` section (renumbering the old
  §6/§7 to §7 Migration / §8 Testing) containing: a **Determinism
  boundary** blockquote (numbers always deterministic, prose always
  best-effort, never blocking a replay); the `narrative` block
  (skill/facts_key/output_key, `schema_version` stays `1`); narrator
  injection (`RecipeRunner(..., narrator=...)`, the `Narrator` protocol,
  `NarrativeMixin`, and that `run_scheduled_refresh` needs no code
  change); optional bindings (baking + drift-check degrade-not-fail
  behaviour, opt-in per pointer); the figure guard (all-or-nothing) and
  its stated limitation (invented figures vs. mis-characterised correct
  ones — spec §7 Known Risks, not glossed over); skill discovery and the
  1000-token cap with the silent-skip gotcha; the `snapshot_col` gotcha
  (three of four finance transformers degrade silently,
  `variance_analysis` raises); and a note that no
  `ai-parrot-visualizations` change was needed.

Verification performed (per the task's Test Specification):
1. **Signature spot-check** — `RecipeRunner.__init__`, `Narrator.narrate`,
   `NarrativeSpec`, `run_scheduled_refresh` all grep-verified against the
   shipped code; every quoted signature matches exactly.
2. **Link check** — the two documents' only relative links both target
   `docs/toolkits/infographic_toolkit.md`, which exists; the two spec
   paths referenced also exist.
3. **YAML walkthrough check** — every walkthrough block reproduced
   verbatim from `examples/infographic_recipes/budget-variance-daily.yaml`
   (TASK-2195's final version); confirmed line-by-line, no drift.
4. **Anti-claim check** — `grep -i` for `docx`, a `"days"` transformer
   claim, an `a2ui` render *mode*, and deterministic-prose phrasing
   across both files: no violations. (One pre-existing, out-of-scope
   `SectionSpec(name="days", ...)` example remains in the tier-1
   descriptor illustration — an arbitrary section *name* for a
   `mode="data-splice"` example, not a claim that a `"days"` transformer
   is registered; left untouched since it predates FEAT-420 and is not
   part of this task's scope.)
5. Code-fence balance verified even in both files (16 / 34 fences).

**Divergences from the spec that the docs had to reflect** (from the
dependency tasks' Completion Notes):
- TASK-2189's `RecipeRunError.stage` Literal had no `"narrative"` member
  (the spec's draft implied one); documented `stage="layout"` as the
  actual home for narrative-adjacent errors, plus `dry_run`'s separate
  `narrative.output_key` bindability check (TASK-2195's fix).
- TASK-2196 discovered and fixed a `publish_recipe` bug where a
  section's `datasets` naming a prior transform step's `output_key`
  (the `narrative_facts` shape) produced a bogus `DataSourceSpec`;
  documented the resulting exclusion rule directly, since it is now
  load-bearing behaviour a reader needs to know about.
- TASK-2194/2195 removed `FinanceReporter`'s tier-1 data-splice
  demonstration entirely (previously its main documented example);
  documented this as an explicit "now A2UI-only" note rather than
  silently updating the reference without comment.
- TASK-2195 discovered `InfographicToolkit`'s `TemplateEngine` eagerly
  validates `template_dirs` at construction; not separately documented
  here since it doesn't change any statement in either file (the docs
  never claimed `template_dirs` was optional at construction time).

**Deviations from spec**: none.
