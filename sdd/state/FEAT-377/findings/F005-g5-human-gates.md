---
id: F005
query: "G5 — Declared human gates never opened"
type: code_review
verdict: CONFIRMED
---

## G5: plan_approval + revision_approval gates declared but never opened

**Verdict: CONFIRMED**

### Evidence

1. **`session_state.py:166-172`** — `GateKind` declares 5 values:
   - `manual_criterion` — USED (qa.py:627)
   - `deployment_approval` — USED (deployment_handoff.py:262)
   - `review_escalation` — USED (qa.py:508)
   - `revision_approval` — **NEVER opened**
   - `plan_approval` — **NEVER opened**

2. **`runner.py:71-76`** — TTL entries exist for both:
   `DEV_LOOP_GATE_TTL_REVISION`, `DEV_LOOP_GATE_TTL_PLAN`
   Wired into `gate_ttl_for()` but never called.

3. **Exhaustive grep** — only 3 gate kinds ever passed to `open_gate`:
   `deployment_approval`, `review_escalation`, `manual_criterion`.

4. Neither `research.py` nor `revision_handoff.py` contains `open_gate`.

5. **`session_state.py:222-228`** — intended semantics documented:
   `plan_approval` is advisory (fail-open), `revision_approval` is
   fail-closed. Infrastructure built, never consumed.
