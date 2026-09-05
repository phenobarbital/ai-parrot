---
id: FEAT-527
title: Infographic → A2UI migration — is AgentTalk infographic output A2UI or the legacy HTML lane, and what would a migration entail?
slug: infographic-a2ui-migration
type: feature
mode: investigation
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-04
  summary_oneline: Determine whether AgentTalk infographics are A2UI surfaces or legacy HTML/Jinja templates, and plan migration
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-527/
created: 2026-09-04
updated: 2026-09-04
resolved_at: 2026-09-04
---

# FEAT-527 — Infographic → A2UI migration

> **Mode**: investigation
> **Confidence**: high
> **Source**: `inline` — user brief, 2026-09-04
> **Audit**: [`sdd/state/FEAT-527/`](../state/FEAT-527/)

> ⚠️ **Provisional FEAT-ID.** `FEAT-527` matches `.id_ledger.json`'s
> `next_feature_id` at time of writing; `scripts/sdd/reserve_ids.py` was not run
> because the shared main checkout carries another session's files. **`/sdd-spec`
> (or `/sdd-brainstorm`) must perform the authoritative reservation** and may land
> on a different number.

---

## 0. Origin

> infographic-a2ui-migration -- current infographic (and themes) are templates
> (i think html or jinja templates) and blocks are custom defined for usage on
> infographics, I think not exactly A2UI surfaces and structures, we built A2UI
> infographics surfaces but we need to check if current AgentTalk Infographic
> work is A2UI or stay in the previous html-based infographics.

**Initial signals** (extracted, not interpreted):
- Verbs: "check if … is A2UI or stay in" → factual investigation before a migration decision
- Named entities: infographic, themes, templates (html/jinja?), blocks, A2UI surfaces, AgentTalk
- Components / labels: none (inline)
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

AgentTalk infographic turns are **the legacy HTML lane today**: `InfographicToolkit`
renders every infographic through the deprecated `InfographicHTMLRenderer`, and only
attaches an A2UI envelope when constructed with `emit_a2ui=True`, which no production
caller does — so bots set `OutputMode.INFOGRAPHIC` and `AgentTalk._format_infographic_response`
returns an HTML URL/inline document that the bundled Svelte UI shows in an iframe.
The user's model is half right: **templates are not Jinja/HTML** — `InfographicTemplate`
is a Pydantic *block-order prompt spec*; **blocks** are 19 Parrot-specific Pydantic
models; **themes** are CSS-token `ThemeConfig`s that are *already* lane-neutral through
`DesignSystem` (FEAT-493). The only Jinja lives in the separate trusted
`render_template` lane. Meanwhile the **backend A2UI lane is complete and dormant**:
an `Infographic` catalog component, a pure (lossy) adapter, builders, recipes,
bot/handler routing and persisted surfaces all exist. Migration is therefore not a
port of missing machinery but a **policy and frontend decision**: single lane vs
dual-emit, templates-as-prompts vs templates-as-recipes, and which frontend renders.
Recommendation: `/sdd-brainstorm` to weigh those forks before a spec.

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-527/findings/`. Each entry cites its finding ID(s).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/models/infographic_templates.py` | `InfographicTemplate`, `BlockSpec`, `infographic_registry` | 21-110, 512-587 | templates = Pydantic block-order specs → `to_prompt_instruction()` (10 built-ins) | F002 |
| 2 | `packages/ai-parrot/src/parrot/models/infographic.py` | `BlockType`, 19 block models, `InfographicResponse`, `ThemeConfig`, `theme_registry` | 79-101, 316-1061, 1290-1655 | custom block vocabulary + CSS-token themes (light/dark/corporate/midnight/petrol) | F003 |
| 3 | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | `InfographicHTMLRenderer.render_to_html` | 223-394 | legacy HTML renderer (per-block `_render_*`, DesignSystem stylesheet) | F004 |
| 4 | `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | `get_infographic_html_renderer` | 119-156 | FEAT-273 G7 DeprecationWarning on the HTML lane; JSON lane kept | F004 |
| 5 | `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | `InfographicToolkit.__init__` / `render` / `_build_a2ui_envelope` / `render_template` | 159-172, 213-264, 402-560, 846-899 | HTML-first render; `emit_a2ui=False` default; Jinja only in `render_template` | F006 |
| 6 | `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | `infographic_response_to_envelope`, `CHART_TYPE_MAP` | 1-70, 599-640 | pure block→catalog adapter, documented lossy degradations | F005 |
| 7 | `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infographic.py` | `InfographicComponent` | 33-71, 144-181 | A2UI composite: title/subtitle/theme-hint + sections (→ Tabs/Column) | F005 |
| 8 | `packages/ai-parrot/src/parrot/bots/data.py` | PandasAgent post-loop branch | 1876-1910 | `a2ui_envelope` present → `finalize_a2ui_response`, else INFOGRAPHIC | F007 |
| 9 | `packages/ai-parrot/src/parrot/bots/base.py` | `_finalize_infographic_response` | 895-915, 1425-1445 | same dual branch in `BaseBot` | F007 |
| 10 | `packages/ai-parrot-server/src/parrot/handlers/agent.py` | `AgentTalk._format_infographic_response` | 1625-1628, 2729-2756, 3052-3135 | A2UI checked first, INFOGRAPHIC second; streaming disabled for INFOGRAPHIC | F007 |
| 11 | `packages/ai-parrot/src/parrot/bots/abstract.py` | `AbstractBot.get_infographic` | 3952-4060 | `InfographicTalk` path; deprecated renderer; rewrites `output_mode` to HTML | F007 |
| 12 | `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | `maybeOpenInfographicCanvas` | 1839-1878 | bundled UI opens iframe only on `output_mode == "infographic"` | F008 |
| 13 | `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-registry.ts` | block registry | 1-35 | 12 Svelte block components vs 19 backend block types | F008 |
| 14 | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py` | `DesignSystem.stylesheet` / `resolve` | 1-20, 79-145 | shared theme composer for legacy HTML **and** A2UI ssr/interactive/pdf renderers | F009 |
| 15 | `agents/flex_dashboard.py` | `FlexDashboard` | 1-16, 127, 432-439 | A2UI-native reference agent (recipe → `Infographic` LayoutSpec) | F010 |
| 16 | `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | `UISurfaceKind` | 39-45 | persisted A2UI surface kinds incl. `infographic` (FEAT-492) | F010 |

### 2.2 Constraints Discovered

- **G7 policy vs. practice.** FEAT-273 G7 deprecates the infographic-HTML path
  ("use `OutputMode.A2UI` with the Infographic catalog component and the SSR-HTML
  renderer"; JSON path kept), yet `InfographicToolkit.__init__` constructs that
  renderer unconditionally, so every toolkit instance emits the warning, and FEAT-493
  (2026-09-02) re-invested in the lane.
  *Implication*: the migration must explicitly honour or amend G7. *Evidence*: F004, F006, F011
- **Lossy adapter.** 7 chart types (radar, heatmap, treemap, gauge, funnel, waterfall,
  donut) collapse; `layout`, `color_by_sign`, per-series colours, table `style`, bullet
  `columns` are dropped — "A2UI carries data and semantics, the renderer owns presentation".
  *Implication*: `financial_variance` and other presentation-tuned templates will not
  render identically. *Evidence*: F005
- **Bundled UI cannot render A2UI.** Only one "a2ui" hit in `ui/src` (a generated type);
  the canvas opens only for `output_mode == "infographic"`; 7 block types have no Svelte
  component. The A2UI Svelte renderer is specified for the external
  **navigator-frontend-next**. *Implication*: flipping the lane hides infographics from
  the bundled UI unless it gets a renderer or the HTML URL keeps flowing. *Evidence*: F008, F010
- **Themes are already lane-neutral.** `DesignSystem` resolves `ThemeConfig` for legacy
  and A2UI HTML renderers alike; the `Infographic` component carries `theme` as a hint.
  *Implication*: no theme migration needed. *Evidence*: F009
- **Templates are prompt artefacts, not render artefacts.** They constrain the LLM's
  block order. *Implication*: they can stay upstream of the adapter or be re-expressed
  as deterministic recipes — an architectural fork. *Evidence*: F002, F005, F010
- **Streaming gate.** INFOGRAPHIC force-disables streaming (atomic signed URL); A2UI has
  no equivalent gate in `AgentTalk`. *Evidence*: F007
- **Real Jinja lane exists separately.** `render_template` + `InfographicTalk /render`
  (FEAT-327) fill trusted developer HTML+Jinja templates; no A2UI counterpart.
  *Evidence*: F006, F007
- **No production `emit_a2ui=True`.** Only `examples/agents/a2ui/a2ui_dashboard_walkthrough.py`
  sets it; `InfographicAuthoringMixin`, `InfographicTalk`, `ResultAgent` use the default;
  AgentStudio forwards `**params` (so it *could* be enabled per agent). *Evidence*: F006

### 2.3 Recent History (Relevant)

| Commit | When | Message | Evidence |
|--------|------|---------|----------|
| `e4628fcea` | 2026-09-02 | FEAT-493 TASK-2712 — migrate the infographic HTML lane onto the composer | F011 |
| `d81ac63df` | 2026-08-30 | FEAT-476 TASK-2595 — flagged surfaces: canvas, charts, maps, infographic | F011 |
| `69422348d` | 2026-08-29 | wip: info agent (toolkit, emission, data.py wiring) | F011 |
| `8d62f8c89` | 2026-08-28 | FEAT-470 TASK-2541 — Infographic adapter remap to v1.0 primitives | F011 |
| `bd0fbbe41` | 2026-08-19 | FEAT-301 TASK-2257 — A2UI adapter converters for the 4 new block types | F011 |
| `076814287` | 2026-08-14 | feat(a2ui): add InfographicResponse → CreateSurface adapter | F011 |

Governing specs (all `approved`): FEAT-095, 273, 301, 470, 476, 491, 492, 493. No open
SDD task covers an infographic→A2UI migration (F011).

---

## 3. Hypothesis

### Hypothesis 1 — AgentTalk infographics are the legacy HTML lane; the A2UI lane is complete but dormant · Confidence: **high**

**Supporting evidence**: F006, F007, F008, F010 · **Contradicting**: —
**Reasoning**: `emit_a2ui` defaults to `False` and a repo-wide grep finds no production
caller enabling it; both bot post-loop branches then take `_finalize_infographic_response`
(→ `OutputMode.INFOGRAPHIC`, HTML url/inline); `AgentTalk` returns the HTML envelope; the
bundled UI iframes it. Everything needed for the A2UI branch (adapter, component, routing,
persistence, HTML renderers) is present and tested — it is simply not switched on.

**Suggested next probe**:
```bash
source .venv/bin/activate
python -c "from parrot.tools.infographic_toolkit import InfographicToolkit as T; import inspect; print(inspect.signature(T.__init__).parameters['emit_a2ui'].default)"
grep -rn "emit_a2ui" packages/*/src agents --include=*.py | grep -v infographic_toolkit.py
```

### Hypothesis 2 — "Templates/blocks" are Parrot-only vocabulary; "themes" already bridge both lanes; the only Jinja is `render_template` · Confidence: **high**

**Supporting evidence**: F002, F003, F006, F009 · **Contradicting**: —
**Reasoning**: direct reads of `InfographicTemplate.to_prompt_instruction()`, the 19 block
models, `ThemeConfig` ("CSS variable configuration"), and `DesignSystem`'s shared-composer
docstring and A2UI-renderer call sites.

### Hypothesis 3 — The repo carries an unresolved policy contradiction (G7 deprecation vs FEAT-493 re-investment) · Confidence: **medium**

**Supporting evidence**: F004, F006, F011 · **Contradicting**: —
**Reasoning**: inferred from the warning site and commit dates; the FEAT-493 spec body was
not read, so it may consciously scope the HTML lane as long-lived (as a *renderer output*
of A2UI rather than a parallel lane).

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Templates are Pydantic block-order specs, not Jinja/HTML | F002 | high | direct read; no Jinja import |
| C2 | Blocks = 19 Parrot Pydantic models; themes = CSS-token `ThemeConfig` | F003 | high | direct read |
| C3 | The only Jinja templates are `render_template` / `InfographicTalk /render` | F006, F007 | high | `TemplateEngine` wiring read |
| C4 | AgentTalk infographic turns are INFOGRAPHIC+HTML today (`emit_a2ui` default False, no production enabler) | F006, F007 | high | default + grep + both bot branches |
| C5 | Backend A2UI infographic lane is complete (component, adapter, builder, routing, persistence, renderers) | F005, F007, F009, F010 | high | reads across all layers |
| C6 | Bundled Svelte UI cannot render A2UI; 12/19 block components | F008 | high | single generated-type "a2ui" hit |
| C7 | Themes already shared via `DesignSystem` | F009 | high | docstring + call sites |
| C8 | Adapter is lossy (7 chart types; presentation fields) | F005 | high | adapter docstring enumerates |
| C9 | G7 deprecates the HTML lane while FEAT-493 re-invested in it | F004, F011 | medium | FEAT-493 spec body not read |
| C10 | A2UI frontend renderer is planned in navigator-frontend-next (external) | F010 | medium | doc dated 2026-09-02; external repo not inspected |
| C11 | No SDD task covers this migration | F011 | medium | keyword scan; origin `claude/a2ui-infografias-audit-*` branches not inspected |
| C12 | "wip: info agent" indicates in-flight work on the same wiring | F011 | low | stat only, diff not read |

Distribution: **8** high, **3** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase, 2026-09-04)

- [x] **U1 — Target end state** — *Resolved*: **Dual-emit permanently.** Flip `emit_a2ui`
  default to `True`; keep the INFOGRAPHIC HTML envelope (`html_url` / `html_inline`)
  alongside `a2ui_envelope` for legacy consumers. Reversible, lowest risk.
  *Resolves claims*: C4, C9 — **FEAT-273 G7 must be amended**: the HTML lane is no
  longer "superseded" but a *sibling emission*; the unconditional DeprecationWarning
  in `get_infographic_html_renderer` (and its trip on every toolkit construction) must go.
- [x] **U2 — Frontend of record** — *Resolved*: **Both.** navigator-frontend-next stays
  the primary A2UI consumer, **and** the bundled ai-parrot-server UI must gain a minimal
  A2UI `Infographic` renderer as part of this feature (today it iframes HTML only and
  covers 12/19 block types). *Resolves claims*: C6, C10
- [x] **U3 — Fate of templates/blocks** — *Resolved*: **Extend A2UI presentation props
  first.** Before choosing between "keep upstream" and "migrate to recipes", grow the
  `Infographic` component / A2UI renderers with the chart types and presentation fields
  the adapter currently drops (radar/heatmap/treemap/gauge/funnel/waterfall/donut;
  `layout`, `color_by_sign`, per-series colours, table `style`, bullet `columns`).
  `InfographicResponse` remains the LLM contract meanwhile. *Resolves claims*: C1, C2, C8
- [x] **U4 — Jinja `render_template` lane** — *Resolved*: **Wrap as opaque HTML surface.**
  `render_template` / `InfographicTalk /render` output is emitted as an A2UI surface
  carrying raw HTML so one envelope contract covers every infographic path.
  *Resolves claims*: C3 — needs a catalog decision (existing opaque/HTML primitive vs a
  new `RawHtml`-style Parrot component) and a sanitisation stance.

### Unresolved (defer to spec / implementation)

- [ ] **Does FEAT-493's spec already scope the HTML lane as long-lived?** — *Owner*: spec
  author · *Blocks claims*: C9 · Read `sdd/specs/html-renderer-design-system.spec.md`
  before amending G7 wording.
- [ ] **What is on `origin/claude/a2ui-infografias-audit-wtp9eu` and
  `origin/claude/agenttalk-infographic-toolkit-0q473i`?** — *Owner*: tbd · *Blocks
  claims*: C11, C12 · Possible prior audit/WIP overlapping this feature.
- [ ] **Streaming**: does dual-emit keep the INFOGRAPHIC no-stream gate, or adopt A2UI's
  behaviour? — *Owner*: spec · *Blocks*: F007 constraint.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-527`** — *Rationale*: all four architectural unknowns are resolved and
localization is high-confidence; the remaining questions are spec-level details. The
answers imply **four modules**, which the spec may split into two features if the task
graph exceeds ~15 tasks:

1. **Backend dual-emit (U1)** — `emit_a2ui=True` by default in `InfographicToolkit`;
   `InfographicAuthoringMixin` / `InfographicTalk._get_render_toolkit` / `ResultAgent`
   inherit it; `AgentTalk` INFOGRAPHIC envelope gains `a2ui_envelope` (and the A2UI
   response gains `metadata.html_url`) so both consumers are served by one turn; amend
   FEAT-273 G7 wording and remove the unconditional DeprecationWarning; decide the
   streaming gate.
2. **A2UI presentation parity (U3)** — extend `Infographic`/`Chart`/`DataTable` catalog
   props and the ssr-html / interactive-html renderers with the fields
   `adapters/infographic.py` documents as dropped; shrink `CHART_TYPE_MAP` collapses;
   update the adapter to pass them through. Prerequisite for the renderer module.
3. **Bundled-UI A2UI Infographic renderer (U2)** — minimal Svelte 5 renderer for
   `a2ui_envelope` in `packages/ai-parrot-server/ui` (open canvas on
   `output_mode ∈ {infographic, a2ui}`), reusing the 12 existing block components where
   the lowering maps 1:1 and adding the 7 missing ones; keep iframe fallback via `html_url`.
4. **Opaque HTML surface for `render_template` (U4)** — catalog component (or reuse of
   an existing opaque primitive) carrying sanitised raw HTML; `render_template` and
   `InfographicTalk /render` emit it; CSP/`JSBundle` headers preserved.

### Alternatives

- **`/sdd-brainstorm FEAT-527`** — only if module 2's scope (which presentation props,
  which chart types) needs option analysis before committing.
- **Split now** — `/sdd-spec` twice: *infographic-dual-emit-a2ui* (modules 1, 2, 4) and
  *agentchat-a2ui-infographic-renderer* (module 3, depends on the first).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-527/state.json` |
| Source (raw) | `sdd/state/FEAT-527/source.md` |
| Research plan | `sdd/state/FEAT-527/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-527/findings/F001-*.md` … `F011-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-527/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 36 / 40
- Grep calls: 20 / 25
- Git calls: 2 / 10
- Wiki calls: 4 (free)
- Depth reached: 1 / 2
- Truncated: **no**

**Mode determination**: `auto` → resolved to `investigation` (source asks "check if … is
A2UI or …" — a factual question preceding a decision).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (via Claude Code, Fable 5.1) |
