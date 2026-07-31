---
type: Wiki Overview
title: 'TASK-1703: Implement ZammadToolkit (AbstractToolkit subclass)'
id: doc:sdd-tasks-completed-task-1703-zammad-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The LLM-facing toolkit that wraps `ZammadInterface` methods as auto-discovered
relates_to:
- concept: mod:parrot.interfaces.zammad
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
- concept: mod:parrot_tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.zammad
  rel: mentions
---

# TASK-1703: Implement ZammadToolkit (AbstractToolkit subclass)

**Feature**: FEAT-218 — Zammad Interface & Toolkit
**Spec**: `sdd/specs/zammad-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1702
**Assigned-to**: unassigned

---

## Context

The LLM-facing toolkit that wraps `ZammadInterface` methods as auto-discovered
tools. Each public async method becomes a tool that an LLM agent can call.
`delete_ticket` is excluded for safety.

Implements: Spec §3 Module 3 (ZammadToolkit).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/zammad.py` with:
  - **`ZammadToolkit`** extending `AbstractToolkit`:
    - `tool_prefix = "zammad"`
    - `exclude_tools = ("delete_ticket",)`
    - Constructor accepting Zammad credentials + `on_behalf_of_header` + `attachment_dir`
    - `start()`: create `ZammadInterface` instance
    - `stop()`: close the interface
    - Public async methods (each becomes an LLM tool):
      - `create_ticket(title, group, customer, article_body, ...)` → dict
      - `get_ticket(ticket_id, expand)` → dict
      - `list_tickets(state_ids, page, per_page)` → dict
      - `update_ticket(ticket_id, title, article_body, ...)` → dict
      - `close_ticket(ticket_id)` → dict (updates state to "closed")
      - `search_tickets(query, page, per_page)` → dict
      - `get_user(user_id, expand)` → dict
      - `search_users(query)` → list
      - `create_user(firstname, lastname, email, ...)` → dict
      - `get_articles(ticket_id)` → list
      - `get_attachment(ticket_id, article_id, attachment_id)` → dict with `{file_path, base64, mime_type, filename}`
  - **Pydantic input models** with `@tool_schema` decorator for each method
- Write unit tests in `packages/ai-parrot-tools/tests/test_zammad_toolkit.py`

**NOT in scope**: ZammadInterface (TASK-1702), TOOL_REGISTRY entry (TASK-1704).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/zammad.py` | CREATE | ZammadToolkit + input models |
| `packages/ai-parrot-tools/tests/test_zammad_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Toolkit base classes — from satellite re-exports
from parrot_tools.toolkit import AbstractToolkit     # verified: packages/ai-parrot-tools/src/parrot_tools/toolkit.py
from parrot_tools.decorators import tool_schema      # verified: packages/ai-parrot-tools/src/parrot_tools/decorators.py

# ZammadInterface (created by TASK-1702)
from parrot.interfaces.zammad import (
    ZammadInterface, TicketCreatePayload, TicketUpdatePayload, UserCreatePayload,
)

# Standard
from pydantic import BaseModel, Field               # verified: used throughout
import base64                                        # stdlib
import logging                                       # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                          # line 207
    exclude_tools: tuple[str, ...] = ()              # line 244
    tool_prefix: Optional[str] = None                # line 249 (approx)
    prefix_separator: str = "_"                      # line 252 (approx)

    def __init__(self, **kwargs): ...                 # line 296
    async def start(self) -> None: ...                # line 337
    async def stop(self) -> None: ...                 # line 344
    def get_tools(self, ...) -> List[AbstractTool]: ...  # line 406

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):  # line 37
```

### Does NOT Exist
- ~~`parrot_tools.zammad`~~ — does not exist yet; must be created
- ~~`AbstractToolkit.register()`~~ — no such method; use TOOL_REGISTRY dict
- ~~`AbstractToolkit.add_tool()`~~ — no such method; tools are auto-discovered from public async methods

---

## Implementation Notes

### Pattern to Follow
Follow `JiraToolkit` structure (`parrot_tools/jiratoolkit.py`):

```python
class CreateTicketInput(BaseModel):
    title: str = Field(..., description="Ticket title")
    group: str = Field(..., description="Ticket group/queue")
    customer: str = Field(..., description="Customer email or ID")
    article_body: str = Field(..., description="Article body text")
    article_type: str = Field(default="note", description="Article type")
    on_behalf_of: Optional[str] = Field(default=None, description="User to act as (ID, login, or email)")
    # ... more fields

class ZammadToolkit(AbstractToolkit):
    tool_prefix = "zammad"
    exclude_tools = ("delete_ticket",)

    def __init__(self, instance_url=None, token=None, ..., **kwargs):
        self._instance_url = instance_url
        self._token = token
        # ... store config
        super().__init__(**kwargs)

    async def start(self):
        self._interface = ZammadInterface(
            instance_url=self._instance_url,
            token=self._token,
            ...
        )
        await self._interface.__aenter__()

    async def stop(self):
        if self._interface:
            await self._interface.close()

    @tool_schema(CreateTicketInput)
    async def create_ticket(self, title, group, customer, article_body, ...):
        """Create a new support ticket in Zammad."""
        payload = TicketCreatePayload(title=title, group=group, ...)
        return await self._interface.create_ticket(payload)
```

### Key Constraints
- Each method docstring becomes the LLM's tool description — make them clear and concise
- `get_attachment` must base64-encode the binary and return a dict:
  `{"file_path": str, "base64": str, "mime_type": str, "filename": str}`
- `close_ticket` is a convenience method that calls `update_ticket` with `state_id` for "closed"
- `delete_ticket` method MUST exist (for the exclude to work on it) but it should just
  delegate to `self._interface.delete_ticket()` — `exclude_tools` prevents it from becoming a tool

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — primary pattern (input models, @tool_schema)
- `packages/ai-parrot-tools/src/parrot_tools/zipcode.py` — simpler example

---

## Acceptance Criteria

- [ ] `ZammadToolkit` extends `AbstractToolkit` with `tool_prefix = "zammad"`
- [ ] All public async methods become tools via `@tool_schema`
- [ ] Tool names are prefixed: `zammad_create_ticket`, `zammad_get_ticket`, etc.
- [ ] `zammad_delete_ticket` does NOT appear in `get_tools()` output
- [ ] `start()` creates `ZammadInterface`; `stop()` closes it
- [ ] `get_attachment` returns `{"file_path", "base64", "mime_type", "filename"}`
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/test_zammad_toolkit.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/zammad.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_zammad_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot_tools.zammad import ZammadToolkit

@pytest.fixture
def toolkit():
    return ZammadToolkit(
        instance_url="https://zammad.example.com",
        token="test-token",
        default_group="Support",
    )

class TestZammadToolkit:
    def test_tool_prefix(self, toolkit):
        names = toolkit.list_tool_names()
        assert all(n.startswith("zammad_") for n in names)

    def test_delete_excluded(self, toolkit):
        names = toolkit.list_tool_names()
        assert "zammad_delete_ticket" not in names

    def test_expected_tools_present(self, toolkit):
        names = set(toolkit.list_tool_names())
        expected = {
            "zammad_create_ticket", "zammad_get_ticket", "zammad_list_tickets",
            "zammad_update_ticket", "zammad_close_ticket", "zammad_search_tickets",
            "zammad_get_user", "zammad_search_users", "zammad_create_user",
            "zammad_get_articles", "zammad_get_attachment",
        }
        assert expected.issubset(names)

    @pytest.mark.asyncio
    async def test_start_stop(self, toolkit):
        with patch("parrot_tools.zammad.ZammadInterface") as MockInterface:
            mock_instance = AsyncMock()
            MockInterface.return_value = mock_instance
            await toolkit.start()
            assert toolkit._interface is not None
            await toolkit.stop()
            mock_instance.close.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/zammad-interface-toolkit.spec.md` §2, §3
2. **Read** `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (lines 645–750) for the toolkit pattern
3. **Verify** TASK-1702 is complete (ZammadInterface exists and is importable)
4. **Implement** the toolkit following JiraToolkit structure
5. **Write tests** verifying tool registration, prefix, and exclusion
6. **Commit** and update status

---

## Completion Note

Implemented `ZammadToolkit` in `parrot_tools/zammad.py` following the
Odoo/Jira toolkit pattern: `tool_prefix = "zammad"`, `exclude_tools =
("delete_ticket",)`, lifecycle via `start()`/`stop()` composing a
`ZammadInterface`. All 11 public methods listed in scope implemented with
`@tool_schema` Pydantic input models. `get_attachment` base64-encodes the
downloaded bytes and guesses `mime_type` via `mimetypes.guess_type`.
`delete_ticket` exists (delegating to `self._interface.delete_ticket()`) so
the exclusion has a method to exclude, but is verified absent from
`list_tool_names()`.

Deviation note: `close_ticket` needs a Zammad "closed" state ID, which isn't
specified anywhere in the spec (Zammad's default state IDs vary per
installation). Added a `closed_state_id: int = 4` constructor parameter
(matching a stock Zammad install) so deployments with custom state schemes
can override it — flagging this as an assumption since the spec doesn't
pin down the exact ID.

9/9 unit tests pass (`pytest packages/ai-parrot-tools/tests/test_zammad_toolkit.py -v`).
`ruff check` clean on both new files.
