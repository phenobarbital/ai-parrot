---
id: F004
query: InfographicResponse fields
type: read
path: packages/ai-parrot/src/parrot/models/infographic.py
lines: 848-935
---

Fields: template (Optional[str]), theme (Optional[str]), blocks (List[InfographicBlock]),
metadata (Optional[Dict[str, Any]]).

NO `document_meta` field. This is new work for WS-B.
Has `_normalise_payload` model_validator (mode="before") for aliasing and normalization.
