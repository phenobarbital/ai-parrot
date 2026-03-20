# TASK-190: InvestmentPolicyStatement Dataclass

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: —
**Assigned-to**: claude-session

---

## Context

> Add `InvestmentPolicyStatement` to `parrot/finance/schemas.py` — the foundational
> dataclass that all other FEAT-027 tasks depend on.

---

## Scope

- Add `InvestmentPolicyStatement` dataclass with all fields from the spec
- Implement `from_yaml(cls, path)` classmethod using `yaml.safe_load`
- Implement `to_prompt_block() -> str` that renders only non-empty fields into an XML block
- Export via `__all__` in `schemas.py`
- Ensure `pyyaml` is in `pyproject.toml` (add via `uv add pyyaml` if missing)

**NOT in scope**: Injecting the block into any agent prompt (done in TASK-191/192/193).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/schemas.py` | MODIFY | Add `InvestmentPolicyStatement` dataclass and helpers |
| `pyproject.toml` | MODIFY if needed | Ensure `pyyaml` dependency is present |

---

## Implementation Notes

### Fields
```python
@dataclass
class InvestmentPolicyStatement:
    allowed_asset_classes: list[str] = field(default_factory=list)
    allowed_exchanges: list[str] = field(default_factory=list)
    blocked_tickers: list[str] = field(default_factory=list)
    preferred_tickers: list[str] = field(default_factory=list)
    preferred_sectors: list[str] = field(default_factory=list)
    avoided_sectors: list[str] = field(default_factory=list)
    max_single_stock_pct: Optional[float] = None
    prefer_etf_over_single: Optional[bool] = None
    default_time_horizon: Optional[str] = None
    max_portfolio_beta: Optional[float] = None
    esg_filter: Optional[bool] = None
    custom_directives: str = ""
```

### `to_prompt_block()` contract
- Returns `""` if ALL fields are empty/None/False/empty-string
- Otherwise returns `<investment_policy>...</investment_policy>` XML block
- Section headers only rendered if at least one field in that section is non-empty
- Booleans render as `yes` / `no`
- Lists render as comma-separated inline strings

### `from_yaml()` contract
- Use `yaml.safe_load()` — never `yaml.load()`
- Unknown YAML keys should raise `TypeError` (dataclass default behavior is fine)

---

## Acceptance Criteria

- [ ] `InvestmentPolicyStatement` importable from `parrot.finance.schemas`
- [ ] `to_prompt_block()` returns `""` when all fields are defaults
- [ ] `to_prompt_block()` returns block containing `<investment_policy>` and `</investment_policy>` when any field is set
- [ ] `preferred_tickers`, `blocked_tickers`, `custom_directives`, `esg_filter` all appear in rendered block when set
- [ ] `from_yaml(path)` loads a YAML file correctly
- [ ] Empty/None fields are omitted from rendered block
- [ ] `InvestmentPolicyStatement` added to `__all__` in `schemas.py`
- [ ] `ruff check parrot/finance/schemas.py` passes

---

## Agent Instructions

1. Check if `pyyaml` is in `pyproject.toml`; if not run `source .venv/bin/activate && uv add pyyaml`
2. Read `parrot/finance/schemas.py` to find correct insertion point (after existing dataclasses, before factory functions)
3. Implement the dataclass following the field list above
4. Implement `to_prompt_block()` — build sections conditionally
5. Implement `from_yaml()` classmethod
6. Add to `__all__`
7. Run `source .venv/bin/activate && python -c "from parrot.finance.schemas import InvestmentPolicyStatement; ips = InvestmentPolicyStatement(preferred_tickers=['AAPL'], custom_directives='No biotech.'); print(ips.to_prompt_block())"`
8. Run `ruff check parrot/finance/schemas.py`
