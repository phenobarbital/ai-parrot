---
kind: inline
jira_key: null
fetched_at: "2026-05-19T12:00:00Z"
summary_oneline: "Submission backend for saving partial form answers into Redis with TTL and session recovery"
---

# formdesigner-partial-saves

A submission backend for saving partial answers for a form into Redis.

Users in frontend can send partial answers (one by one or in bulk) and those partial answers can be saved temporarily into Redis.

Partial answers are removed at the end of the session or via timeout (TTL). A timeout of 1 hour can be useful to recover a session from a crashed app in frontend.

If frontend sends new values for an existing cached question, new fresh values take precedence over cached values.
