# Agents

Drop-in agent modules discovered at startup by the `BotManager` and exposed
over the AgentTalk REST API (`POST /api/v1/agents/chat/{agent_id}`). Each file
registers one or more `Agent` subclasses via `@register_agent`.

| File | Agent id | Purpose |
|------|----------|---------|
| `finance.py` | `finance_agent` | NetSuite ERP via MCP |
| `odoo.py` | `odoo_agent` | Odoo ERP via toolkit |
| `operator.py` | `operator` | Per-user Office365 assistant |
| `expense_approval.py` | `expense_approval` | Human-in-the-loop expense/refund approval with **Tier 1 → Tier 2 escalation** |

---

## Human-in-the-Loop escalation (Tier 1 → Tier 2)

The `expense_approval` agent demonstrates a real, end-to-end Human-in-the-Loop
(HITL) flow. When the agent needs a human decision (e.g. approve a refund above
a threshold) it does **not** answer on its own — it routes the decision through a
tiered **escalation policy** managed by `HumanInteractionManager`
(`parrot.human.manager`).

```
Web user ──POST /chat/expense_approval──► Agent
                                            │  needs approval
                                            ▼
                            ┌──────────── Tier 1 ────────────┐
                            │  Microsoft Teams approval card  │
                            │  (Approve / Reject / Escalate)  │
                            └────────────────┬───────────────┘
                  approved/rejected │        │ no reply in time  OR  "Escalate" tapped
                                    │        ▼
                                    │   ┌──────────── Tier 2 ────────────┐
                                    │   │  Email to finance / on-call     │
                                    │   │  (one-way NOTIFY)               │
                                    │   └────────────────┬───────────────┘
                                    ▼                    ▼
                              Agent resumes ◄──── decision / escalation result
```

### Tier 1 — Teams approval (interactive)

- Action type: **`INTERACT`** dispatched on the **`teams`** channel
  (`TeamsHumanChannel`).
- The approver receives a proactive 1:1 Adaptive Card with
  **✅ Approve / ❌ Reject** buttons (plus an **Escalate** button because the
  interaction is policy-bound).
- The card submit comes back through the Teams HITL webhook
  (`/api/teams-hitl/messages`), resolves the interaction, and the agent
  continues.

### Tier 2 — Email escalation (one-way)

- Action type: **`NOTIFY`** with `action_metadata = {"kind": "email", ...}`,
  handled by `NotifyAction` → `EmailBackend` (async SMTP via `aiosmtplib`).
- A notification email is sent to the second-level approver(s); the agent
  resumes immediately with the escalation result (fire-and-forget — no reply is
  awaited at Tier 2).

### What triggers the jump to Tier 2

The interaction is created with `timeout_action = ESCALATE`, so Tier 2 fires when:

1. **Timeout** — the Teams approver does not respond within the Tier 1 window
   (`tier.timeout`), or
2. **Explicit escalate** — the approver taps the card's **Escalate** button
   (the `ESCALATE_OPTION_KEY` sentinel routes through `manager.advance_chain`).

A plain **Reject** is *not* an escalation: it resolves Tier 1 with a "denied"
decision and the agent reports the rejection back to the web caller.

> Severity (`low | normal | high | critical`) selects the **starting** tier via
> `EscalationPolicy.select_starting_tier`. A `critical` request can skip Tier 1
> and start straight at the email tier if Tier 1 declares a higher
> `min_severity`.

---

## Configuration

### 1. Tier 1 — Teams HITL bot

The Teams channel is wired with `setup_teams_hitl(app, manager, TeamsHitlConfig())`.
`TeamsHitlConfig` reads everything from the environment (navconfig), so set:

| Variable | Description |
|----------|-------------|
| `MSTEAMS_HITL_APP_ID` | Microsoft App ID of the dedicated HITL bot |
| `MSTEAMS_HITL_APP_PASSWORD` | Client secret for the HITL bot |
| `MSTEAMS_TENANT_ID` | AAD tenant id (single-tenant apps) |
| `MSTEAMS_GRAPH_CLIENT_ID` | Graph app id used for email → AAD resolution |
| `MSTEAMS_GRAPH_CLIENT_SECRET` | Graph app secret |
| `MSTEAMS_GRAPH_TENANT_ID` | Tenant id for the Graph app |
| `REDIS_URL` | Redis used for interaction state + conversation references |

The HITL bot must be installed in the tenant so it can open proactive 1:1 chats
with approvers (recipients are addressed by **email**).

### 2. Tier 2 — SMTP email

The email backend is configured on the manager's `NotifyAction`. The agent reads
SMTP settings from the environment:

| Variable | Default | Description |
|----------|---------|-------------|
| `HITL_SMTP_HOST` | `localhost` | SMTP server hostname |
| `HITL_SMTP_PORT` | `25` | SMTP port (587 STARTTLS / 465 implicit TLS) |
| `HITL_SMTP_USERNAME` | — | SMTP auth user (optional) |
| `HITL_SMTP_PASSWORD` | — | SMTP auth password (optional) |
| `HITL_SMTP_FROM` | `parrot-hitl@parrot.local` | `From:` address |
| `HITL_SMTP_STARTTLS` | `false` | Use STARTTLS (port 587) |
| `HITL_SMTP_SSL` | `false` | Use implicit TLS/SSL (port 465) |

### 3. The escalation policy & approvers

Tier targets are set when the policy is built (see the agent's `configure()`):

| Variable | Description |
|----------|-------------|
| `EXPENSE_TIER1_APPROVER` | Teams email of the first-level approver (Tier 1) |
| `EXPENSE_TIER2_EMAILS` | Comma-separated emails for the Tier 2 escalation |
| `EXPENSE_TIER1_TIMEOUT` | Seconds to wait for the Teams reply before escalating (e.g. `180`) |

Roughly, the policy is assembled like this:

```python
from parrot.human.models import (
    EscalationPolicy, EscalationTier, EscalationActionType,
)

policy = EscalationPolicy(
    name="expense-teams-then-email",
    tiers=[
        EscalationTier(                       # Tier 1 — Teams approval
            level=1,
            name="Teams Approval",
            channel_type="teams",
            action_type=EscalationActionType.INTERACT,
            target_humans=[tier1_approver_email],
            timeout=tier1_timeout_seconds,
        ),
        EscalationTier(                       # Tier 2 — Email escalation
            level=2,
            name="Email Escalation",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={
                "kind": "email",
                "to": tier2_emails,
                "subject_template": "Expense escalation: {question}",
            },
            timeout=3600,
        ),
    ],
)
# Registered on the process-wide manager so the tool can reference it by id:
manager._policies[policy.policy_id] = policy
```

The HITL approval tool then references the policy and declares a severity; the
manager picks the starting tier and handles the Tier 1 → Tier 2 transition
automatically.

> If any Teams/SMTP variable is missing, the agent logs a warning and degrades
> gracefully (the tier that lacks credentials is skipped) so the rest of the
> agent still runs.
