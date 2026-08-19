---
id: F100
query: Q100, Q101
type: code_analysis
confidence: high
---
# F100: A2UI Adapter Block Coverage (FEAT-273 Module 11)

**File**: `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py`

The adapter `_Converter.walk()` maps 12 block types explicitly:
- hero_card → KPICard
- chart → Chart (+ data model binding)
- table → DataTable (+ data model binding)
- timeline → Timeline
- progress → KPICard (per item)
- summary → section text (or Card fallback)
- bullet_list → Card (items as body)
- checklist → Card (items as body)
- callout → Card (badge = level)
- quote → Card (footer = attribution)
- image → Card (image + caption)
- title → surface title / section heading
- divider → section boundary
- accordion/tab_view → flattened into sibling sections (recursive, depth-limited)

**Gap**: The 4 proposed new block types (`chain`, `steps`, `code`, `card_grid`)
would fall through to `_card_like()` as generic Cards. This is a **documented
degradation path** — the adapter already handles unknown types this way. However,
for semantic-rich blocks (chain/steps especially), the Card fallback loses
structure. Extending `_Converter` with explicit mappings is recommended but
not blocking — the adapter degrades safely.

**A2UI catalog components available for mapping**:
Chart, Card, KPICard, DataTable, Timeline, Map, Infographic (composite),
Report (composite), Form (action-bearing, rejected for display-only).
No `Code` or `Steps` component exists in the catalog — new blocks would
need either new A2UI catalog components or Card-based lowering.
