---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: FinanceReporter Tier-2 + Narrative Skill

**Date**: 2026-08-07
**Author**: Jesus
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

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
   of it — `library.py:198-200` states the transformers carry the math
   "WITHOUT any narrative sentence generation, which is a renderer/layout
   concern". That concern was never assigned to anyone. Today the platform can
   compute *that* EBITDA variance worsened, but cannot *say* so.

**Who is affected**: finance/ops consumers of the daily budget-variance report
(they currently get numbers with no interpretation, or fall back to the
standalone `daily_report.py` script running on someone's Windows box against
a OneDrive-synced folder); and every future reporting agent, which today has no
sanctioned pattern for narrative output.

**Why now**: the deterministic replay machinery (FEAT-324) and the authoring
machinery (FEAT-326) are both merged and stable. The remaining work is
connective, and the longer `FinanceReporter` stands as the canonical example
while bypassing the transformer library, the more it teaches the wrong pattern.

## Constraints & Requirements

- **G1 (never stored/executed code) is inviolable.** Recipes reference
  transformations by *registered name*. Any narrative mechanism must store a
  *reference* (a skill name), never code, never a prompt blob that behaves as
  code.
- **G3/G7 determinism of the data.** Every number in a rendered artifact must
  trace to a registered transformer over registered datasets. LLM output may
  add *prose*, never *data*.
- **A pure replay must never fail for lack of an LLM.** `RecipeRunner.run()`
  (`runner.py:208`) is the single path behind chat, REST and scheduler (G6). A
  scheduled refresh with no narrator configured must still deliver the artifact.
- **G8 one-way imports.** `parrot/outputs/a2ui/**` must not import agents,
  `DatasetManager`, or LLM clients (`builders.py:11-12`). The narrator contract
  therefore cannot live inside `outputs/a2ui/`; `parrot/tools/infographic_recipes/`
  is the sanctioned side (it already imports `DatasetManager` for exactly this
  reason — `runner.py` module docstring).
- **Skill bodies are hard-capped at 1000 tokens.**
  `SkillDefinition.MAX_TOKENS = 1000` (`skills/models.py:74`) with a
  `field_validator` that *raises* above it (`skills/models.py:76-82`). A skill
  carrying a facts contract plus reference phrasing cannot be a single file.
- **Additive schema changes only.** `InfographicRecipe.schema_version` must stay
  `1` and pre-existing recipes must keep loading — the precedent set when
  `section_descriptor` was added (`models.py:196`).
- **No fabricated figures.** A financial report with an invented number is the
  one failure mode that is categorically unacceptable, so LLM prose needs a
  mechanical guard, not just prompt discipline.
- **`sdd/artifacts/*.py` are reference artifacts, not importable modules.** Their
  math may be ported (as Module 3 did) but never imported (`library.py:3-5`).

---

## Options Explored

### Option A: Fully deterministic — narrative as a template transformer

Port `headline_text` / `division_read` / `trend_clause` literally into a new
registered transformer (e.g. `narrative_text`) that emits finished sentences by
the same if/elif branching as the reference artifact. The "skill" becomes
documentation only — a `.md` describing the vocabulary for humans, never loaded
by an LLM. Tier 2 closes with a plain transformer chain and zero new machinery.

✅ **Pros:**
- Zero new architecture: one more `@infographic_transformer`, nothing else.
- Byte-identical replay, trivially testable, no LLM anywhere.
- Cannot fabricate figures — every sentence is code the reviewer read.
- G1/G3/G7 untouched; scheduled refresh needs nothing new.

❌ **Cons:**
- Not what was asked: the narrative is not a skill, and nothing about it is
  adaptable — new data shapes need a code change and a release.
- The prose is as rigid as the original: three canned sentence templates that
  read like a form letter and cannot respond to an unusual month.
- Re-introduces exactly the "narrative as hardcoded Python" that FEAT-324
  deliberately declined to port as a renderer concern.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pandas` | already a transformer-layer dep | allowed in `outputs/a2ui/recipes` per G8 |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/recipes/library.py` — register alongside the existing seven
- `sdd/artifacts/executive_summary.py:159-269` — the phrasing logic to port

---

### Option B: Deterministic facts + skill-guided injected narrator

Split the concern in two, along the determinism boundary:

- A new registered transformer **`narrative_facts`** deterministically derives
  every *judgement* the prose needs — direction flags, the top driver, urgency,
  per-division reads (`offset_by` / `spread` / `concentrated`) — as structured
  data in the `data_model`. This is a faithful port of the *decisions* inside
  `headline_text`/`division_read`/`trend_clause`, minus the English.
- A composite **skill** (`.agent/skills/budget-narrative/`) teaches an LLM how
  to turn those facts into prose, with the facts contract and the reference
  phrasing as *assets* (served by `read_skill_asset`) so `SKILL.md` stays under
  the 1000-token cap.
- The recipe declares narrative **declaratively** (`narrative: {skill, facts_key,
  output_key}`) — a name, not code. `RecipeRunner` accepts an optional injected
  `narrator`; with none, the step is skipped and the layout's narrative binds
  are declared `optional`, so a pure replay degrades to facts-without-prose
  instead of failing.
- A post-generation **figure guard** extracts numbers from the prose and rejects
  the whole narrative if any is not derivable from the facts, falling back to the
  no-narrative artifact.

Tier 2 closes by giving `SectionDescriptor` an optional `layout` field so
`publish_recipe` can emit a real component tree instead of its hardcoded
template-based `LayoutSpec`. Two publishable profiles: a `Report` layout (the
executive-summary deliverable) and an `Infographic` layout (the dashboard).

✅ **Pros:**
- Data stays provably deterministic; only prose is probabilistic, and the guard
  bounds even that.
- The narrative *is* a real skill — editable by a non-engineer, versioned as
  data, discovered by the existing `SkillsDirectoryLoader`, with zero code
  change to adapt tone or add a division-specific read.
- Reuses all four finance transformers already ported and idle.
- `Report` and `Infographic` catalog components already exist and already accept
  per-section `text`, so no new render code.
- Replay never regresses: no narrator → same artifact as today, plus facts.
- Establishes a reusable pattern (`Narrator` protocol + `NarrativeMixin`) rather
  than a one-off.

❌ **Cons:**
- The largest surface area of the three: touches the recipe model, the runner,
  the authoring mixin, the descriptor, the catalog-layout path and the skills
  tree.
- Introduces a genuinely non-deterministic component into a subsystem whose
  headline guarantee is determinism — defensible only because it is fenced
  (facts deterministic, prose guarded, replay degrades), and that fence is
  itself new code that must be right.
- The figure guard is a heuristic. It can only catch numbers, not a confidently
  wrong *characterisation* of a correct number.
- Two publishable profiles doubles the layout definition to maintain.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pandas` | `narrative_facts` transformer | already a dep of the recipes layer |
| `jsonpointer` | `$bind` resolution in the bake pass | already a dep, lazily imported (`baking.py:35-57`), satellite-only |
| — | no new third-party dependency | narrator uses the existing `AbstractClient` path via the agent |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/recipes/library.py:82-315` — `_day_totals_for`, `variance_analysis`, `top_movers`, `division_breakdown` supply every input `narrative_facts` needs
- `parrot/outputs/a2ui/catalog/components/report.py:31-63` — `REPORT_SCHEMA` already has `summary` + `sections[].text`
- `parrot/outputs/a2ui/catalog/components/infographic.py` — `INFOGRAPHIC_SCHEMA` already has per-section `text`
- `parrot/tools/infographic_recipes/runner.py:512-535` — `_assemble_envelope_or_raise` already routes non-`Infographic` layouts through `build_surface`, so a `Report` root needs **no runner change**
- `parrot/skills/loader.py`, `parrot/skills/tools.py:371-533` — composite discovery + `load_skill` / `read_skill_asset`
- `parrot/auth/system_account.py:129` — `run_scheduled_refresh` takes a runner instance, so an injected narrator needs no change there
- `examples/infographic_recipes/budget-variance-daily.yaml` — the layout to extend

---

### Option C: Narrative outside the recipe — two artifacts

Keep the recipe 100% deterministic and unchanged. `FinanceReporter` runs the
recipe for the visual artifact, then separately loads the narrative skill and
produces prose as its own second artifact (or chat message). No new recipe
field, no runner change, no optional binds.

✅ **Pros:**
- FEAT-324's determinism guarantee is not merely fenced, it is untouched.
- Smallest blast radius: no changes to `models.py`, `runner.py`, or `baking.py`.
- Mirrors the original deliverable shape most literally — `daily_report.py` also
  emailed two separate files.
- Narrative failure can never break the dashboard, structurally.

❌ **Cons:**
- The narrative is invisible to the recipe contract: `infographic_get_recipe_contract`
  cannot report it, `dry_run` cannot validate it, and a scheduled refresh has no
  declarative way to request it.
- Scheduling regresses: the scheduler triggers `RecipeRunner.run()`, so a
  narrative-bearing scheduled report needs a *second* orchestration path outside
  the "one runner behind all three triggers" rule (G6).
- Two artifacts means two deliveries, two persistence calls, and a recipient who
  must correlate them.
- Tier-2 gap (1) still needs the `layout`/transformer work anyway, so this only
  avoids the narrative-integration cost, not the tier-2 cost.

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:**
- `parrot/skills/mixin.py` — `SkillRegistryMixin.get_skill_context` for skill loading
- `parrot/tools/infographic_recipes/runner.py` — used as-is, unmodified

---

### Option D (unconventional): Executable skills — skill assets *are* the transformer

Let a composite skill ship its transform as a Python asset. Discovery imports
the asset, which registers itself via `@infographic_transformer`, so a
non-engineer can add a whole new analysis + narrative by dropping a directory
into `.agent/skills/`. Reports become fully data-defined; the platform ships no
domain code at all.

✅ **Pros:**
- Radically extensible: a new report is a folder, not a release.
- Collapses the facts/prose split — one artifact defines both, no contract drift
  between a transformer and the skill that documents it.
- Would make the transformer library a bootstrap vocabulary rather than a
  bottleneck.

❌ **Cons:**
- **Directly violates G1.** `TransformerRegistry` deliberately refuses dynamic
  import of user-supplied dotted paths precisely to keep this hole closed
  (`transformers.py:72-79`: "there is no dynamic import of user-supplied dotted
  paths, which would reopen the G1 'stored code' hole").
- Arbitrary code execution from a data directory — a skills folder becomes an
  RCE surface, and `read_skill_asset`'s sandboxing exists to prevent exactly the
  adjacent class of problem.
- Provenance becomes unauditable: `ProvenanceDescriptor` promises never to record
  the code used to build data, which only means anything if that code is
  reviewed and versioned in-tree.
- Recorded here for completeness and to make the rejection explicit rather than
  implicit — it is the obvious "make it flexible" instinct and must be closed off
  by name so no downstream agent reaches for it.

📊 **Effort:** Medium (to build) / unbounded (to secure)

🔗 **Existing Code to Reuse:**
- n/a — rejected

---

## Recommendation

**Option B** is recommended.

Option A is honest about determinism but does not deliver the feature: a canned
sentence generator is not a skill, and it re-lands the rigidity that FEAT-324
explicitly pushed out of the transformer layer. Option D is the opposite failure
— it delivers the flexibility by demolishing the guarantee the subsystem is built
on, and `transformers.py:72-79` already refuses it in writing.

Option C is the serious alternative, and its determinism argument is real: it is
the only option where FEAT-324's core promise needs no fence at all. It loses on
G6. The single-runner rule is what makes chat, REST and scheduled refresh
behave identically, and a narrative that only exists outside the runner means the
scheduled daily report — the actual production use case, the thing
`daily_report.py` was doing on a Task Scheduler — is the one trigger that cannot
produce the narrative without a second, parallel orchestration path. Building
that path is not obviously cheaper than declaring one optional step, and it
permanently splits the delivery story.

What Option B trades away, stated plainly: it admits a non-deterministic
component into a deterministic subsystem. That is acceptable **only** because
the fence is structural rather than procedural — facts are computed by a
registered transformer like everything else, prose can never become data, the
figure guard mechanically rejects invented numbers, and the absence of a narrator
degrades instead of failing. Each of those is a testable property, not a
convention someone must remember. The residual risk the fence does *not* cover
is a fluent mischaracterisation of a correct number; that is a review/monitoring
concern, and it is the reason the guard's fallback is "ship without prose" rather
than "ship the prose anyway".

The secondary win is that `Report` and `Infographic` already accept per-section
`text`, and `_assemble_envelope_or_raise` already routes non-`Infographic`
layouts through `build_surface` — so the two most visible parts of this feature
need no new rendering code at all.

---

## Feature Description

### User-Facing Behavior

**Interactive (tier 1).** A finance user asks `FinanceReporter` for the daily
budget variance. They get an A2UI artifact whose numbers come from
`troc.finance_projection` and whose prose reads like the original executive
summary — a bottom-line paragraph, a per-division read, named key drivers with
their trend, and a recommendation naming the largest single driver. The prose
adapts to the actual month: a month where both metrics improve reads differently
from one where they diverge.

**Publishing (tier 2).** The same descriptor can be published as a named recipe.
Two profiles are publishable: a **Report** profile (narrative-first — the
executive-summary deliverable) and an **Infographic** profile (visual-first — the
dashboard). Publication now succeeds instead of returning a `GapReport`.

**Scheduled refresh.** The recipe replays daily under the system account with
fresh data. With a narrator configured, the prose is regenerated against the new
numbers — never stale text over refreshed figures. With no narrator (or an LLM
outage), the artifact still ships: same layout, same numbers, narrative sections
omitted. The report never silently skips a day because of the narrative layer.

**Editing the voice.** Changing how the report reads is editing
`.agent/skills/budget-narrative/SKILL.md` — no code change, no release. The skill
is discoverable via `list_skill_commands` like every other skill in the tree.

### Internal Behavior

**Deterministic facts.** A new `narrative_facts` transformer consumes the same
`snapshots` frame the existing finance transformers use and emits structured
judgements: revenue state/direction, EBITDA direction, the top driver with a
derived urgency, and a per-division read *kind* (`on_track` / `spread` /
`concentrated` / `offset_by`, with the offsetting project named). It ports the
*branching* of `headline_text`/`division_read`/`trend_clause`, not their English.
Money values are rounded to 2dp like its siblings.

**Declarative narrative step.** `InfographicRecipe` gains an optional
`narrative` field naming a skill, the facts key to read, and the output key to
write. Additive — `schema_version` stays `1`, existing recipes load unchanged.
The step is visible to `infographic_get_recipe_contract` and checkable by
`dry_run`, which is precisely what Option C could not offer.

**Injected narrator.** A `Narrator` protocol (`async def narrate(facts, skill)`)
is defined on the `parrot/tools/infographic_recipes/` side of the G8 boundary.
`RecipeRunner.__init__` takes an optional keyword-only `narrator`; a new step
runs between the transform chain and the bind-drift check. `NarrativeMixin`
implements the protocol over `SkillRegistryMixin` — loads the skill body plus its
assets, calls the LLM, returns prose. `FinanceReporter` composes it. Because
`run_scheduled_refresh` receives a runner *instance*, the scheduled path needs no
change: whoever builds the runner decides whether it can narrate.

**Optional binds.** Narrative binds carry a sibling `optional` flag.
`is_binding_expression` is `BINDING_KEY in value` (`models.py:90`), so an extra
key does not break binding detection — the flag is additive by construction. Two
places learn to honour it: the runner's bind-drift check (tolerate a missing
top-level key) and the bake pass's `_resolve_value` (yield absent instead of
`BakeError`). The renderer omits a section whose text resolved to nothing.

**Figure guard.** After generation, numbers are extracted from the prose and
checked for derivability from the facts. Any non-derivable figure discards the
*entire* narrative and falls back to the no-narrative artifact — the same
degraded state as "no narrator", so there is one fallback path, not two.

**Layout generalisation.** `SectionDescriptor` gains an optional `layout`
(`LayoutSpec`). When present, `publish_recipe` uses it verbatim; when absent it
keeps today's template-based `LayoutSpec` (`infographic_authoring.py:379-382`),
so existing descriptors are unaffected.

**Migration.** `FinanceReporter`'s data-splice descriptor and its
`_build_section_payload` override are **replaced** by descriptors built on the
registered transformers. Consequence, accepted deliberately: FEAT-326's shipped
e2e example and tests assert the data-splice path for this agent and must be
rewritten. The data-splice *render mode* itself (TASK-1883) stays — only this
agent's use of it goes away.

### Edge Cases & Error Handling

- **No narrator injected** → narrative step skipped, optional binds unresolved,
  sections omitted, run succeeds. The baseline, not an error.
- **LLM call fails or times out** → same degraded artifact; logged as a warning,
  never fatal. Matches the established `_maybe_enhance` posture
  (`infographic_toolkit.py:1523-1548`: fall back to the deterministic skeleton).
- **Prose contains a non-derivable figure** → whole narrative discarded, warning
  logged with the offending figure, degraded artifact shipped.
- **Skill not found** in the registry → hard error at publish/dry-run time (a
  recipe naming a nonexistent skill is a broken recipe), warning-and-degrade at
  run time (so a skills-tree mishap does not stop the daily report).
- **Skill body exceeds 1000 tokens** → `SkillDefinition`'s validator rejects it at
  discovery (`skills/models.py:76-82`); this is why the facts contract and
  reference phrasing are assets, not body.
- **Single snapshot in the window** → `variance_analysis` already returns
  identical first/last totals with zero deltas (`library.py:200-203`);
  `narrative_facts` must emit `flat`/`held_steady` reads rather than claiming a
  trend. Direct analogue of the reference artifact's `n_days` handling.
- **A project new at the latest snapshot** → `top_movers` already yields
  `trend: null` (`library.py:302-306`); the narrative must say "new this period",
  mirroring `trend_clause`'s fallback (`executive_summary.py:269`).
- **No materially negative project** → recommendation degrades to "no single
  project stands out", as in `executive_summary.py:384`.
- **Division with zero budget** → guard division-by-zero as the reference does
  (`executive_summary.py:48`, preserved in `library.py:98`).
- **`optional` on a non-narrative bind** → allowed but pointless; it must not
  silently mask a genuine drift in a data bind, so the drift check should report
  optional-and-missing at INFO, not swallow it.
- **Both profiles published under one name** → `(name, owner)` collision requires
  `overwrite=True` (`infographic_authoring.py:321-330`); the two profiles need
  distinct recipe names.

---

## Capabilities

### New Capabilities
- `narrative-facts-transformer`: registered transformer deriving structured
  narrative judgements from budget-variance snapshots.
- `recipe-narrative-step`: additive declarative `narrative` field on
  `InfographicRecipe` plus the injected-`Narrator` step in `RecipeRunner`.
- `optional-data-bindings`: `optional` flag on `$bind` expressions, honoured by
  the runner's drift check and the bake pass.
- `narrative-skill`: composite `.agent/skills/budget-narrative/` skill with facts
  contract and reference phrasing as assets.
- `narrator-protocol`: `Narrator` protocol + reusable `NarrativeMixin` over
  `SkillRegistryMixin`.
- `narrative-figure-guard`: post-generation numeric derivability check with
  all-or-nothing fallback.
- `descriptor-layout-spec`: optional `layout` on `SectionDescriptor` so
  `publish_recipe` can emit a component-tree layout.

### Modified Capabilities
- `dataagent-infographic` (FEAT-326) — `FinanceReporter` migrates off data-splice
  to A2UI layouts; its e2e example and tests are rewritten.
- `infographic-builder` (FEAT-324) — recipe model, runner pipeline and bake pass
  gain the narrative step and optional binds.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/recipes/library.py` | extends | new `narrative_facts` transformer alongside the existing seven |
| `parrot/outputs/a2ui/recipes/models.py` | modifies | additive `narrative` field on `InfographicRecipe`; `schema_version` stays `1` |
| `parrot/tools/infographic_recipes/runner.py` | modifies | `narrator` ctor kwarg; new async step between `_run_transforms_or_raise` and `_check_bind_drift_or_raise`; drift check honours `optional` |
| `parrot/outputs/a2ui/baking.py` | modifies | `_resolve_value` yields absent instead of `BakeError` for optional binds |
| `parrot/tools/infographic_sections.py` | modifies | additive optional `layout: LayoutSpec` on `SectionDescriptor` (note `extra="forbid"`) |
| `parrot/bots/mixins/infographic_authoring.py` | modifies | `publish_recipe` honours `descriptor.layout` instead of always hardcoding the template `LayoutSpec` |
| `parrot/bots/mixins/` (new) | extends | `NarrativeMixin` + `Narrator` protocol placement (G8: protocol on the `tools/` side) |
| `.agent/skills/budget-narrative/` | new | composite skill + assets |
| `agents/finance_reporter.py` | modifies | drops the data-splice descriptor and `_build_section_payload` override; gains Report + Infographic descriptors |
| `examples/budget_variance_infographic.py` | modifies | runner updated to the A2UI path |
| `examples/infographic_recipes/budget-variance-daily.yaml` | modifies | gains the `narrative` step and optional narrative binds |
| `packages/ai-parrot/tests/integration/test_dataagent_infographic_e2e.py` | modifies | asserts data-splice for this agent; must be rewritten |
| `packages/ai-parrot/tests/unit/bots/test_publish_recipe.py` | modifies | covers the layout/GapReport behaviour being changed |
| `docs/toolkits/infographic_authoring.md` | modifies | documents the layout field + narrative |
| `docs/outputs/infographic-recipes.md` | modifies | documents the narrative step, optional binds, narrator injection |
| **Deployment** | new config | narrator requires LLM credentials under `PARROT_SYSTEM_ACCOUNT_ID` for scheduled narrative |
| **Breaking changes** | none at the API level | recipe schema additive; `FinanceReporter`'s own descriptor shape changes (example agent, not public API) |

---

## Code Context

### User-Provided Code

No code was pasted during discovery. The user pointed at three in-repo reference
files, all read and cited below: `sdd/artifacts/executive_summary.py`,
`sdd/artifacts/daily_report.py`, `sdd/artifacts/budget_variance_dashboard_Template.html`.

The reference narrative logic to be ported as *facts* (English stripped):

```python
# Source: sdd/artifacts/executive_summary.py:159-180 (headline_text)
rev_dir = "narrowing" if a["rev_pct_change"] > 0 else "widening" if a["rev_pct_change"] < 0 else "flat"
eb_dir = "improved" if a["ebitda_dollar_change"] > 0 else "worsened" if a["ebitda_dollar_change"] < 0 else "held steady"
rev_state = "behind" if lt["rev_variance"] < 0 else "ahead of"
# ... plus a three-way branch on the sign combination of the two changes

# Source: sdd/artifacts/executive_summary.py:183-201 (division_read)
# read kinds, in the order the reference decides them:
#   no read_worst + ebitda_variance >= 0  -> "broadly on track"
#   no read_worst + ebitda_variance <  0  -> "modest shortfall spread across"
#   read_worst    + ebitda_variance >= 0  -> "offset by <best positive project>"
#   read_worst    + ebitda_variance <  0  -> "<names> trailing forecast"

# Source: sdd/artifacts/executive_summary.py:142 (materiality threshold)
d["read_worst"] = [p for p in div_worst if p["ebitda_variance"] < -5000][:2]

# Source: sdd/artifacts/executive_summary.py:258-269 (trend_clause)
# prefers day-over-day when a 3-day window exists, else since-first-of-month,
# else "new this period"

# Source: sdd/artifacts/executive_summary.py:369-382 (recommendation urgency)
#   trend < 0 -> "still moving the wrong direction — immediate priority"
#   trend > 0 -> "improving, confirm whether the trend continues"
#   else      -> "warrants a direct check on timing vs structural"
```

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:194
class RecipeRunner:
    def __init__(
        self,
        store: AbstractRecipeStore,
        dataset_manager: DatasetManager,
        *,
        artifact_store: Any = None,   # line 199
        owner: Any = None,            # line 200
    ) -> None: ...                    # line 194

    async def run(                    # line 208
        self,
        name: str,
        *,
        params: dict[str, Any] | None = None,
        pctx: Any | None = None,
        recipe_owner: Optional[str] = None,
    ) -> RenderedArtifact: ...
    # pipeline body, lines 245-254:
    #   _load_recipe / _resolve_params_or_raise / _fetch_frames /
    #   _run_gate_or_raise / _run_transforms_or_raise (249) /
    #   _check_bind_drift_or_raise (250) / _assemble_envelope_or_raise (251) /
    #   _render_or_raise (252) / _deliver_best_effort (253)

    async def dry_run(self, recipe: InfographicRecipe) -> list[RecipeRunError]: ...  # line 256
    def _run_transforms_or_raise(self, recipe, frames, resolved_params) -> dict[str, Any]: ...  # line 448 (SYNC)
    def _check_bind_drift_or_raise(self, recipe, data_model) -> None: ...  # line 490
    def _assemble_envelope_or_raise(self, recipe, data_model): ...          # line 512
    async def _render_or_raise(self, recipe, envelope) -> RenderedArtifact: ...  # line 537
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class TransformStep(BaseModel):      # line 79
    transformer: str
    inputs: list[str] = Field(default_factory=list)      # line 93
    params: dict[str, Any] = Field(default_factory=dict) # line 94
    output_key: str

class LayoutSpec(BaseModel):         # line 98
    component: str
    properties: dict[str, Any] = Field(default_factory=dict)  # line 110

class RenderSpec(BaseModel):         # line 113
    profile: str = "interactive-html"                    # line 125
    theme: Optional[str] = None                          # line 126
    delivery: Optional[dict[str, Any]] = None            # line 127

class ScheduleSpec(BaseModel):       # line 130
    principal: str
    tenant_id: Optional[str] = None                      # line 150
    roles: list[str] = Field(default_factory=list)       # line 151

class InfographicRecipe(BaseModel):  # line 154
    schema_version: int = 1                              # line 184
    params: list[RecipeParam] = Field(default_factory=list)          # line 189
    data_sources: list[DataSourceSpec] = Field(default_factory=list) # line 190
    transforms: list[TransformStep] = Field(default_factory=list)    # line 191
    layout: LayoutSpec
    render: RenderSpec = Field(default_factory=RenderSpec)           # line 193
    schedule: Optional[ScheduleSpec] = None                          # line 194
    section_descriptor: Optional[SectionDescriptor] = None           # line 196  <-- additive precedent

class TransformerManifest(BaseModel):  # line 222
    requires_columns: dict[str, list[str]] = Field(default_factory=dict)  # line 236
    params_schema: dict[str, Any] = Field(default_factory=dict)            # line 237

class RecipeRunError(BaseModel):     # line 240
    transformer: Optional[str] = None            # line 256
    dataset: Optional[str] = None                # line 257
    missing_columns: list[str] = Field(default_factory=list)  # line 258
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
TransformerFunc = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

def infographic_transformer(name: str, ...) -> Callable: ...   # line 164 (decorator)
def validate_inputs(step: TransformStep, frames) -> list[RecipeRunError]: ...

class TransformerRegistry:
    def register(self, name, func, *, requires_columns=None, description="",
                 params_schema=None) -> RegisteredTransformer: ...
    def get(self, name) -> RegisteredTransformer: ...    # raises KeyError
    def manifest(self, name) -> TransformerManifest: ...
    def list(self) -> list[TransformerManifest]: ...

transformer_registry: TransformerRegistry  # module-level shared instance
# G1 note, lines 72-79: "there is no dynamic import of user-supplied dotted
# paths, which would reopen the G1 'stored code' hole"
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py
# All seven register by import side effect; recipes/__init__.py imports this module.
_MONEY_COLUMNS = ["rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"]  # line 39
def _day_totals_for(df) -> dict[str, Any]: ...                       # line 82
@infographic_transformer("day_totals", ...)          def day_totals(inputs, params)          # 105 / 120
@infographic_transformer("division_breakdown", ...)  def division_breakdown(inputs, params)  # 132 / 146
@infographic_transformer("variance_analysis", ...)   def variance_analysis(inputs, params)   # 191 / 209
@infographic_transformer("top_movers", ...)          def top_movers(inputs, params)          # 253 / 270
@infographic_transformer("groupby_aggregate", ...)   def groupby_aggregate(inputs, params)   # 318 / 333
@infographic_transformer("pivot", ...)               def pivot(inputs, params)               # 346 / 362
@infographic_transformer("latest_vs_baseline", ...)  def latest_vs_baseline(inputs, params)  # 375 / 389

# variance_analysis returns (lines 239-250):
#   first_snapshot, last_snapshot, first_totals, last_totals, rev_pct_change,
#   ebitda_dollar_change, rev_direction, ebitda_direction, rev_state, n_snapshots
# top_movers returns (line 315): {"worst": [...], "best": [...]}
#   each entry: {division, project, ebitda_variance, trend}  (trend None if new)
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                  component_id: str = "blk-000",
                  data_model: Optional[dict[str, Any]] = None) -> CreateSurface: ...  # line 44
def build_infographic(*, title: str, sections: Sequence[dict[str, Any]],
                      subtitle: Optional[str] = None, theme: Optional[str] = None,
                      surface_id: str = "infographic",
                      data_model: Optional[dict[str, Any]] = None) -> CreateSurface: ...  # line 151
# sections item shape (docstring, lines 162-163):
#   {"heading": ..., "text"?: ..., "components"?: [{"component": name, "properties": {...}}]}
def _binding(pointer) -> Optional[dict[str, str]]: ...  # line 40 -> {"$bind": pointer}
# G8, lines 11-12: imports only the a2ui core; never agents/DatasetManager/LLM clients
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py
BINDING_KEY = "$bind"                                          # line 50
def is_valid_pointer(pointer: str) -> bool: ...                # line 59
def is_binding_expression(value: Any) -> bool:                 # line 79
    return isinstance(value, dict) and BINDING_KEY in value    # line 90
    # <-- membership test only: a sibling "optional" key does NOT break detection
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
def _resolve_value(value: Any, data_model: dict[str, Any]) -> Any: ...  # line 60
    # raises BakeError on an unresolvable pointer (lines 78-81)
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]: ... # line 100
class BakeError(Exception): ...                                          # line 31
# jsonpointer imported lazily (lines 35-57) -> core-only installs can syntax-check only
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/report.py
REPORT_SCHEMA = {                       # line 31
  "properties": {
    "title": {...}, "metadata": {...}, "summary": {...},   # summary IS supported
    "sections": {"items": {"properties": {
        "heading": {...}, "text": {...}, "components": {...}},
        "required": ["heading"]}},
  },
  "required": ["title", "sections"],    # line 62
}
@register_component("Report")
class ReportComponent:
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree: ...
# Module docstring: "Report is a narrative, section-structured document"; display-only

# From .../catalog/components/infographic.py
INFOGRAPHIC_SCHEMA = {...}   # per-section "text": {"type": "string"} IS present
@register_component("Infographic")
class InfographicComponent:
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree: ...
```

```python
# From packages/ai-parrot/src/parrot/tools/infographic_sections.py
class SectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str; target: str
    datasets: List[str] = Field(default_factory=list)
    columns: Dict[str, List[str]] = Field(default_factory=dict)
    shape: Literal["records", "scalar", "mapping", "table"]
    hint: Optional[str] = None
    # NOTE: no transform/transformer field of any kind

class SectionDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")   # <-- adding `layout` must be an explicit field
    template: str
    mode: Literal["jinja", "data-splice"]       # <-- no "a2ui"/"component" value
    splice_marker_id: str = "report-data"
    sections: List[SectionSpec] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)

def validate_descriptor_datasets(descriptor, dataset_manager) -> None: ...
def validate_payload_shape(descriptor, payload) -> None: ...
class ProvenanceDescriptor(BaseModel): ...
class TransformerGap(BaseModel): ...   # section, proposed_name, suggested_source
class GapReport(BaseModel): ...        # gaps, covered
class AdhocDatasetAdapter: ...
```

```python
# From packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
class InfographicAuthoringMixin:
    def __init__(self, *args, infographic_toolkit=None, artifact_store=None,
                 recipe_store=None, template_dirs=None, **kwargs) -> None: ...
    async def configure(self, *args, **kwargs) -> None: ...
    async def generate_infographic(self, template: str,
                                   descriptor: "SectionDescriptor | str",
                                   params: Optional[dict] = None
                                   ) -> Tuple[InfographicRenderResult, ProvenanceDescriptor]: ...
        # validate_descriptor_datasets (151) -> _build_section_payload (153)
        # -> render_data_template | render_template (155-167) -> ProvenanceDescriptor (169)
    async def _build_section_payload(self, descriptor, params) -> Tuple[Dict, Dict[str, str]]: ...  # line 182
        # raises InfographicValidationError("multi_dataset_section_unsupported") (220) for >1 dataset
    @staticmethod
    def _assemble_section(section: SectionSpec, frames: Dict[str, Any]) -> Any: ...  # line 250
        # ONLY reshapes raw columns to records/table/mapping/scalar — no transformer lookup
    async def publish_recipe(self, name, descriptor, owner=None, delivery=None,
                             overwrite=False) -> Union[InfographicRecipe, GapReport]: ...  # line 280
        # transformer_registry.get(tname) (338); GapReport on any gap (358-363)
        # layout HARDCODED (379-382):
        #   LayoutSpec(component="Infographic", properties={"template": descriptor.template})
    @staticmethod
    def _transformer_name(section: SectionSpec) -> str:          # line 394
        return re.sub(r"\W+", "_", section.name).strip("_")      # line 397
    @staticmethod
    def _suggest_transformer_source(section, fn_name) -> str: ...  # line 399 (never executed)
```

```python
# From agents/finance_reporter.py
FINANCE_DATASET = "finance_projection"                           # line 43
FINANCE_COLUMNS = ["snapshot_date", "division", "project",
                   "rev_actual", "rev_budget",
                   "ebitda_actual", "ebitda_budget"]             # lines 44-52
DEFAULT_TEMPLATE_DIR = <repo>/sdd/artifacts                      # line 41

@register_agent(name="finance_reporter")                         # line 55
class FinanceReporter(InfographicAuthoringMixin, PandasAgent):   # line 56
    agent_id = "finance_reporter"                                # line 59
    llm = "google:gemini-3.5-flash"                              # line 60
    TEMPLATE_NAME = "budget_variance_dashboard_Template.html"    # line 62
    async def register_datasets(self) -> None: ...               # line 73 (troc.finance_projection, line 81)
    async def configure(self, app=None, queries=None) -> None: ...# line 99
    @classmethod
    def budget_variance_descriptor(cls) -> SectionDescriptor: ...# line 108
        # mode="data-splice", splice_marker_id="report-data",
        # single SectionSpec(name="days", target="/days", shape="mapping")
    async def _build_section_payload(self, descriptor, params): ...# line 131  <-- to be removed
        # hand-rolled groupby into {"YYYYMMDD": [[div, proj, ra, rb, ea, eb], ...]}
```

```python
# From packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                       # line 53
    name: str; description: str; triggers: List[str]    # lines 59-61
    source: SkillSource = SkillSource.AUTHORED          # line 62
    priority: int = 90                                  # line 63
    version: str = "1.0"                                # line 64
    category: Optional[str] = None                      # line 65
    template_body: str                                  # line 66
    token_count: int                                    # line 67
    file_path: Path                                     # line 68
    assets_dir: Optional[Path] = Field(default=None)    # line 69 (composite only)
    MAX_TOKENS: ClassVar[int] = 1000                    # line 74  <-- HARD CAP
    @field_validator("token_count")                     # line 76 -> raises above cap
```

```python
# From packages/ai-parrot/src/parrot/skills/tools.py
class SkillFileToolkit(AbstractToolkit):                          # line 371
    async def list_skill_commands(self) -> ToolResult: ...        # line 413
    async def load_skill(self, name: str) -> ToolResult: ...      # line 454
    async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult: ...  # line 491
def create_skill_tools(...)                                        # line 635

# From packages/ai-parrot/src/parrot/skills/loader.py
class SkillsDirectoryLoader:
    def __init__(self, paths: List[Path], logger: Optional[Logger] = None) -> None: ...
    async def discover(self) -> List[SkillDefinition]: ...
    async def load_into(self, registry: SkillFileRegistry) -> int: ...
# Layouts: single-file {dir}/{name}.md | composite {dir}/{name}/SKILL.md + assets

# From packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:
    enable_skill_registry: bool = True
    skill_paths: List[Path] = []                 # recommended [Path(".agent/skills/")]
    inject_skills_into_prompt: bool = True
    async def get_skill_context(self, query, max_skills, max_tokens): ...
    async def save_learned_skill(self, name, content, description, triggers, category): ...
```

```python
# From packages/ai-parrot/src/parrot/auth/system_account.py
def resolve_system_account_context(channel: str = "scheduler",
                                   account: Optional[SystemAccount] = None
                                   ) -> PermissionContext: ...    # line 90
async def run_scheduled_refresh(runner: Any, name: str, *, params=None,
                                recipe_owner=None, channel="scheduler",
                                account=None) -> Any: ...          # line 129
# Takes a runner INSTANCE -> an injected narrator needs no change here.
# Docstring line 142: "RecipeRunner is NEVER modified and pctx=None is NEVER forwarded"
```

#### Verified Imports

```python
# All confirmed present in the current tree:
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer, transformer_registry
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec, InfographicRecipe, LayoutSpec, RenderSpec, TransformStep,
)                                    # as imported by infographic_authoring.py:40-46
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError    # infographic_authoring.py:47
from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.models import BINDING_KEY, is_binding_expression, CreateSurface
from parrot.outputs.a2ui.baking import BakeError, bake_envelope
from parrot.tools.infographic_sections import (
    GapReport, ProvenanceDescriptor, SectionDescriptor, SectionSpec,
    TransformerGap, validate_descriptor_datasets,
)                                    # as imported by infographic_authoring.py:32-39
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

#### Key Attributes & Constants
- `SkillDefinition.MAX_TOKENS` → `1000` (`skills/models.py:74`) — enforced by validator, `skills/models.py:76`
- `SkillDefinition.assets_dir` → `Optional[Path]`, set only for composite skills (`skills/models.py:69`)
- `InfographicRecipe.schema_version` → `1` (`recipes/models.py:184`) — must not bump
- `RenderSpec.profile` → default `"interactive-html"` (`recipes/models.py:125`)
- `BINDING_KEY` → `"$bind"` (`a2ui/models.py:50`)
- `FinanceReporter.TEMPLATE_NAME` → `"budget_variance_dashboard_Template.html"` (`finance_reporter.py:62`)
- `FINANCE_COLUMNS` → 7 columns incl. `snapshot_date` (`finance_reporter.py:44-52`)
- `_MONEY_COLUMNS` → the 4 money columns the finance transformers require (`library.py:39`)
- Materiality threshold for a division "read" → `ebitda_variance < -5000`, max 2 projects (`executive_summary.py:142`)
- Snapshot column convention → `snapshot_col` param, default `"snapshot"` (`library.py:9-16`) — note `FinanceReporter` calls its column `snapshot_date`, so the param must be passed explicitly or the column renamed
- `PARROT_SYSTEM_ACCOUNT_ID` / `_TENANT` / `_ROLES` → system-account env config (`docs/toolkits/infographic_authoring.md`)

### Does NOT Exist (Anti-Hallucination)
- ~~`transformer_registry.get("days")`~~ — **no `days` transformer is registered**. This is the root cause of the tier-2 gap. The seven registered names are exactly: `day_totals`, `division_breakdown`, `variance_analysis`, `top_movers`, `groupby_aggregate`, `pivot`, `latest_vs_baseline`.
- ~~`SectionSpec.transform`~~ / ~~`SectionSpec.transformer`~~ — no such field; `SectionSpec` is `extra="forbid"`.
- ~~`SectionDescriptor.layout`~~ — does not exist yet (this feature adds it); `SectionDescriptor` is `extra="forbid"`, so it must be a declared field.
- ~~`SectionDescriptor.mode == "a2ui"`~~ — `mode` is `Literal["jinja", "data-splice"]` only.
- ~~`InfographicRecipe.narrative`~~ — does not exist yet (this feature adds it).
- ~~`RecipeRunner(narrator=...)`~~ — no narrator parameter today; ctor is `(store, dataset_manager, *, artifact_store=None, owner=None)`.
- ~~any LLM step inside `RecipeRunner`~~ — the pipeline is strictly deterministic; `run()` lines 245-254 contain no LLM call.
- ~~`parrot.bots.mixins.NarrativeMixin`~~ / ~~`Narrator` protocol~~ — do not exist.
- ~~`InfographicAuthoringMixin._build_layout_spec`~~ — no such hook; the layout is hardcoded inline at `infographic_authoring.py:379-382`.
- ~~any `.docx` renderer / `python-docx` dependency in `parrot/`~~ — `.docx` appears only as an *input* format (loaders, `doc_converter`, `notifications` attachment allowlist). `executive_summary.build_docx` was never ported. **Explicitly out of scope.**
- ~~`executive_summary.headline_text` / `division_read` / `trend_clause` ported anywhere~~ — only the *math* reached `library.py`; all narrative phrasing is unported.
- ~~importable `sdd.artifacts.executive_summary`~~ — `sdd/artifacts/*.py` are standalone reference artifacts, not package modules. Port, never import (`library.py:3-5`).
- ~~packaged skills inside `ai-parrot`~~ — zero `.md` skills ship in `packages/`; skills live as repo data in `.agent/skills/` (20+ present).
- ~~a reusable narrative skill already covering this~~ — `.agent/skills/data-storytelling/SKILL.md` exists but is generic, auto-generated boilerplate about matplotlib/pandas presentation; it does not consume a facts contract and is **not** a substitute.
- ~~`InfographicToolkit._maybe_enhance` as the narrative seam~~ — it exists (`infographic_toolkit.py:1474`) but is **deprecated** (FEAT-273 / G7, warning at lines 1502-1509) and operates on **raw HTML**, not structured text. Do not revive it; narrative goes into catalog-validated component `text`, which is a different mechanism.
- ~~`FinanceReporter` using any transformer from `library.py`~~ — it imports none; verified zero occurrences.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Three clusters are genuinely independent
  once the contracts are fixed: (1) the `narrative_facts` transformer + its unit
  tests — pure function over a DataFrame, touches only `library.py`; (2) the
  skill tree (`SKILL.md` + assets) — data only, no Python; (3) the
  `SectionDescriptor.layout` + `publish_recipe` change — touches
  `infographic_sections.py` and `infographic_authoring.py` only. The runner /
  narrator / optional-bind cluster (`runner.py`, `baking.py`, `models.py`,
  `NarrativeMixin`) is one tightly-coupled unit that must land together, and the
  `FinanceReporter` migration plus its e2e rewrite depends on almost everything
  else, so it goes last.
- **Cross-feature independence**: Touches FEAT-324 (`outputs/a2ui/recipes/**`,
  `tools/infographic_recipes/**`) and FEAT-326 (`bots/mixins/infographic_authoring.py`,
  `tools/infographic_sections.py`, `agents/finance_reporter.py`) — both merged,
  so no in-flight conflict from them. Shared-file risk concentrates on
  `outputs/a2ui/recipes/models.py` and `baking.py`, which any other
  A2UI/recipe work would also touch; worth a `/sdd-status` check for in-flight
  A2UI specs before starting. The `.agent/skills/` tree is append-only here (a
  new directory), so it cannot collide.
- **Recommended isolation**: `per-spec`
- **Rationale**: The independent clusters are small (one transformer, one skill
  directory, one additive model field) while the coupled core — recipe model +
  runner step + bake-pass optional binds + narrator protocol — is the bulk of
  the work and cannot be split without agents guessing at each other's
  contracts. Add the ordering constraint that `FinanceReporter` and the e2e
  tests must be rewritten only after the layout and narrative contracts are
  final, and the sequencing is naturally linear. One worktree, tasks in
  dependency order, is cheaper than coordinating four worktrees around two
  shared files.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus*: `type: feature`, `base_branch: dev`.
- [x] How to reconcile deterministic narrative logic with a skill being LLM instructions — *Owner: Jesus*: deterministic `narrative_facts` transformer emits structured judgements; the skill teaches the LLM to render them as prose.
- [x] Which render path closes tier 2 — *Owner: Jesus*: migrate to the A2UI component layout (not a `days` data-splice transformer).
- [x] Narrative behaviour on a scheduled, user-less refresh — *Owner: Jesus*: regenerate with the LLM under the system account, so prose never goes stale against refreshed numbers.
- [x] Is a `.docx` executive summary in scope — *Owner: Jesus*: no. Out of scope; narrative is delivered inside the artifact. A separate spec if ever wanted.
- [x] How LLM prose enters a deterministic `data_model` — *Owner: Jesus*: a declarative `narrative` step (skill name + facts key + output key — a reference, never code) plus an optional injected `narrator` on `RecipeRunner`; absent narrator skips the step.
- [x] Runner behaviour when `/narrative` is absent — *Owner: Jesus*: declared-optional binds; the drift check tolerates them and the renderer omits the section. Replay never fails for lack of an LLM.
- [x] How to generalise `publish_recipe`'s hardcoded `LayoutSpec` — *Owner: Jesus*: additive optional `layout` field on `SectionDescriptor`; absent means today's template-based behaviour.
- [x] Fate of the existing data-splice descriptor and reference template — *Owner: Jesus*: **replace**. `FinanceReporter` becomes A2UI-only; FEAT-326's e2e example and tests are rewritten accordingly. (The data-splice render mode itself stays.)
- [x] Where the narrative skill lives and in what shape — *Owner: Jesus*: composite `.agent/skills/budget-narrative/` with `SKILL.md` + facts-contract and reference-phrasing assets — required anyway by the 1000-token body cap.
- [x] Who implements the narrator — *Owner: Jesus*: a `Narrator` protocol plus a reusable `NarrativeMixin` over `SkillRegistryMixin`; `FinanceReporter` composes it.
- [x] Where narrative renders in the A2UI layout — *Owner: Jesus*: both, as two publishable profiles — a `Report` root (executive summary) and an `Infographic` root (dashboard).
- [x] Guardrail against LLM-fabricated figures — *Owner: Jesus*: post-generation numeric derivability check; any non-derivable figure discards the whole narrative and falls back to the no-narrative artifact.
- [ ] Does `a2ui/models._validate_bindings` (models.py:93) reject a binding mapping carrying a sibling `optional` key? `is_binding_expression` is a membership test so detection is safe, but the validator's strictness is unverified and decides whether `optional` can be a sibling key or must be encoded differently (e.g. `{"$bind": ..., "$optional": true}` or a separate `optionalBinds` list on the layout) — *Owner: implementing agent (verify before designing the flag)*
- [ ] Column-name mismatch: the finance transformers default to `snapshot_col="snapshot"` (`library.py:13`) while `troc.finance_projection` exposes `snapshot_date` (`finance_reporter.py:44`). Pass the param explicitly everywhere, or rename in the dataset projection? Explicit params are less magical but must be repeated in every recipe — *Owner: Jesus*: explicit params
- [ ] Should `narrative_facts` be finance-specific or take the generic shape (facts derived from any `variance_analysis`+`top_movers` pair)? Generic is more reusable but risks a vague contract that the skill cannot rely on — *Owner: Jesus*: take generic shape
- [ ] Does the `interactive-html` renderer (`ai-parrot-visualizations`) already render `Report` roots and per-section `text`, or does the narrative need renderer work in the satellite package? Unverified — the catalog schema accepts it, which is not the same as the renderer honouring it — *Owner: implementing agent (verify early; it could change the effort estimate materially)*
- [ ] Which LLM serves the narrator? `FinanceReporter.llm` is `"google:gemini-3.5-flash"` (`finance_reporter.py:60`) — adequate for prose, but the figure guard's strictness should be calibrated to whatever model actually runs — *Owner: Jesus*
- [ ] Delivery: the original flow emailed the report. Should the published recipes set `RenderSpec.delivery`, and to which recipients — reusing `daily_report.py`'s list, or configured per deployment? — *Owner: Jesus*: configured per-deployment
