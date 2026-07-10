---
id: F009
query: INFOGRAPHIC_SYSTEM_PROMPT coverage
type: read
path: packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py
lines: 16-46
---

Documents only 12 of 15 block types.
Missing: accordion, checklist, tab_view (these exist in the model but aren't in the prompt).
The spec says new blocks will be added with "a one-line usage rule each, hero_card-style".
Pre-existing gap: 3 blocks are undocumented.
