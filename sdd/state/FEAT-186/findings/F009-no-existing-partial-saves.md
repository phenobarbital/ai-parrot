---
id: F009
query: Q011
type: grep
pattern: partial|draft|autosave
---

## No Existing Partial Save Implementation

Grep for "partial", "draft", "autosave" found zero relevant hits in
the formdesigner package. The only match is `_deep_merge` in `_utils.py`
described as "partial update" (PATCH operations) and "not a partial diff"
warning in create_form tool.

**This is a greenfield addition** — no existing code to refactor, no
backward compatibility concerns. The feature is purely additive.
