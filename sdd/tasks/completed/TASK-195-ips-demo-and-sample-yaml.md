# TASK-195: IPS Demo Integration and Sample YAML

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-194
**Assigned-to**: claude-session

---

## Context

> Show IPS usage in `demo_full_cycle.py` and provide a sample `ips_sample.yaml`
> that users can copy and customise. Demonstrates both inline construction and YAML loading.

---

## Scope

- Modify `parrot/finance/demo_full_cycle.py` to import and use `InvestmentPolicyStatement`
- Create `examples/ips_sample.yaml` with a realistic sample IPS
- Show both inline construction and YAML loading paths in the demo

**NOT in scope**: Production CLI integration, persistent IPS storage.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/demo_full_cycle.py` | MODIFY | Import IPS, construct inline, pass to runner |
| `examples/ips_sample.yaml` | CREATE | Sample IPS YAML file |

---

## Sample YAML content (`examples/ips_sample.yaml`)

```yaml
# Investment Policy Statement — sample configuration
# Copy and edit this file to define your portfolio's investment philosophy.

allowed_asset_classes: [equity, etf]
allowed_exchanges: [NASDAQ, NYSE]
blocked_tickers: [DOGE, SHIB, GME]
preferred_tickers: [AAPL, MSFT, SPY, QQQ]

preferred_sectors: [technology, healthcare]
avoided_sectors: [energy, tobacco, weapons]
max_single_stock_pct: 5.0
prefer_etf_over_single: true

default_time_horizon: swing
max_portfolio_beta: 1.2
esg_filter: true

custom_directives: |
  Prefer momentum plays over value.
  Avoid biotech pre-FDA approval events.
  Do not initiate new positions during earnings week without UNANIMOUS consensus.
  Core holdings (AAPL, MSFT, SPY) require STRONG_MAJORITY to reduce.
```

---

## Implementation Notes

### Demo pattern
```python
from parrot.finance.schemas import InvestmentPolicyStatement

# Option A — inline
ips = InvestmentPolicyStatement(
    preferred_tickers=["AAPL", "MSFT", "SPY"],
    blocked_tickers=["DOGE", "SHIB"],
    preferred_sectors=["technology", "healthcare"],
    esg_filter=True,
    custom_directives=(
        "Prefer momentum over value. "
        "No biotech pre-FDA. "
        "No new positions during earnings week without UNANIMOUS consensus."
    ),
)

# Option B — from YAML
# ips = InvestmentPolicyStatement.from_yaml("examples/ips_sample.yaml")
```

Pass `ips` to the research runner / swarm construction in the demo.

---

## Acceptance Criteria

- [ ] `demo_full_cycle.py` imports and uses `InvestmentPolicyStatement`
- [ ] Demo shows inline construction (active) and YAML loading (commented as alternative)
- [ ] `examples/ips_sample.yaml` exists and is valid YAML
- [ ] `InvestmentPolicyStatement.from_yaml("examples/ips_sample.yaml")` loads without error
- [ ] `ruff check parrot/finance/demo_full_cycle.py` passes

---

## Agent Instructions

1. Read `parrot/finance/demo_full_cycle.py` to understand current structure
2. Add IPS construction near top of demo (before swarm/runner setup)
3. Pass `ips` to the runner call
4. Create `examples/ips_sample.yaml` with sample content above
5. Verify YAML loads:
   ```bash
   source .venv/bin/activate
   python -c "
   from parrot.finance.schemas import InvestmentPolicyStatement
   ips = InvestmentPolicyStatement.from_yaml('examples/ips_sample.yaml')
   print('Loaded:', ips.preferred_tickers)
   print(ips.to_prompt_block()[:200])
   "
   ```
6. Run `ruff check parrot/finance/demo_full_cycle.py`
