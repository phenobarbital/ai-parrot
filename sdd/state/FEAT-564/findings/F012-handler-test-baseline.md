---
id: F012
query_id: Q012
type: read
intent: Reproduce the reported read-only request fixture failure
executed_at: 2026-09-17
parent_id: F003
depth: 1
---

# F012 — Handler fixture failure reproduced

## Summary

Executed pytest packages/ai-parrot/tests/test_video_reel_handler.py -q in the activated project environment: 13 passed, 8 warnings, 20 errors. Setup errors identify the assignment to the read-only request property. This is a broken test fixture, not proof of HTTP runtime failure or successful handler coverage. Instantiate using the real view contract where practical; _request is the minimal fixture repair.

## Citations

- packages/ai-parrot/tests/test_video_reel_handler.py:70–90 — handler fixture uses __new__ and h.request = MagicMock().
- artifacts/logs/video_reel_proposal_revision_pytest.log — full fresh test output and summary.
- packages/ai-parrot-server/src/parrot/handlers/video_reel.py:14–31 — BaseView inheritance and VideoReelHandler.

## Notes

Initial sandbox attempt stopped in navconfig Logstash initialization because local socket creation was denied. The same command was rerun with approved escalation and reached the reported fixture errors. No fixtures were modified in this documentation task.
