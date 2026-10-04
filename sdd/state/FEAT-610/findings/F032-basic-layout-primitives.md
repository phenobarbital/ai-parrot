---
id: F032
query_id: Q031
type: read
intent: Layout containers available for a dashboard grid (Row/Column/Card/Tabs; no Grid)
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F032 — Layout: Basic Catalog has Row/Column/List/Card/Tabs/Modal; there is NO Grid container
## Summary
The vendored A2UI v1.0 Basic Catalog (`https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json`) ships 18 primitives: Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Modal, Divider, Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput. Layout is Row/Column (with per-child `weight` flex hint on `Component`) plus Card/Tabs; there is no Grid/GridLayout component. Chart's `layout: full|half` is a width hint (Infographic lowering groups consecutive half-width siblings into a Row). Surface default catalog for parrot composites is `https://parrot.dev/catalogs/v1`; mixing both catalogs in one surface is normal (renderers declare both in `supported_catalog_ids`).
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/catalog.json`
  lines: -
  symbol: `components`
  excerpt: |
    catalogId https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json
    ['Text','Image','Icon','Video','AudioPlayer','Row','Column','List','Card','Tabs','Modal',
     'Divider','Button','TextField','CheckBox','ChoicePicker','Slider','DateTimeInput']
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/__init__.py`
  lines: 44
  symbol: `BASIC_CATALOG_ID`
  excerpt: |
    BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py`
  lines: 53
  symbol: `DEFAULT_CATALOG_ID`
  excerpt: |
    DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`
  lines: 400-443
  symbol: `Component.weight`
  excerpt: |
    weight: The relative flex weight within a ``Row``/``Column``.
    ...
    weight: float | None = None
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte`
  lines: 295-296
  symbol: `-`
  excerpt: |
    {:else if component === 'List' || component === 'Row' || component === 'Column'}
    	<div class={component === 'Row' ? 'flex flex-row gap-3' : 'flex flex-col gap-2'}>
## Implications
- Dashboard layout should be `root: Column[ Row[KPICard x N], Row[Chart country, Chart licensee, Chart course], FilterBar, DataTable ]`; the HTML renderer maps Row→CSS flex/grid (honouring `weight`), Column→vertical stack, Card→panel.
- A per-widget refresh button + title chrome must be renderer-owned (wrap each Parrot composite in a card header), since Card has no header/actions props for display-only LLM surfaces.
