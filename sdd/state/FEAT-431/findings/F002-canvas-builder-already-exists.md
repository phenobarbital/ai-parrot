# F002 — The "Canvas Builder" substrate ALREADY EXISTS in navigator-svelte

**Repo:** `/home/jelitox/repos/Trocdigital/navigator-svelte` (read-only pass)
**Citations:**
  `src/lib/components/agents/canvas/blocks/` — **17 block components**
  `src/lib/components/agents/canvas/InfographicCanvas.svelte` (407 lines)
  `src/lib/components/agents/canvas/InfographicEditor.svelte` (158 lines)
  `sdd/specs/migracion-canvas-blocks.spec.md` (FEAT-043, draft)
  `sdd/specs/migracion-infographic-blocks.spec.md` (FEAT-044, approved)
  dashboard editor: `DashboardEditToolbar.svelte`, `GridGuides.svelte`,
  `add-widget-modal.svelte`, `widget-settings-modal.svelte`, `LayoutGridModal.svelte`
  widget domain: 22 classes in `src/lib/fn/dashboard/domain/*widget*.ts`
**Confidence:** high (direct source read)

## Headline

Brainstorm §5.1.B proposes building "a visual Canvas Builder in Navigator" as new
construction. **Two independent visual composition surfaces already exist:**

1. **Agent canvas with a block editor** — 17 blocks shipped:
   `TitleBlock, ChartBlock, TableBlock, MapBlock, HeroCardBlock, SummaryBlock,
   CalloutBlock, QuoteBlock, BulletListBlock, ImageBlock, HtmlBlock, MarkdownBlock,
   InteractiveBlock, DividerBlock` + `BlockToolbar`, `BlockInsertHandle`,
   `MarkdownToolbar`. With `InfographicCanvas` + `InfographicEditor`.
2. **Dashboard editor** — drag/drop grid, snap/resize, add-widget and per-widget
   settings modals, over a 22-class widget domain model.

The migrations that produced (1) were specced as FEAT-043 (canvas blocks, 17 types) and
FEAT-044 (infographic blocks, 15 types), ported from the earlier FrontNext / parrot-ui
implementation. Both are implemented on disk.

## The real gap: the frontend does not speak A2UI

`grep -il "a2ui|CreateSurface" src` → **zero matches**. The frontend canvas is aligned
with the **legacy `InfographicResponse` block vocabulary**, not with A2UI envelopes.

Backend `outputs/a2ui/adapters/infographic.py` converts legacy blocks → A2UI
`CreateSurface` (handlers: `_chart`, `_table`, `_hero_card`, `_timeline`, `_progress`,
`_card_like`, `_flatten_container` for accordion/tab_view). The frontend blocks map
closely onto that same legacy vocabulary:

| Legacy / frontend block | A2UI catalog component |
|---|---|
| ChartBlock | `chart` |
| TableBlock | `datatable` |
| HeroCardBlock | `card` / `kpicard` |
| MapBlock | `map` |
| Summary/Callout/Quote | `card` (card_like) |
| — (missing on frontend) | `timeline`, `report`, `form` |
| Title/Image/Html/Markdown/Divider/BulletList | no direct A2UI component |

So SPEC-B's frontend work is **binding an existing editor to A2UI**, not building a
canvas. That is a materially smaller and better-understood problem.

## Secondary observation — duplication in flight

The block set exists **twice**: `src/lib/components/agents/canvas/blocks/` and
`src/lib/fn/components/agents/canvas/blocks/` (17 files each). `fn/` appears to be a
newer domain-driven layout mid-migration. SPEC-B must target one and not deepen the fork.
