# TASK-169: Add Memo Tools to Analyst Toolkit

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (1h)
**Depends-on**: TASK-167, TASK-168
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Integrate memo query tools into the analyst toolkit.
> Enables analysts to reference historical investment decisions.

---

## Scope

- Add memo tools to `AnalystToolkit` or appropriate toolkit
- Ensure tools available in analyst agent's tool list
- Update toolkit docstring

**NOT in scope**: Prompt engineering for using memo tools.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/__init__.py` | MODIFY | Export memo tools |
| `parrot/finance/prompts.py` | MODIFY | Add memo tool hints to analyst prompt |

---

## Implementation Notes

### Tool Registration

If using a toolkit class:

```python
# parrot/finance/tools/__init__.py

from .memo_tools import get_recent_memos, get_memo_detail

# Add to toolkit exports
ANALYST_TOOLS = [
    # ... existing tools ...
    get_recent_memos,
    get_memo_detail,
]
```

### Prompt Update

Add to analyst prompt:

```python
# parrot/finance/prompts.py

ANALYST_MEMO_TOOLS = """
## Historical Memo Tools

You have access to historical investment memos:

- `get_recent_memos(days=7, ticker=None)`: Get recent memo summaries
- `get_memo_detail(memo_id)`: Get full memo details

Use these to:
- Reference past decisions on a ticker
- Check what was recommended in similar market conditions
- Verify execution history of recommendations
"""
```

---

## Acceptance Criteria

- [x] Memo tools exported from tools package
- [x] Tools available to analyst agent
- [x] Toolkit docstring updated
- [x] Prompt includes guidance on memo tool usage
- [x] Existing analyst functionality unchanged

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

- `parrot/finance/swarm.py`: Added import of `get_recent_memos`, `get_memo_detail` from `.tools.memo_tools`.
  Updated `_get_analyst_query_tools()` to include both memo tools alongside existing research tools (5 tools total).
- `parrot/finance/prompts.py`: Added `<memo_tools>` section to `ANALYST_QUERY_PREAMBLE` documenting
  `get_recent_memos` and `get_memo_detail` with usage guidance.
- `parrot/finance/tools/__init__.py`: Updated module docstring to mention memo query tools.
