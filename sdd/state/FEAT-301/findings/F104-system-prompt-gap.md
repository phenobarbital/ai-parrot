---
id: F104
query: Q108
type: code_analysis
confidence: high
---
# F104: INFOGRAPHIC_SYSTEM_PROMPT Block Documentation Gap

**File**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py`
**Lines**: 16-46

The prompt documents 12 block types:
  title, hero_card, summary, chart, bullet_list, table, image, quote,
  callout, divider, timeline, progress

**Missing from prompt** (3 existing blocks):
  accordion, checklist, tab_view

**Prior Q&A decision (U3)**: Document all blocks. Still valid.
With 4 new blocks proposed (chain, steps, code, card_grid), the prompt
must document 19 block types total.

**Risk**: A prompt documenting 19 blocks is larger, potentially degrading
LLM output quality. The prior U3 decision accepted this risk. Consider:
- Grouping blocks by category (data, text, layout, code) with compact
  descriptions
- Adding a "preferred blocks" hint so the LLM doesn't over-use exotic types
