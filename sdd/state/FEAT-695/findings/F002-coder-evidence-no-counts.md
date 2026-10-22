# F002 — sdd-coder validation evidence carries outcome/exit_code, not counts
- sdd_coder/background.py:190-191 — outcome Literal[completed|failed|timed_out|cancelled], exit_code.
- sdd_coder/optimization_models.py:205 TaskCompletionEvidence — validation_refs: list[EvidenceRef], no pass/fail counts.
- sdd_coder/evidence.py — durable store outside worktree (executions/<id>/events.jsonl + artifacts/).
- sdd_coder/summary.py — per-seat roll-up (time/tokens) exists; no test roll-up.
- models/base.py:510 DevelopmentOutput — files_changed/commit_shas/summary, no test results.
