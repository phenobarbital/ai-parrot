# TASK-192: IPS Injection — CIO and Secretary Factory Functions

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: TASK-190
**Assigned-to**: claude-session

---

## Context

> Add `ips: InvestmentPolicyStatement | None = None` to `create_cio()` and
> `create_secretary()` (memo writer) factory functions.
> The IPS is injected as a policy guardrail so both the CIO's deliberation and
> the Secretary's memo output reflect the portfolio's investment philosophy.

---

## Scope

- `create_cio()` in `parrot/finance/agents/deliberation.py`
- `create_secretary()` (or equivalent memo writer factory) in `parrot/finance/agents/deliberation.py`

**NOT in scope**: Analyst factories (TASK-191), swarm threading (TASK-193).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/agents/deliberation.py` | MODIFY | Add `ips` param + injection to `create_cio()` and memo writer factory |

---

## Implementation Notes

### Same injection pattern as TASK-191
```python
def create_cio(ips: InvestmentPolicyStatement | None = None) -> Agent:
    system_prompt = CIO_ARBITER
    if ips:
        block = ips.to_prompt_block()
        if block:
            system_prompt = system_prompt + "\n\n" + block
    return Agent(..., system_prompt=system_prompt, ...)
```

### Secretary note
The Secretary / Memo Writer should also receive the IPS so that investment memos
explicitly reference policy-compliant framing (e.g., ESG filters, preferred sectors).
Apply the same injection pattern.

### Zero-regression contract
When `ips=None`, `system_prompt` must equal the original constant exactly.

---

## Acceptance Criteria

- [ ] `create_cio(ips=None)` → `agent.system_prompt == CIO_ARBITER`
- [ ] `create_cio(ips=<populated IPS>)` → `agent.system_prompt` contains `<investment_policy>` block
- [ ] Same two criteria apply to the Secretary / Memo Writer factory
- [ ] `ruff check parrot/finance/agents/deliberation.py` passes

---

## Agent Instructions

1. Read `parrot/finance/agents/deliberation.py` to find all agent factory functions
2. Identify both CIO and Secretary factory function names
3. Add `ips` param and conditional injection to both
4. Run zero-regression check for each:
   ```bash
   source .venv/bin/activate
   python -c "
   from parrot.finance.agents.deliberation import create_cio
   from parrot.finance.prompts import CIO_ARBITER
   a = create_cio(ips=None)
   assert a.system_prompt == CIO_ARBITER
   print('OK: CIO no regression')
   "
   ```
5. Run `ruff check parrot/finance/agents/deliberation.py`
