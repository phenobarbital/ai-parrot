# TASK-152: CIO Toolset Integration

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-151
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Wire options toolkit tools into CIO agent's available toolset.
> CIO must be able to call place_iron_butterfly, place_iron_condor, etc.

---

## Scope

- Add AlpacaOptionsToolkit to CIO agent's tool list
- Ensure toolkit is instantiated with paper=True by default
- Verify tools appear in CIO's available tools

**NOT in scope**: Prompt changes (done in TASK-151).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/swarm.py` | MODIFY | Add options tools to CIO |
| `parrot/finance/agents/analysts.py` | MODIFY | If CIO defined there |

---

## Implementation Notes

### Tool Registration
```python
from parrot.finance.tools.alpaca_options import AlpacaOptionsToolkit

# In CIO agent creation
options_toolkit = AlpacaOptionsToolkit(paper=True)
cio_tools = [
    *existing_tools,
    *await options_toolkit.get_tools(),
]
```

---

## Acceptance Criteria

- [x] AlpacaOptionsToolkit instantiated for CIO
- [x] Paper mode enabled by default
- [x] Options tools appear in CIO's tool list
- [x] CIO can invoke place_iron_butterfly in tests
- [x] CIO can invoke place_iron_condor in tests

---

## Completion Note

Integrated AlpacaOptionsToolkit into the CIO agent in `parrot/finance/swarm.py`:

**Changes Made:**

1. **Import added** (line 60):
   ```python
   from .tools.alpaca_options import AlpacaOptionsToolkit
   ```

2. **CIO agent creation updated** (configure method):
   - Created `self._options_toolkit = AlpacaOptionsToolkit(paper=True)`
   - Retrieved tools via `options_tools = await self._options_toolkit.get_tools()`
   - Passed tools to CIO agent: `tools=options_tools`
   - Enabled tool usage: `use_tools=True`

**Tools Now Available to CIO:**
- `get_account` — Alpaca account info
- `get_options_chain` — Options chain with Greeks
- `get_options_positions` — Current options positions
- `place_iron_butterfly` — Place Iron Butterfly strategy
- `place_iron_condor` — Place Iron Condor strategy
- `close_options_position` — Close multi-leg position

**Verification:**
- Import successful
- Toolkit instantiates with paper=True
- Ruff linting passes
