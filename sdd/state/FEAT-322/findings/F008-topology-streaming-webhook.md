# F008 — Topology, streaming, webhook & recent activity

**Queries**: Q014 (read definition.py, 171 lines), Q006 (read streaming.py:1-110
+ wiki TASK-879), Q011 (webhook.py head + route grep), Q013 (git log)

## Topology (definition.py)
- Node ids: `intent_classifier, bug_intake, research, development, qa,
  deployment_handoff, failure_handler, close` + `revision_handoff`
  (revision graph) (:36-44). **Matches the sketch's `NodeId` Literal 1:1.**
- CEL predicates route on node RESULTS: `result.kind == "bug"`,
  `result.passed == true|false` (:47-50) — QA gate outcomes must be folded
  into `QAReport.passed` before the node returns (see F005).
- `on_error` fan-in: all middle nodes (incl. HANDOFF) → `failure_handler`
  (:53, :118-121). Revision graph: development → qa → revision_handoff →
  close (:131-168).

## Streaming (streaming.py:1-110)
- Multiplexer fans in `flow:{run_id}:flow` + discovered
  `flow:{run_id}:dispatch:*` (SCAN, :90-110); WS query params
  `view=flow|dispatch|both`, `replay=true|false` (:19-22). Emits flat
  envelopes `{source, node_id, event_kind, ts, payload}` (:14-17).
  No snapshot/state mode — confirms brainstorm. `view="state"` slots in as
  a new ViewLiteral + a snapshot-then-envelopes connect path.

## Webhook (webhook.py)
- `register_pull_request_webhook` (:292) hooks
  `AutonomousOrchestrator.WebhookListener`; handles PR-closed cleanup and
  the PR-comment → revision-run trigger (dedup by head SHA). This is the
  existing "external command → runner" path; `resolve_gate` needs an
  equivalent client-command surface (WS or HTTP) on the runner — none
  exists today.

## Recent activity (git log, 6 weeks)
- FEAT-270 multi-dispatcher code review merged (touches qa.py, dispatcher,
  factories); Moonshot + Z.ai dispatchers added; FEAT-253 repo wiring.
  Files this feature touches are ACTIVE — re-verify anchors at /sdd-task
  time and keep worktrees short-lived.
