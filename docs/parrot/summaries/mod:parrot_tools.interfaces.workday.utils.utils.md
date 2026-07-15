---
type: Wiki Summary
title: parrot_tools.interfaces.workday.utils.utils
id: mod:parrot_tools.interfaces.workday.utils.utils
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_tools.interfaces.workday.utils.utils
relates_to:
- concept: func:parrot_tools.interfaces.workday.utils.utils.ensure_list
  rel: defines
- concept: func:parrot_tools.interfaces.workday.utils.utils.extract_by_type
  rel: defines
- concept: func:parrot_tools.interfaces.workday.utils.utils.extract_nested
  rel: defines
- concept: func:parrot_tools.interfaces.workday.utils.utils.first
  rel: defines
- concept: func:parrot_tools.interfaces.workday.utils.utils.safe_serialize
  rel: defines
---

# `parrot_tools.interfaces.workday.utils.utils`

## Functions

- `def safe_serialize(val: Any) -> str` — Serialize Decimal, list or dict into JSON-friendly string,
- `def ensure_list(val: Any) -> List` — Convert a potentially singular value to a list.
- `def extract_by_type(ids: Any, desired_type: str) -> Optional[str]` — Given a list of {'_value_1':…, 'type':…} dicts (or a single dict),
- `def extract_nested(data: Dict[str, Any], path: list) -> Any` — Helper to extract nested data from a dict given a list of keys.
- `def first(v: Any) -> Dict[str, Any]` — Helper to get first item of a list or dict, or empty dict if neither.
