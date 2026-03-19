# TASK-191: IPS Injection — Analyst Factory Functions

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-190
**Assigned-to**: claude-session

---

## Context

> Add `ips: InvestmentPolicyStatement | None = None` to all analyst factory functions.
> When provided, append `ips.to_prompt_block()` to the system prompt before passing to `Agent`.

---

## Scope

All five analyst factory functions in `parrot/finance/agents/analysts.py`:
- `create_macro_analyst()`
- `create_equity_analyst()`
- `create_crypto_analyst()`
- `create_sentiment_analyst()`
- `create_risk_analyst()`

And the generic `create_analyst()` factory if it exists.

**NOT in scope**: CIO or Secretary injection (TASK-192/193).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/agents/analysts.py` | MODIFY | Add `ips` param + prompt injection to all analyst factories |

---

## Implementation Notes

### Injection pattern (same for all factories)
```python
from parrot.finance.schemas import InvestmentPolicyStatement

def create_macro_analyst(
    tools: list | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> Agent:
    system_prompt = ANALYST_MACRO
    if ips:
        block = ips.to_prompt_block()
        if block:
            system_prompt = system_prompt + "\n\n" + block
    return Agent(
        ...
        system_prompt=system_prompt,
        ...
    )
```

### Zero-regression contract
When `ips=None`, `system_prompt` must be **byte-for-byte** equal to the original constant.
Do not add trailing newlines or other mutations when `ips` is None.

---

## Acceptance Criteria

- [ ] All 5 analyst factories accept `ips: InvestmentPolicyStatement | None = None`
- [ ] When `ips=None`, `agent.system_prompt == ANALYST_MACRO` (and equivalents) — no regression
- [ ] When `ips` has content, `agent.system_prompt` ends with the `<investment_policy>` block
- [ ] `ruff check parrot/finance/agents/analysts.py` passes
- [ ] Import `InvestmentPolicyStatement` at top of file (not inline)

---

## Agent Instructions

1. Read `parrot/finance/agents/analysts.py` fully before editing
2. Add `InvestmentPolicyStatement` import at top
3. For each factory function: add `ips` param and conditional prompt injection
4. Verify zero-regression with:
   ```bash
   source .venv/bin/activate
   python -c "
   from parrot.finance.agents.analysts import create_macro_analyst
   from parrot.finance.prompts import ANALYST_MACRO
   a = create_macro_analyst(ips=None)
   assert a.system_prompt == ANALYST_MACRO, 'REGRESSION: system_prompt changed when ips=None'
   print('OK: no regression')
   "
   ```
5. Verify injection:
   ```bash
   python -c "
   from parrot.finance.schemas import InvestmentPolicyStatement
   from parrot.finance.agents.analysts import create_macro_analyst
   ips = InvestmentPolicyStatement(custom_directives='Test directive')
   a = create_macro_analyst(ips=ips)
   assert '<investment_policy>' in a.system_prompt
   print('OK: block injected')
   "
   ```
6. Run `ruff check parrot/finance/agents/analysts.py`
