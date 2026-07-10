---
id: F003
query: BlockType enum and block model conventions
type: read
path: packages/ai-parrot/src/parrot/models/infographic.py
lines: 71-825
---

15 BlockType members confirmed: title, hero_card, summary, chart, bullet_list,
table, image, quote, callout, divider, timeline, progress, accordion, checklist, tab_view.

NO block model uses `model_config = ConfigDict(frozen=True)` or `extra="forbid"`.
Spec says "frozen=True where the file uses it" — file convention is NO frozen/no extra.
New models should follow the same convention (plain BaseModel).

InfographicBlock union at line 825 uses `Union[...]` with Pydantic v2 discriminator.
