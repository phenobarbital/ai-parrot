---
id: F010
query_id: Q010
type: git_log
intent: Establish recent activity on incident-relevant files
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F010 — recent history on pythonrepl.py

## Summary
Five commits in 60 days touch `pythonrepl.py`; the head one, `0f76129b1
"security on llm clients and agents"`, is the partial implementation of this very
FEAT (it touches pythonrepl.py, google/client.py, bots/agent.py, security/
redaction.py, both test files, and committed the brainstorm md). Prior commits are
unrelated (bokeh removal, skill-registry fixes, genai bump, lazy imports).

## Citations
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  symbol: `git log --since=60.days.ago`
  excerpt: |
    0f76129b1 security on llm clients and agents   <-- partial impl of FEAT-252
    88e7a5a53 Remove Bokeh, HoloViews, and D3 output modes
    dd7e0666e fixes over skill registry and pandas agent + infographic
    016631ee5 increased version of google-genai
    ba5291361 lazy import of pythonrepl modules

## Notes
The partial work is committed on dev, not a dangling worktree. Tests
test_pythonrepl_security.py (38 lines) + edits to test_google_client.py exist.
