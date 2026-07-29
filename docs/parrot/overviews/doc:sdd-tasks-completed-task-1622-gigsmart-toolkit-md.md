---
type: Wiki Overview
title: 'TASK-1622: GigSmartToolkit — AbstractToolkit for LLM Agents'
id: doc:sdd-tasks-completed-task-1622-gigsmart-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The main LLM-facing toolkit. Inherits `AbstractToolkit` and exposes 23 async
  methods
relates_to:
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.working_memory
  rel: mentions
- concept: mod:parrot_tools.gigsmart.toolkit
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.client
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.config
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.models.gig
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.queries.gigs
  rel: mentions
---

# TASK-1622: GigSmartToolkit — AbstractToolkit for LLM Agents

**Feature**: FEAT-253 — GigSmart Interface Toolkit
**Spec**: `sdd/specs/gigsmart-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (8-16h)
**Depends-on**: TASK-1621
**Assigned-to**: unassigned

---

## Context

The main LLM-facing toolkit. Inherits `AbstractToolkit` and exposes 23 async methods
as tools. Read methods return structured dicts; write methods are gated via
`confirming_tools`. Uses `@tool_schema` decorators for Pydantic input validation.
Implements Spec §2 Module 7.

---

## Scope

- Implement `GigSmartToolkit(AbstractToolkit)` with 23 tool methods
- Compose `GigSmartClient` (not inherit)
- Use `confirming_tools` frozenset for all write operations (HITL gate)
- Apply `@tool_schema` decorators with Pydantic input models
- Google-style docstrings on every method (becomes LLM tool description)
- Optional `WorkingMemoryToolkit` composition for DataFrame spilling
- Write unit tests with mocked client

**NOT in scope**: GraphQL client internals (TASK-1621), model definitions (TASK-1619).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gigsmart/__init__.py` | CREATE | Package init with exports |
| `packages/ai-parrot-tools/src/parrot_tools/gigsmart/toolkit.py` | CREATE | GigSmartToolkit class |
| `packages/ai-parrot-tools/src/parrot_tools/gigsmart/schemas.py` | CREATE | @tool_schema input models |
| `tests/tools/gigsmart/test_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:207
from parrot.tools import AbstractToolkit

# packages/ai-parrot/src/parrot/tools/decorators.py:37
from parrot.tools.decorators import tool_schema

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py:43
from parrot.tools.working_memory import WorkingMemoryToolkit  # optional composition

# From earlier tasks
from parrot_tools.interfaces.gigsmart.client import GigSmartClient  # TASK-1621
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig  # TASK-1617
from parrot_tools.interfaces.gigsmart.models.gig import PostShiftInput  # TASK-1619
from parrot_tools.interfaces.gigsmart.queries.gigs import LIST_GIGS, POST_SHIFT  # TASK-1620
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):  # line 207
    exclude_tools: tuple[str, ...] = ()  # line 244
    tool_prefix: Optional[str] = None  # line 258
    confirming_tools: frozenset = frozenset()  # line 276
    def __init__(self, **kwargs):  # line 278
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # line 354
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:  # line 369
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]:  # line 385

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):  # line 37
    # Attaches _args_schema to the function

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(AbstractToolkit):  # line 43
    name: str = "working_memory"  # line 76
    tool_prefix: str = "wm"  # line 77
```

### Does NOT Exist
- ~~`WorkingMemoryToolkit` as a base class~~ — compose it, do NOT inherit from it
- ~~`DeterministicGuard`~~ — does NOT exist; use `confirming_tools: frozenset`
- ~~`@requires_confirmation` decorator~~ — does NOT exist; add method name to `confirming_tools`
- ~~Separate `hire_worker()`, `end_engagement()`, `cancel_engagement()`~~ — ALL use `transition_engagement()`
- ~~`edit_timesheet()` method~~ — does NOT exist in GigSmart API

---

## Implementation Notes

### Class Skeleton
```python
class GigSmartToolkit(AbstractToolkit):
    name: str = "gigsmart"
    description: str = "Tools for interacting with the GigSmart staffing platform API"
    tool_prefix: str = "gs"

    confirming_tools: frozenset = frozenset({
        "post_shift", "transition_gig", "transition_engagement",
        "add_organization_location", "add_organization_position",
        "approve_timesheet", "remove_timesheet_dispute",
        "add_conversation_message",
    })

    def __init__(self, config: GigSmartConfig, wm: WorkingMemoryToolkit | None = None, **kwargs):
        super().__init__(**kwargs)
        self._client = GigSmartClient(config)
        self._wm = wm
```

### 23 Tool Methods by Surface

**Organizations (2)**
- `list_organizations(first, after, filter_name)` → list
- `get_organization(organization_id)` → dict

**Locations (3)**
- `list_locations(organization_id, first, after)` → list
- `place_autocomplete(search_text)` → list (for address resolution)
- `add_organization_location(organization_id, place_id, label)` → dict **[confirming]**

**Positions (3)**
- `list_positions(organization_id, first, after)` → list
- `get_position(position_id)` → dict
- `add_organization_position(organization_id, name, category_id)` → dict **[confirming]**

**Gigs/Shifts (4)**
- `list_gigs(organization_id, first, after, state_filter)` → list
- `get_gig(gig_id)` → dict
- `post_shift(organization_id, position_id, location_id, starts_at, ends_at, ...)` → dict **[confirming]**
- `transition_gig(gig_id, action)` → dict **[confirming]**

**Engagements (4)**
- `list_engagements(gig_id, first, after, state_filter)` → list
- `get_engagement(engagement_id)` → dict
- `transition_engagement(engagement_id, action)` → dict **[confirming]**
- `list_engagement_states(engagement_id)` → list (state history)

**Timesheets (4)**
- `list_timesheets(engagement_id)` → list
- `get_timesheet(timesheet_id)` → dict
- `approve_timesheet(timesheet_id)` → dict **[confirming]**
- `remove_timesheet_dispute(dispute_id)` → dict **[confirming]**

**Messages (1)**
- `add_conversation_message(engagement_id, body)` → dict **[confirming]**

**Utilities (2)**
- `search_gigs(query, location, radius_miles, first)` → list
- `get_gig_summary(gig_id)` → dict (enriched view with engagements + timesheets)

### @tool_schema Pattern
```python
class ListGigsInput(BaseModel):
    organization_id: str = Field(description="Organization ID (e.g., org_xxx)")
    first: int = Field(default=25, ge=1, le=100, description="Page size")
    after: str | None = Field(default=None, description="Cursor for pagination")
    state_filter: str | None = Field(default=None, description="Filter by gig state")

@tool_schema(ListGigsInput)
async def list_gigs(self, organization_id: str, first: int = 25,
                    after: str | None = None, state_filter: str | None = None) -> list[dict]:
    """List gigs for an organization with optional state filtering.

    Returns a list of gig summaries including ID, name, dates, state, and pay rate.
    Use state_filter with values like ACTIVE, UPCOMING, COMPLETED.
    """
```

### WorkingMemory Composition
```python
async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:
    if self._wm and isinstance(result, list) and len(result) > 10:
        import pandas as pd
        df = pd.DataFrame(result)
        await self._wm.store(key=f"gs_{tool_name}", df=df,
                             description=f"GigSmart {tool_name} results")
        return {"spilled_to_working_memory": f"gs_{tool_name}", "count": len(result)}
    return result
```

---

## Acceptance Criteria

- [ ] 23 public async methods defined
- [ ] All write methods listed in `confirming_tools` frozenset
- [ ] `@tool_schema` decorators on all methods with Pydantic input models
- [ ] Google-style docstrings on every tool method
- [ ] `transition_engagement` is the single method for ALL engagement state changes
- [ ] `transition_gig` is the single method for ALL gig state changes
- [ ] Optional `WorkingMemoryToolkit` composition works via `_post_execute`
- [ ] `tool_prefix = "gs"` set correctly
- [ ] Tests pass: `pytest tests/tools/gigsmart/test_toolkit.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.gigsmart.toolkit import GigSmartToolkit
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig

@pytest.fixture
def config():
    return GigSmartConfig(client_id="test", client_secret="secret")

@pytest.fixture
def toolkit(config):
    tk = GigSmartToolkit(config=config)
    tk._client = AsyncMock()
    return tk

class TestGigSmartToolkit:
    def test_inherits_abstract_toolkit(self, toolkit):
        from parrot.tools import AbstractToolkit
        assert isinstance(toolkit, AbstractToolkit)

    def test_confirming_tools_set(self, toolkit):
        assert "post_shift" in toolkit.confirming_tools
        assert "transition_engagement" in toolkit.confirming_tools
        assert "approve_timesheet" in toolkit.confirming_tools
        assert "list_gigs" not in toolkit.confirming_tools

    def test_tool_prefix(self, toolkit):
        assert toolkit.tool_prefix == "gs"

    def test_has_23_tools(self, toolkit):
        tools = toolkit.get_tools()
        assert len(tools) == 23

    async def test_list_gigs(self, toolkit):
        toolkit._client.paginate = AsyncMock(return_value=[{"id": "gig_1"}])
        result = await toolkit.list_gigs(organization_id="org_1")
        assert len(result) == 1

    async def test_transition_engagement(self, toolkit):
        toolkit._client.execute = AsyncMock(return_value={"transitionEngagement": {"engagement": {"id": "eng_1"}}})
        result = await toolkit.transition_engagement(engagement_id="eng_1", action="HIRE")
        assert result is not None
```

---

## Completion Note

*(Agent fills this in when done)*
