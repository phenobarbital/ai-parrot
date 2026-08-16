---
id: F001
query: "G1 — QA failure edge topology"
type: code_review
verdict: CONFIRMED
---

## G1: No bounded repair loop from QA → development

**Verdict: CONFIRMED**

### Evidence

1. **`definition.py:104-111`** — QA has exactly two outbound edges:
   - `qa → deployment_handoff` (predicate: `result.passed == true`)
   - `qa → failure_handler` (predicate: `result.passed == false`)
   - No `qa → development` edge exists.

2. **`flow.py:343-345`** — imperative wiring mirrors declarative:
   ```python
   flow.add_edge("qa", "deployment_handoff", predicate=_qa_passed)
   flow.add_edge("qa", "failure_handler", predicate=_qa_failed)
   ```

3. **No retry counter** — grep for `qa_attempt`, `qa_retr`, `retry_count`,
   `max_qa`, `bounded_retry`, `repair_loop` across `dev_loop/` = zero hits.

4. **`failure_handler.py`** is terminal — posts Jira comment, transitions
   to "Needs Human Review", reassigns to escalation_assignee.

5. **Code-review auto-fix** (`qa.py:187-196`) re-runs deterministic criteria
   *within the same QA node execution* after code-review fixes — but this
   is not a graph-level `qa → development → qa` loop. If overall QA still
   fails, flow routes to `failure_handler`.

6. **Revision mode** (`_build_revision_definition`) is a separate flow, not
   a within-run retry. Its own QA failure also routes to `failure_handler`.

### Impact

Every fixable lint error, missed criterion, or flaky test costs a full
human round-trip (Jira escalation + manual fix or new revision run).
