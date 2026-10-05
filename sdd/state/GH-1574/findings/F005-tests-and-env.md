# F005 — Test coverage and environment note
- citations:
  - packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py:1-23 — registry/builder only; no behavioural test of any callback's status.
  - packages/ai-parrot-server/tests/scheduler/ — test_listeners.py, test_run_now.py, test_multiworker.py, ... (natural home for manager-level outcome tests).
  - async-notify: pyproject pins `>=1.6.0` (ai-parrot, ai-parrot-server); `uv pip show async-notify` in .venv now reports 2.0.0 = uv.lock. The "Related" venv mismatch in the issue is already resolved; no code change.
