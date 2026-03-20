# TASK-193: IPS Threading Through TradingSwarm

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-191, TASK-192
**Assigned-to**: claude-session

---

## Context

> Wire `ips` through `TradingSwarm` (or equivalent swarm construction function)
> so that when a swarm is built, the IPS is passed to all analyst and CIO factory calls.

---

## Scope

- Identify the swarm construction entry point in `parrot/finance/swarm.py`
- Add `ips: InvestmentPolicyStatement | None = None` to the constructor / factory
- Pass `ips=ips` when calling `create_macro_analyst()`, `create_equity_analyst()`,
  `create_crypto_analyst()`, `create_sentiment_analyst()`, `create_risk_analyst()`,
  `create_cio()`, and the Secretary factory

**NOT in scope**: Research runner or demo (TASK-194/195).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/swarm.py` | MODIFY | Add `ips` param and thread to all factory calls |

---

## Implementation Notes

- Read `swarm.py` to understand how agents are instantiated (inline vs. factory calls)
- If agents are created in `__init__`, add `ips` to `__init__` signature
- If agents are created in a `build()` / `configure()` method, add `ips` there
- If `TradingSwarm` receives pre-built agent instances rather than constructing them
  internally, this task may be a no-op for `swarm.py` and the threading belongs in
  the caller — confirm during implementation and adjust scope accordingly

---

## Acceptance Criteria

- [ ] `TradingSwarm(ips=None)` behaves identically to current behavior
- [ ] `TradingSwarm(ips=<populated IPS>)` passes the IPS to all analyst and CIO factory functions
- [ ] `ruff check parrot/finance/swarm.py` passes
- [ ] No analyst or CIO agent is accidentally created without receiving the `ips`

---

## Agent Instructions

1. Read `parrot/finance/swarm.py` fully before editing
2. Locate where `create_*_analyst()`, `create_cio()`, and Secretary factory are called
3. Add `ips` parameter at the appropriate level and thread it down
4. Verify swarm can be instantiated without IPS:
   ```bash
   source .venv/bin/activate
   python -c "from parrot.finance.swarm import TradingSwarm; print('OK: import')"
   ```
5. Run `ruff check parrot/finance/swarm.py`
