---
id: F006
query: Q006
type: grep
pattern: session_id
---

## Session ID Extraction

Found in `api/uploads.py` (lines 316-319):
```python
session_id: str | None = None
if "session" in request:
    _sid = request["session"].get("id")
    session_id = str(_sid) if _sid else None
```

Also used in `RestCallbackInput` (rest_field_resolver.py:225):
- `session_id: str | None` field

**Key insight**: Session ID is available via `request["session"]["id"]`
on any authenticated route. This is the natural key for partitioning
partial saves per user session. The Redis key should include both
form_id and session_id to isolate saves per user per form.
