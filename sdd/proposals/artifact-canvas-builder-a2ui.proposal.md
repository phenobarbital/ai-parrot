---
id: FEAT-431
title: Artifact & Canvas Builder — bind the existing canvas to A2UI, supersede FEAT-301
slug: artifact-canvas-builder-a2ui
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  fetched_at: 2026-08-19
  summary_oneline: "SPEC-B — agent-generated A2UI surfaces replacing opaque HTML artifacts, composed in Navigator"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-431/
related:
  - FEAT-430 (SPEC-A — scheduled dashboard delivery)
  - FEAT-273 (a2ui-implementation — COMPLETE)
  - FEAT-301 (themed component catalog — SUPERSEDED by this proposal)
created: 2026-08-19
updated: 2026-08-19
revision: 2 (F005 — fn/ is an FN mirror; Q4 resolved)
---

# FEAT-431 — Artifact & Canvas Builder (SPEC-B)

> **Mode**: enrichment · **Confidence**: high
> **Source**: `BRAINSTORM-dashboard-notify-canvas.md` §5 (rev 2.1)
> **Audit**: [`sdd/state/FEAT-431/`](../state/FEAT-431/)

---

## 0. Origin

SPEC-B of the rev 2.1 brainstorm: move artifact generation from Claude-generated opaque
HTML to **agent-generated, deterministically refreshable A2UI structures**, and give
Navigator an **Artifact & Canvas Builder** so reports are composed from real catalog
components.

Companion to **FEAT-430** (SPEC-A), which owns scheduling, secure sharing and delivery.
Per HI-6, SPEC-B changes **only the generation step**.

---

## 1. Synthesis Summary

**SPEC-B is a binding problem and a governance problem — not a build-a-canvas problem.**

The brainstorm proposes constructing a visual Canvas Builder. Two visual composition
surfaces already ship in `navigator-svelte`, and FEAT-273 is verifiably complete with a
9-component catalog. What is genuinely missing is that **the frontend has zero A2UI
references**: its canvas speaks the *legacy* `InfographicResponse` block vocabulary, which
is exactly what the backend's existing adapter converts *away from*.

Second, an un-actioned proposal (FEAT-301) targets incompatible A2UI architecture and its
own research warned it would create "parallel A2UI infrastructure". SPEC-B must close it.

---

## 2. Codebase Findings

### 2.1 Localization

| Component | Location | Finding |
|---|---|---|
| A2UI core | `ai-parrot/.../outputs/a2ui/` (builders, catalog, recipes, renderers, baking, producer) | F001 |
| Catalog (9 components) | `.../a2ui/catalog/components/{card,chart,datatable,form,infographic,kpicard,map,report,timeline}.py` | F001 |
| legacy→A2UI adapter | `.../a2ui/adapters/infographic.py` | F001 |
| Artifact/delivery/deeplink | `.../a2ui/{artifacts,delivery,deeplink}.py` | FEAT-430 F007 |
| Renderers | `ai-parrot-visualizations/.../a2ui_renderers/{adaptive_cards,ssr_html,interactive_html,pdf}.py` | FEAT-430 F007 |
| **Agent canvas (17 blocks)** | `navigator-svelte/src/lib/components/agents/canvas/blocks/` | F002 |
| **Infographic editor** | `.../canvas/InfographicCanvas.svelte` (407L), `InfographicEditor.svelte` (158L) | F002 |
| Dashboard editor | `.../components/dashboards/{DashboardEditToolbar,GridGuides}.svelte` + modals | F002 |
| Widget domain (22 classes) | `navigator-svelte/src/lib/fn/dashboard/domain/*widget*.ts` | F002 |
| Permission substrate | `navigator-svelte/src/lib/helpers/rep-mode.ts` | F004 |
| Prior art (conflict) | `sdd/proposals/infographic-theme-catalog-a2ui.proposal.md` (FEAT-301) | F003 |

### 2.2 Claims CONFIRMED

- **rev2 #5 — "FEAT-273 is DONE"**: confirmed. Task index shows **22/22 tasks `done`**,
  `completed_at: 2026-07-11`. SPEC-B is not blocked on platform delivery. [F001]
- **§5.1.D — pipeline reuse**: confirmed by FEAT-430 F007 — `RenderedArtifact`,
  `deliver_artifact()` and an `adaptive_cards` renderer already exist, so scheduling,
  sharing and delivery carry over untouched.
- **§5.1.D open question — "A2UI → sendable/viewable rendering"**: largely **already
  answered**; renderers for adaptive cards, SSR HTML, interactive HTML and PDF ship today.

### 2.3 Claims CORRECTED

**1. The Canvas Builder substrate already exists.** [F002] *(headline)*

Brainstorm §5.1.B treats "a visual Canvas Builder in Navigator" as new construction. Two
composition surfaces already ship:

- **Agent canvas with a 17-block editor**: `TitleBlock, ChartBlock, TableBlock, MapBlock,
  HeroCardBlock, SummaryBlock, CalloutBlock, QuoteBlock, BulletListBlock, ImageBlock,
  HtmlBlock, MarkdownBlock, InteractiveBlock, DividerBlock` + `BlockToolbar`,
  `BlockInsertHandle`, `MarkdownToolbar` — plus `InfographicCanvas` and
  `InfographicEditor`.
- **Dashboard editor**: drag/drop grid, snap/resize, add-widget and per-widget settings
  modals, over a 22-class widget domain model.

These came from FEAT-043 (canvas blocks, 17 types) and FEAT-044 (infographic blocks, 15
types), ported from the earlier FrontNext / parrot-ui implementation. Both are on disk.

**2. The real gap is that the frontend does not speak A2UI.** [F002]

`grep -il "a2ui|CreateSurface"` over `navigator-svelte/src` returns **zero matches**. The
canvas is aligned to the legacy `InfographicResponse` vocabulary — the very model
`adapters/infographic.py` converts *into* A2UI. Mapping today:

| Frontend block | A2UI catalog |
|---|---|
| ChartBlock | `chart` |
| TableBlock | `datatable` |
| HeroCardBlock | `card` / `kpicard` |
| MapBlock | `map` |
| Summary / Callout / Quote | `card` (card_like) |
| Title / Image / Html / Markdown / Divider / BulletList | no direct component |
| *(absent on frontend)* | `timeline`, `report`, `form` |

**3. FEAT-301 must be superseded, not ignored.** [F003]

FEAT-301 sits at `status: review` with **no task index** — never decomposed, never built.
Its own finding F012 recorded the conflict with FEAT-273 (v0.9.1 vs v1.0, standalone
renderer vs centralized catalog+registry, fresh vs shared envelope models) and concluded:

> WS-C must be reconciled with FEAT-273 or risk creating **parallel A2UI infrastructure**.

FEAT-273 then shipped, settling it by fact. Leaving FEAT-301 open invites a third effort
to recreate exactly that risk.

### 2.4 Risks NOT anticipated by the brainstorm

- **~~The canvas block set is duplicated~~ — CORRECTED by F005.** The two trees are not
  a fork. `src/lib/components/agents/canvas/blocks/` is navigator-svelte's own and is
  **canonical**; `src/lib/fn/components/agents/canvas/blocks/` is a **sandbox mirror of
  navigator-frontend-next's `$lib`** (FEAT-446 Port Kit), where files must keep FN's
  relative paths. Writing there desynchronizes the mirror. [F005]
- **The dashboard domain layer is FN-ported.** There is no `src/lib/dashboard/` outside
  `fn/` — the 22 widget classes, `iframe-widget.svelte.ts` and the dashboard modals live
  only under `src/lib/fn/dashboard/`. Only `src/lib/components/dashboards/` is
  navigator-svelte's own. Relevant to any work touching widgets. [F005]
- **Three A2UI components have no canvas counterpart** — `timeline`, `report`, `form`.
  Either new blocks or an explicit v2 scope exclusion. [U2]

---

## 3. Hypothesis / Scope

### 3.1 Design decisions (resolved with the user)

- **D1 — Reverse adapter.** Add the inverse direction to the existing adapter: A2UI
  `CreateSurface` → canvas block vocabulary. The 17 blocks and the editor stay untouched
  and **the frontend never learns A2UI**. Keeps the mapping in Python beside the forward
  adapter that already exists, rather than duplicating it in Svelte.
- **D2 — Supersede FEAT-301.** FEAT-431 formally supersedes it; its theming content is
  absorbed into the centralized A2UI catalog (`@register_component`), not reimplemented
  as a standalone renderer or `parrot-catalog.json`.
- **D3 — Repo split.** FEAT-431 covers backend generation, the reverse adapter, the
  FEAT-301 supersession and the frontend **contract**. The Canvas Builder UI itself goes
  to `navigator-svelte` under its own FEAT-ID, mirroring how SPEC-A's settings panel was
  split (FEAT-430 F010).

### 3.2 Revised build delta

| # | Item | Brainstorm estimate | Verified reality |
|---|---|---|---|
| 1 | A2UI generation engine | new | **mostly exists** — adapter, builders, catalog, producer ship [F001] |
| 2 | Canvas Builder UI | new | **substrate exists** — 17 blocks + editor + grid editor [F002] |
| 3 | A2UI→canvas binding | not identified | **new** — the reverse adapter (D1) |
| 4 | Agent → A2UI for dashboards | new | **new** — agent + data-slug binding [U3] |
| 5 | Two-level permissions | new | **small** — new groups on an existing pattern [F004] |
| 6 | A2UI→sendable rendering | open question | **already answered** [FEAT-430 F007] |
| 7 | Supersede FEAT-301 | — | **new** (governance) [F003] |
| 8 | Knowledge transfer (§5.1.E) | deliverable | **retained** — see 3.4 |

### 3.3 Coexistence (unchanged from FEAT-430)

`Dashboard.attributes.artifact_type` = `v1-html` | `v2-a2ui`, defaulting to `v1-html`
when absent. Both branches emit a `RenderedArtifact`, so storage, signing, sharing and
delivery are written once. No forced migration; formats coexist per report, exactly as
§5.1.C requires.

### 3.4 Knowledge transfer (§5.1.E) — retained deliverable

The brainstorm names knowledge concentration ("only Jesús knows how to use it") as the
recurring organizational risk and makes documentation an explicit deliverable, not a
nice-to-have. This proposal keeps it in scope: a runbook covering end-to-end A2UI
generation → render → deliver, written against the now-verified FEAT-273 surface.

Note: F001 removes the brainstorm's *first* proposed task for SPEC-B — "local end-to-end
verification of FEAT-273" — as a discovery exercise, since the task index settles its
completeness. The runbook remains valuable; the verification framing does not.

---

## 4. Confidence Map

| Claim | Confidence | Basis |
|---|---|---|
| C1 FEAT-273 complete, 9-component catalog | high | F001 — task index + source tree |
| C2 Canvas substrate already ships | high | F002 — direct source read |
| C3 Frontend has zero A2UI, uses legacy vocabulary | high | F002 — exhaustive grep |
| C4 FEAT-301 must be superseded | high | F003 — its own recorded conflict |
| C5 Permission substrate exists | medium | F004 — pattern verified, gate not traced |
| C6 ~~Canvas blocks duplicated~~ → `components/` canonical, `fn/` is an FN mirror | high | F005 — supersedes F002 |

---

## 5. Open Questions

- [x] **Q1 — How to bind frontend to A2UI?** → **Reverse adapter** (D1).
- [x] **Q2 — What about FEAT-301?** → **Supersede and absorb its theming** (D2).
- [x] **Q3 — Scope?** → **Backend + contract here; Canvas Builder UI in navigator-svelte** (D3).
- [x] **Q4 — Which block tree is canonical?** → **`src/lib/components/agents/canvas/blocks/`**
  (navigator-svelte's own). `fn/` is a sandbox mirror of navigator-frontend-next and must
  keep FN's paths. The reverse adapter targets the canonical tree. [F005]
- [ ] **Q5 — `timeline`, `report`, `form`**: add canvas blocks, or exclude from v2 scope?
- [ ] **Q6 — Which agent produces the A2UI surface** for a dashboard, and how is it bound
  to data slugs? The largest genuinely-unknown design area.
- [ ] **Q7 — Does superseding FEAT-301 also require reconciling FEAT-094**
  (infographic-html-output), which FEAT-301 lists as related?

---

## 6. Recommended Next Step

→ **`/sdd-spec FEAT-431`**

Localization is high-confidence, three design decisions are resolved, and the build delta
is concrete. Q4 is now resolved (F005), so the reverse adapter has an
unambiguous target vocabulary.

The companion Canvas Builder UI needs its own FEAT-ID in `navigator-svelte`, coordinated
via that repo's `sdd/BACKEND-REQUEST-<topic>.md` convention (see FEAT-430's handoff
material at `sdd/state/FEAT-430/handoff/`).

---

## 7. Research Audit

- State: `sdd/state/FEAT-431/`, findings `F001..F004`, synthesis `synthesis.json`
- Budget: `loose` — not truncated
- Repos: `ai-parrot` (wiki-indexed), `navigator-svelte` (read-only; nothing modified —
  that repo has uncommitted in-flight work)
- Inherits verified findings from FEAT-430 (F007 A2UI delivery, F009/F010 coexistence seam)
