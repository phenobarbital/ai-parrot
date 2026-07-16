---
type: Concept
title: parse_repo_specs()
id: func:parrot.flows.dev_loop.config.parse_repo_specs
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse ``DEV_LOOP_REPOS`` entries into :class:`RepoSpec` objects.
---

# parse_repo_specs

```python
def parse_repo_specs(raw: list[str]) -> list[RepoSpec]
```

Parse ``DEV_LOOP_REPOS`` entries into :class:`RepoSpec` objects.

Each entry is one of:

* a **JSON object string** — ``RepoSpec(**json.loads(entry))``
  (honors ``alias`` / ``branch`` / ``private``).
* a **full clone URL** — ``RepoSpec(alias=<derived>, url=<entry>)``.
  Supports ``https://github.com/owner/name(.git)`` and
  ``git@github.com:owner/name.git``.
* an **``owner/name`` slug** — ``RepoSpec(alias=<name>, url=<entry>)``.

The alias defaults to the repo's ``<name>`` component with any
trailing ``.git`` stripped.  ``branch`` defaults to ``"main"`` and
``private`` to ``False`` unless supplied in the JSON form.

Blank / whitespace-only entries are silently skipped.  Invalid JSON
falls back to URL/slug handling so a slightly-malformed entry still
produces a usable ``RepoSpec``.  Entries for which no alias can be
derived (e.g. bare ``git@github.com:``) are also skipped with a
warning.

Args:
    raw: List of raw string entries from ``DEV_LOOP_REPOS``.

Returns:
    List of :class:`RepoSpec` instances, in order.
