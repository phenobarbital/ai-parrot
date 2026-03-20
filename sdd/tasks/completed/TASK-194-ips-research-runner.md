# TASK-194: IPS Parameter in Research Runner

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-193
**Assigned-to**: claude-session

---

## Context

> Expose `ips` at the research runner entry point so callers (demos, CLI, integrations)
> can pass an `InvestmentPolicyStatement` without reaching into swarm internals.

---

## Scope

- Identify the public entry point(s) in `parrot/finance/research_runner.py`
- Add `ips: InvestmentPolicyStatement | None = None` parameter
- Pass it down to swarm construction

**NOT in scope**: Demo integration (TASK-195), CLI (out of scope for this feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/research_runner.py` | MODIFY | Add `ips` param to runner entry point(s) |

---

## Implementation Notes

- Read `research_runner.py` to identify the main async function / class entry point
- The IPS should flow: `research_runner(ips=...) → TradingSwarm(ips=...) → agents`
- Default `ips=None` must not change existing behavior

---

## Acceptance Criteria

- [ ] Research runner entry point accepts `ips: InvestmentPolicyStatement | None = None`
- [ ] `ips` is passed to `TradingSwarm` (or equivalent)
- [ ] Calling runner without `ips` argument works identically to current behavior
- [ ] `ruff check parrot/finance/research_runner.py` passes

---

## Agent Instructions

1. Read `parrot/finance/research_runner.py`
2. Add `ips` parameter and thread to swarm
3. Run import check:
   ```bash
   source .venv/bin/activate
   python -c "from parrot.finance.research_runner import ResearchRunner; print('OK')"
   ```
   (adjust class/function name to what exists)
4. Run `ruff check parrot/finance/research_runner.py`
