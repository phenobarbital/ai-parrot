# Feature Specification: Investment Policy Statement (IPS)

**Feature ID**: FEAT-027
**Date**: 2026-03-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Depends on**: FEAT-024 (Finance Research Collective Memory), FEAT-026 (Multi-Executor Integration)

---

## 1. Motivation & Business Requirements

### Problem Statement

The investment committee agents (analysts + CIO) currently operate with no awareness of the portfolio owner's investment philosophy, preferences, or constraints beyond the structural `ExecutorConstraints` (position sizing, drawdown limits, etc.). Those constraints are numerical guards — they cannot express:

- "We prefer momentum over value"
- "Avoid biotech pre-FDA approval"
- "Do not trade during earnings week without UNANIMOUS consensus"
- "No exposure to tobacco, fossil fuels, or weapons (ESG filter)"
- "MSFT, AAPL, and SPY are our core holdings — bias toward adding, not selling"

The result: analysts generate technically valid recommendations that may be misaligned with the client's actual investment philosophy, requiring manual intervention downstream.

### Goals

- Define a structured `InvestmentPolicyStatement` (IPS) dataclass in `schemas.py`
- Render it to a well-formed `<investment_policy>` XML block for prompt injection
- Inject it into the system prompt of every analyst and the CIO at agent creation time
- Support loading from a YAML file (`InvestmentPolicyStatement.from_yaml(path)`)
- Expose optional `ips` parameter in analyst and CIO factory functions
- Show usage in `demo_full_cycle.py`
- When no IPS is provided, inject nothing — no defaults, no silent fallbacks

### Non-Goals

- Enforcing IPS constraints programmatically (that is `ExecutorConstraints`'s job)
- Persisting IPS to a database or memo store
- A UI to edit the IPS (out of scope)
- Per-agent IPS (all analysts share the same IPS — it is portfolio-level)

---

## 2. Architectural Design

### Overview

```
InvestmentPolicyStatement          (new dataclass — schemas.py)
     │
     ├── from_yaml(path) → IPS     (classmethod — schemas.py)
     └── to_prompt_block() → str   (method — schemas.py)
              │
              └── "<investment_policy>...</investment_policy>"
                       │
           injected into system_prompt at agent creation
                       │
         ┌─────────────┼──────────────────┐
   Macro Analyst  Equity Analyst    CIO Arbiter  ...
  (create_macro_analyst)        (create_cio)
```

### Injection Point

The `<investment_policy>` block is appended to the **static system prompt** at agent creation. This is the simplest and most reliable approach:

- No change to the `Agent` base class
- No change to the runtime message flow
- Survives tool calls and multi-turn conversations (system prompt is persistent)
- The block is appended after the existing prompt body, before the closing tag (if any), or simply concatenated

```python
# analysts.py — before
system_prompt = ANALYST_MACRO

# analysts.py — after
system_prompt = ANALYST_MACRO
if ips:
    system_prompt = system_prompt + "\n\n" + ips.to_prompt_block()
```

### IPS Prompt Block Format

```xml
<investment_policy>
INVESTMENT POLICY STATEMENT

This portfolio operates under the following investment policy.
You MUST align your analysis, recommendations, and scoring with these directives.

PERMITTED UNIVERSE
- Asset classes: equity, etf
- Exchanges: NASDAQ, NYSE
- Blocked tickers: ETH, DOGE, SHIB
- Preferred tickers (core holdings — bias toward adding): AAPL, MSFT, SPY

SECTOR PREFERENCES
- Preferred sectors: technology, healthcare
- Sectors to avoid: energy, tobacco, weapons, gambling

STYLE & SIZING
- Max single-stock allocation: 5.0% of portfolio
- Prefer ETFs over single stocks when equivalent exposure is achievable

TIME HORIZON & RISK
- Default time horizon: swing (days to weeks)
- Max portfolio beta: 1.2
- ESG filter active: yes — exclude companies flagged for environmental, social, or governance violations

CUSTOM DIRECTIVES
Preferimos momentum plays sobre value. Evitar biotech pre-FDA.
No operar durante earnings week sin consenso UNANIMOUS.
</investment_policy>
```

Fields omitted when empty/None are not rendered (no placeholder text).

### Data Model

```python
# schemas.py — new dataclass
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml

@dataclass
class InvestmentPolicyStatement:
    """Portfolio-level investment policy injected into every analyst and CIO prompt.

    All fields are optional. Only populated fields are rendered in the prompt block.
    Use `from_yaml(path)` to load from a YAML configuration file.
    Use `to_prompt_block()` to get the XML string for prompt injection.
    """

    # Universe
    allowed_asset_classes: list[str] = field(default_factory=list)   # ["equity", "etf"]
    allowed_exchanges: list[str] = field(default_factory=list)        # ["NASDAQ", "NYSE"]
    blocked_tickers: list[str] = field(default_factory=list)          # ["ETH", "DOGE"]
    preferred_tickers: list[str] = field(default_factory=list)        # ["AAPL", "MSFT", "SPY"]

    # Sector style
    preferred_sectors: list[str] = field(default_factory=list)        # ["tech", "healthcare"]
    avoided_sectors: list[str] = field(default_factory=list)          # ["energy", "tobacco"]
    max_single_stock_pct: Optional[float] = None                      # 5.0
    prefer_etf_over_single: Optional[bool] = None                     # True

    # Horizon & risk
    default_time_horizon: Optional[str] = None                        # "swing"
    max_portfolio_beta: Optional[float] = None                        # 1.2
    esg_filter: Optional[bool] = None                                 # True

    # Free-form — most powerful field
    custom_directives: str = ""
    # "Preferimos momentum plays sobre value. Evitar biotech pre-FDA.
    #  No operar durante earnings week sin consenso UNANIMOUS."

    @classmethod
    def from_yaml(cls, path: str | Path) -> "InvestmentPolicyStatement":
        """Load IPS from a YAML file."""
        data = yaml.safe_load(Path(path).read_text())
        return cls(**data)

    def to_prompt_block(self) -> str:
        """Render to <investment_policy> XML block for system prompt injection."""
        ...
```

### YAML File Format

```yaml
# ips.yaml — example
allowed_asset_classes: [equity, etf]
allowed_exchanges: [NASDAQ, NYSE]
blocked_tickers: [ETH, DOGE, SHIB]
preferred_tickers: [AAPL, MSFT, SPY]

preferred_sectors: [technology, healthcare]
avoided_sectors: [energy, tobacco]
max_single_stock_pct: 5.0
prefer_etf_over_single: true

default_time_horizon: swing
max_portfolio_beta: 1.2
esg_filter: true

custom_directives: |
  Preferimos momentum plays sobre value. Evitar biotech pre-FDA.
  No operar durante earnings week sin consenso UNANIMOUS.
```

### Integration Points

| Existing Component | Change Type | Notes |
|---|---|---|
| `parrot/finance/schemas.py` | add | New `InvestmentPolicyStatement` dataclass |
| `parrot/finance/agents/analysts.py` | modify | Accept `ips` param in all `create_*_analyst()` functions |
| `parrot/finance/agents/deliberation.py` | modify | Accept `ips` param in `create_cio()` |
| `parrot/finance/swarm.py` | modify | Thread `ips` through swarm construction |
| `parrot/finance/research_runner.py` | modify | Accept and pass `ips` to swarm |
| `parrot/finance/demo_full_cycle.py` | modify | Import and pass a sample IPS |
| `parrot/finance/__init__.py` | modify | Export `InvestmentPolicyStatement` |

---

## 3. Module Breakdown

### Module 1: InvestmentPolicyStatement Dataclass

- **Path**: `parrot/finance/schemas.py` (modify)
- **Responsibility**:
  - Add `InvestmentPolicyStatement` dataclass with all fields listed in §2
  - Implement `from_yaml(cls, path)` classmethod using `yaml.safe_load`
  - Implement `to_prompt_block() -> str` — renders only non-empty fields into the XML block shown in §2
  - Export via `__all__`
- **Depends on**: None
- **Notes**: `yaml` is already a standard/available dependency; if not, add `pyyaml` via `uv add pyyaml`

### Module 2: Analyst Factory Functions — IPS Parameter

- **Path**: `parrot/finance/agents/analysts.py` (modify)
- **Responsibility**:
  - Add `ips: InvestmentPolicyStatement | None = None` parameter to every `create_*_analyst()` function and to the generic `create_analyst()` factory
  - When `ips` is not None, append `ips.to_prompt_block()` to the system prompt string before passing to `Agent(system_prompt=...)`
  - No change to Agent base class
- **Depends on**: Module 1

### Module 3: CIO Factory Function — IPS Parameter

- **Path**: `parrot/finance/agents/deliberation.py` (modify)
- **Responsibility**:
  - Add `ips: InvestmentPolicyStatement | None = None` parameter to `create_cio()`
  - Same injection pattern as Module 2
- **Depends on**: Module 1

### Module 4: Swarm Threading

- **Path**: `parrot/finance/swarm.py` (modify)
- **Responsibility**:
  - Add `ips: InvestmentPolicyStatement | None = None` to `TradingSwarm.__init__()` (or equivalent construction function)
  - Pass `ips` when calling analyst and CIO factory functions
- **Depends on**: Modules 2, 3

### Module 5: Research Runner — IPS Parameter

- **Path**: `parrot/finance/research_runner.py` (modify)
- **Responsibility**:
  - Add `ips: InvestmentPolicyStatement | None = None` parameter to the runner entry point
  - Pass it down to swarm construction
- **Depends on**: Module 4

### Module 6: Demo Integration

- **Path**: `parrot/finance/demo_full_cycle.py` (modify)
- **Responsibility**:
  - Import `InvestmentPolicyStatement` from `parrot.finance.schemas`
  - Construct a sample IPS inline (preferred tickers, blocked tickers, custom directive)
  - Pass it to the research runner / swarm
  - Also show the YAML loading path with `InvestmentPolicyStatement.from_yaml("ips.yaml")`
- **Depends on**: Modules 1, 5

### Module 7: Exports

- **Path**: `parrot/finance/__init__.py` (modify)
- **Responsibility**: Export `InvestmentPolicyStatement`
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_ips_empty_renders_empty_block` | Module 1 | IPS with all defaults → `to_prompt_block()` returns a well-formed but minimal block (or empty string — define contract) |
| `test_ips_renders_preferred_tickers` | Module 1 | `preferred_tickers=["AAPL"]` → block contains "AAPL" |
| `test_ips_renders_blocked_tickers` | Module 1 | `blocked_tickers=["DOGE"]` → block contains "DOGE" |
| `test_ips_renders_custom_directives` | Module 1 | `custom_directives="No biotech"` → block contains "No biotech" |
| `test_ips_omits_empty_fields` | Module 1 | Empty lists and None fields are not rendered in block |
| `test_ips_from_yaml` | Module 1 | Load from fixture YAML → all fields populated correctly |
| `test_ips_from_yaml_missing_fields` | Module 1 | YAML with partial fields → remaining fields default correctly |
| `test_ips_esg_filter_rendered` | Module 1 | `esg_filter=True` → block contains "ESG filter active: yes" |
| `test_analyst_no_ips_uses_base_prompt` | Module 2 | `create_macro_analyst(ips=None)` → `system_prompt == ANALYST_MACRO` |
| `test_analyst_with_ips_appends_block` | Module 2 | `create_macro_analyst(ips=ips)` → `system_prompt` contains `<investment_policy>` |
| `test_all_analysts_accept_ips` | Module 2 | All 5 analyst factories accept `ips` without error |
| `test_cio_no_ips_uses_base_prompt` | Module 3 | `create_cio(ips=None)` → `system_prompt == CIO_ARBITER` |
| `test_cio_with_ips_appends_block` | Module 3 | `create_cio(ips=ips)` → `system_prompt` contains `<investment_policy>` |

### Verification Commands

```bash
source .venv/bin/activate

# Import check
python -c "
from parrot.finance.schemas import InvestmentPolicyStatement
ips = InvestmentPolicyStatement(
    preferred_tickers=['AAPL', 'MSFT'],
    blocked_tickers=['DOGE'],
    custom_directives='No biotech pre-FDA.'
)
print(ips.to_prompt_block())
"

# YAML load check
python -c "
from parrot.finance.schemas import InvestmentPolicyStatement
ips = InvestmentPolicyStatement.from_yaml('examples/ips_sample.yaml')
print('Loaded:', ips.preferred_tickers, ips.esg_filter)
"

# Analyst injection check
python -c "
from parrot.finance.schemas import InvestmentPolicyStatement
from parrot.finance.agents.analysts import create_macro_analyst
ips = InvestmentPolicyStatement(custom_directives='No earnings week.')
a = create_macro_analyst(ips=ips)
assert '<investment_policy>' in a.system_prompt
print('OK: investment_policy block injected')
"

# Run tests
pytest tests/ -k "ips or investment_policy" -v --no-header 2>&1 | head -60
```

---

## 5. Acceptance Criteria

- [ ] `InvestmentPolicyStatement` dataclass exists in `parrot/finance/schemas.py`
- [ ] `InvestmentPolicyStatement.from_yaml(path)` loads correctly from a YAML file
- [ ] `InvestmentPolicyStatement.to_prompt_block()` returns a non-empty string containing `<investment_policy>` and `</investment_policy>` tags
- [ ] Fields with empty lists or `None` values are omitted from the rendered block
- [ ] `custom_directives` always renders when non-empty
- [ ] All 5 analyst factory functions accept `ips: InvestmentPolicyStatement | None = None`
- [ ] `create_cio()` accepts `ips: InvestmentPolicyStatement | None = None`
- [ ] When `ips=None`, system prompts are byte-for-byte identical to the current baseline (no regression)
- [ ] When `ips` is provided, `<investment_policy>` block appears at end of system prompt
- [ ] `InvestmentPolicyStatement` is exported from `parrot/finance/__init__.py`
- [ ] `demo_full_cycle.py` demonstrates both inline construction and YAML loading
- [ ] No `InvestmentPolicyStatement` with default values is created implicitly anywhere
- [ ] All existing tests continue to pass
- [ ] New unit tests pass for all test cases in §4

---

## 6. Implementation Notes & Constraints

### Rendering Contract for `to_prompt_block()`

- Returns `""` (empty string) if ALL fields are empty/None/False — callers check truthiness before appending
- Otherwise returns the full `<investment_policy>...</investment_policy>` block
- Section headers (e.g. `PERMITTED UNIVERSE`) are only rendered if at least one field in that section is non-empty
- Boolean fields render as `yes` / `no` (not `True` / `False`)
- Lists render as comma-separated inline strings or bullet lines — pick one style, be consistent

### Why System Prompt (not instructions/context)

- `instructions` in the Agent is designed for per-run task context, not persistent policy
- System prompt is set once at agent creation and persists across all turns in a session
- This ensures the IPS cannot be overridden by tool results or user messages
- No changes to `AbstractBot` or `Agent` infrastructure required

### pyyaml Dependency

- Check if `pyyaml` is already in `pyproject.toml`. If not: `uv add pyyaml`
- Use `yaml.safe_load()` — never `yaml.load()` (security)

### Patterns to Follow

- Dataclass with `field(default_factory=list)` — same pattern as other dataclasses in `schemas.py`
- Optional fields typed as `Optional[T] = None` — consistent with `ExecutorConstraints`
- No `__post_init__` validation beyond type checking — IPS is advisory, not enforced

### Known Risks / Gotchas

- **Prompt length**: Long `custom_directives` + large ticker lists can significantly expand system prompts. Users should keep custom_directives concise (< 500 chars recommended, not enforced)
- **No enforcement**: IPS is advisory only — an analyst CAN still recommend a blocked ticker if its analysis strongly supports it. Enforcement belongs in `ExecutorConstraints` (out of scope here)
- **Stale IPS**: Once injected at agent creation, the IPS is baked into the system prompt. Dynamic IPS changes require recreating agents

---

## 7. Open Questions

- [x] Should `to_prompt_block()` return `""` when all fields empty, or still return the outer tags? — *Answer: return `""` so callers can check `if ips and ips.to_prompt_block()`*
- [x] Should `InvestmentPolicyStatement` fields use `AssetClass` enum or raw `str`? — *Answer: raw `str` for YAML compatibility and flexibility (users shouldn't need to know our internal enums)*
- [x] Where does the sample YAML file live? — *Answer: `examples/ips_sample.yaml` (new file, illustrative only)*
- [ ] Should the Secretary / Memo Writer agent also receive the IPS? — *Depends on whether memo output should reflect IPS preferences; owner: TBD*: As Security Guardtrail is preferable add the IPS to secretary.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-05 | Jesus Lara | Initial draft |
