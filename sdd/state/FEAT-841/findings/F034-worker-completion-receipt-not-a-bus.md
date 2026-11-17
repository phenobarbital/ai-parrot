---
id: F034
query_id: Q003
type: wiki_query
intent: "Orient: how sdd-worker finishes a feature — last task close, review checkpoint, notification to host."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 1500
parent_id: null
depth: 1
merged_from: [FW-005]
---

# F034 — The worker's only completion signal is a best-effort desktop receipt (FEAT-793): record_completion binds to Git HEAD in a per-launch cache and a Stop hook notifies the host once — there is no event on any bus and the worker never pushes

## Summary

Q003 top hits: `test_worker_prompt_orchestrator.py` (1.00), `TASK-5124-worker-notification-protocol.md` (0.66), `TASK-5122-worker-completion-receipt.md` (0.32), spec `tmux-notify-worker.spec.md` (FEAT-793). The worker's `## Completion` section (`.claude/agents/sdd-worker.md:624`) ends with: file deferred findings (a `critical` one "blocks /sdd-done", L709) · **"Do NOT push"** (L715, sandbox has no route to github.com) · optional `"$PARROT_SDD_NOTIFY_PYTHON" -S "$PARROT_SDD_NOTIFY_HELPER" --complete` (L724) · print summary. `worker_notification.py` (stdlib only) implements `configure_notification` (launch context + quoted Stop command), `record_completion(env)` (atomic receipt in the session cache), `_receipt` ("strict receipt matches context and the current Git HEAD"), `_claim_attempt` (exactly-once marker), `handle_stop` (one desktop notification, never propagates errors). TASK-5124 scope note: "NOT in scope: … merge/closeout approval". So "the worker is the explicit witness" of completion, but the witness is a 0600 JSON file on the host, not a ledger event — `work.completed` has no precedent yet, but the HEAD-bound receipt pattern is exactly the binding a verdict needs.

## Citations

- path: `.claude/agents/sdd-worker.md`
  lines: 624-730
  symbol: `## Completion`
  excerpt: |
    L709: defer one, file it as `critical` — it blocks `/sdd-done`
    L715: 2. **Do NOT push.** The sandbox has no route to `github.com`
    L724: "$PARROT_SDD_NOTIFY_PYTHON" -S "$PARROT_SDD_NOTIFY_HELPER" --complete
- path: `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py`
  lines: 1-1
  symbol: `record_completion`
  wiki_page_id: file:packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py
  excerpt: |
    def _head(worktree): Return the validated current Git HEAD hash.
    def configure_notification(cache): Write validated launch context and return a quoted Stop command.
    def record_completion(env): Atomically record eligible feature completion in the existing session cache.
    def _receipt(cache, context): Return whether a strict receipt matches context and the current Git HEAD.
    def _claim_attempt(cache): Exclusively create the persistent delivery-attempt marker before sending.
    def handle_stop(payload): Attempt one notification for a valid Stop and receipt without propagating errors.
- path: `sdd/tasks/completed/TASK-5124-worker-notification-protocol.md`
  lines: 1-40
  symbol: `TASK-5124 Scope`
  wiki_page_id: file:sdd/tasks/completed/TASK-5124-worker-notification-protocol.md
  score: 0.66
  excerpt: |
    The worker is the explicit witness that task execution, child settlement, review and push finished;
    the receipt cannot be inferred from Stop or index status alone.
    **NOT in scope**: ... task-scoped completion behavior or merge/closeout approval.
- path: `sdd/specs/tmux-notify-worker.spec.md`
  lines: 1-1
  symbol: `FEAT-793 tmux worker completion notifications`
  wiki_page_id: file:sdd/specs/tmux-notify-worker.spec.md
  score: 0.12
- path: `packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py`
  lines: 1-1
  symbol: `test_worker_notification_protocol_order`
  wiki_page_id: sym:packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py#test_worker_notification_protocol_order
  excerpt: |
    Only feature completion records after push and before the final summary.

## Notes

TASK-5124's blueprint text said "after step 2 pushed successfully", but the live worker L715 says "Do NOT push" — the twin test name still says "after push". [cross-lane: type=read, intent=codebase lane Q017 should quote the current Completion step order verbatim (push vs no-push) since the receipt placement is the insertion point for work.completed.] Both worker twins (`.claude/agents/sdd-worker.md` and the shipped asset) are byte-identical and must change together.
