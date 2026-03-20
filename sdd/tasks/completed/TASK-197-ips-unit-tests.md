# TASK-197: IPS Unit Tests

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-190, TASK-191, TASK-192
**Assigned-to**: claude-session

---

## Context

> Write the unit test suite for `InvestmentPolicyStatement` (dataclass, rendering,
> YAML loading) and for the analyst/CIO injection behaviour.

---

## Scope

- All tests from the spec §4 Test Specification
- Test file: `tests/test_investment_policy_statement.py`
- A YAML fixture file: `tests/fixtures/ips_fixture.yaml`

**NOT in scope**: Integration tests running a full swarm (too heavy for unit tests).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_investment_policy_statement.py` | CREATE | Full unit test suite |
| `tests/fixtures/ips_fixture.yaml` | CREATE | YAML fixture for from_yaml tests |

---

## Test Cases

### Dataclass & Rendering (Module 1)

| Test | Description |
|---|---|
| `test_ips_all_defaults_returns_empty_block` | `InvestmentPolicyStatement()` → `to_prompt_block() == ""` |
| `test_ips_renders_preferred_tickers` | `preferred_tickers=["AAPL"]` → block contains "AAPL" |
| `test_ips_renders_blocked_tickers` | `blocked_tickers=["DOGE"]` → block contains "DOGE" |
| `test_ips_renders_custom_directives` | `custom_directives="No biotech"` → block contains "No biotech" |
| `test_ips_omits_empty_list_sections` | Only `preferred_tickers` set → `avoided_sectors` section absent |
| `test_ips_esg_filter_yes` | `esg_filter=True` → block contains "yes" |
| `test_ips_esg_filter_no` | `esg_filter=False` → block contains "no" |
| `test_ips_block_has_xml_tags` | Any non-empty IPS → block starts with `<investment_policy>` and ends with `</investment_policy>` |
| `test_ips_from_yaml` | Load fixture → all populated fields match expected values |
| `test_ips_from_yaml_partial` | Fixture with only `preferred_tickers` → other fields default |

### Analyst Injection (Module 2)

| Test | Description |
|---|---|
| `test_analyst_no_ips_no_regression` | `create_macro_analyst(ips=None).system_prompt == ANALYST_MACRO` |
| `test_analyst_with_ips_injects_block` | `create_macro_analyst(ips=ips).system_prompt` contains `<investment_policy>` |
| `test_all_analyst_factories_accept_ips` | All 5 factories called with `ips=ips` without error |

### CIO & Secretary Injection (Module 3)

| Test | Description |
|---|---|
| `test_cio_no_ips_no_regression` | `create_cio(ips=None).system_prompt == CIO_ARBITER` |
| `test_cio_with_ips_injects_block` | `create_cio(ips=ips).system_prompt` contains `<investment_policy>` |
| `test_secretary_with_ips_injects_block` | Secretary factory with `ips` → `system_prompt` contains `<investment_policy>` |

---

## Fixture YAML (`tests/fixtures/ips_fixture.yaml`)

```yaml
preferred_tickers: [AAPL, MSFT]
blocked_tickers: [DOGE]
preferred_sectors: [technology]
esg_filter: true
custom_directives: "Test directive only."
```

---

## Acceptance Criteria

- [ ] All tests in the table above are implemented
- [ ] All tests pass: `pytest tests/test_investment_policy_statement.py -v`
- [ ] No test imports implementation code from outside `parrot/finance/`
- [ ] Fixtures directory exists and `ips_fixture.yaml` is valid

---

## Agent Instructions

1. Create `tests/fixtures/ips_fixture.yaml` with content above
2. Create `tests/test_investment_policy_statement.py`
3. Import what's needed: `InvestmentPolicyStatement`, analyst factories, `ANALYST_MACRO`, `CIO_ARBITER`
4. Implement all tests from the table
5. Run: `source .venv/bin/activate && pytest tests/test_investment_policy_statement.py -v --no-header`
6. All tests must pass — fix any failures before marking task complete
