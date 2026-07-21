# F006 — DeploymentHandoffNode: unguarded Jira transition confirmed

**Query**: Q009 (read nodes/deployment_handoff.py:40-180)
**File**: packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py

## Facts
- `execute` (:89) sequence: (1) push branch (:118-126, blocked on failure) →
  (2) open DRAFT PR with retry-once (:128-160, blocked on failure) →
  (3) **Jira transition, unconditional on the success path** (:164-175,
  `transition_issue_with_candidates` with
  `conf.DEV_LOOP_JIRA_TRANSITIONS_READY`; failure only logs + continues) →
  (4) Jira comment with PR link (:177+).
- Returns `{"status": "ready_to_deploy", "pr_url", "pr_number"}` or
  `{"status": "blocked", "error"}`; `pr_number` feeds the revision loop.
- No human approval anywhere in-loop — confirms brainstorm problem stmt 3.

## Gate insertion point (verified)
Between step 2 (PR exists → `pr_url`/`pr_number` known, evidence available
for the gate's `payload_ref`) and step 3 (Jira transition). A rejected or
expired `deployment_approval` gate must route to `failure_handler`; the
node can surface that by returning a distinct status (e.g.
`{"status": "rejected"}`) routed by a CEL edge, or by raising to trigger
the existing `on_error` edge (definition.py routes HANDOFF on_error →
FAILURE).
