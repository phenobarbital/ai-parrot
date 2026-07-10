---
id: F010
query: I18nText and A2UI code existence
type: grep
---

I18nText: does NOT exist in infographic models or anywhere in parrot/models/.
Forms subsystem has `LocalizedString` for dict-based i18n, but not wired to infographics.
A2UI: zero results for "a2ui" (case-insensitive) across the codebase.
No vendored A2UI schemas, no envelope.schema.json, no catalog.json.
All A2UI work is greenfield for WS-C.
