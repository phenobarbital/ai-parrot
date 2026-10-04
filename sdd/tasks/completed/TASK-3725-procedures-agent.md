# TASK-3725: ProceduresAgent transport adapter over the service (M11)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3715, TASK-3724
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (`agent.py`), review finding **R3** and **AC8**. Every chat integration (Slack `wrapper.py:539`, WhatsApp `wrapper.py:212`, Telegram `wrapper.py:1505`) calls `agent.ask(...)`. `ContractsAgent` *refuses* `ask`/`ask_stream`/`invoke` (`parrot_tools/contracts/agent.py:338-349`) so channels cannot use it. `ProceduresAgent` instead makes `ask()` a **gated transport adapter**: it builds a trusted `RequestContext` from the platform session kwargs (never from model output), calls `ProceduresAnswerService.answer(...)` (TASK-3723) and returns an `AIMessage` whose `output` is only released content, `structured_output` is the `ProcedureAnswer`, and `image_urls`/`media_urls` (TASK-3715) are the per-answer presigned URLs. The ReAct loop's raw output never reaches a channel, MCP, HTTP, streaming or memory history.

Covers spec §4 test `test_agent_ask_is_gated`; AC8, AC9.

---

## Scope

- Create `parrot_tools/procedures/agent.py` with `PROCEDURES_SYSTEM_PROMPT`, `UngatedAnswerRefused`, `ProceduresAgent(Agent)`:
  - `__init__(*, service, context_factory, **kwargs)` — creates `ProceduresToolkit` **before** `super().__init__` (contracts `agent.py:245-264`: `Agent.__init__` calls `agent_tools()`).
  - `agent_tools()` → the toolkit's tools.
  - `ask()` / `ask_stream()` / `invoke()` → gated through the service; `invoke()` raises `UngatedAnswerRefused("invoke")` when no context can be built.
  - `render(outcome)` — deterministic text rendering of a released `ProcedureAnswer` (numbered steps, prerequisites, hazards, tips, citation footers; `Clarification` ⇒ question + candidate list; `incomplete` ⇒ the reason, no steps).
- Per-request context isolation via a `ContextVar` (concurrent asks must never share a context).
- Write `test_agent.py`.

**NOT in scope**: channel wrappers (TASK-3717/3718/3719); the `AIMessage` field definitions (TASK-3715); conversation-memory persistence of the turn (AbstractBot owns history — this task only guarantees what it returns is released content).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/agent.py` | CREATE | `ProceduresAgent` transport adapter |
| `packages/ai-parrot-tools/tests/procedures/test_agent.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging
from contextvars import ContextVar                                     # precedent: parrot_tools/contracts/agent.py:25
from typing import Any, AsyncIterator, Callable, Optional
from parrot.bots import Agent                                          # verified: parrot/bots/__init__.py:2; contracts/agent.py:29
from parrot.models.responses import AIMessage                          # verified: models/responses.py:75
from parrot.models.basic import CompletionUsage                        # verified: models/basic.py:48 (responses.py:8 imports it)
# created by TASK-3720 / 3723 / 3724 (packages/ai-parrot-tools/src/parrot_tools/procedures/)
from parrot_tools.procedures.retrieval import Clarification, RequestContext
from parrot_tools.procedures.service import AnswerOutcome, ProceduresAnswerService
from parrot_tools.procedures.toolkit import ProceduresToolkit
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent: def __init__(self, name="Agent", agent_id="agent", use_llm="google", llm=None, tools=None, ...)  # line 84
    # line 154: `extra_tools = self.agent_tools()` — called INSIDE __init__ ⇒ toolkit must exist before super().__init__
class Agent(BasicAgent): def agent_tools(self) -> List[AbstractTool]  # line 1520-1526

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):   # line 75
    input: str                # line 79 — REQUIRED
    output: Any               # line 80 — REQUIRED
    response: Optional[str]   # line 81
    model: str                # REQUIRED (after documents, ~line 98)
    provider: str             # REQUIRED
    usage: CompletionUsage    # line 101 — REQUIRED
    structured_output: Optional[Any]   # line 148
# created by TASK-3715 — AIMessage.image_urls: List[str], AIMessage.media_urls: List[str] (http(s) only, validated)

# packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py — TEMPLATE (do not import)
class UngatedAnswerRefused(PermissionError): def __init__(self, entrypoint: str)   # line 214-223
class ContractsAgent(Agent):                                                        # line 232
    def __init__(self, *args, service, request_context, library=None, **kwargs)    # line 245 — toolkit + ContextVar BEFORE super().__init__ (253-262)
    def agent_tools(self) -> list[Any]: return self.toolkit.get_tools()             # line 266-268
    async def ask/ask_stream/invoke → raise UngatedAnswerRefused                     # line 338-349 — NOT copied for ask()

# created by TASK-3723 — ProceduresAnswerService.answer(question, *, request_context, producer=None) -> AnswerOutcome | Clarification
#                        stream_answer(...) -> AsyncIterator[str]; AnswerOutcome(answer, audit_id, image_urls, media_urls)
# created by TASK-3724 — ProceduresToolkit(*, service, request_context, library=None, task_memory=None, episodic=None)
```

### Does NOT Exist
- ~~Returning the ReAct loop's reply from `ask()`~~ — R3: only service-released content.
- ~~Building `RequestContext` from the question or model/tool output~~ — only from platform-session kwargs via `context_factory`.
- ~~Raising `UngatedAnswerRefused` from `ask()`~~ — contracts does; procedures must answer through the gate so channels work.
- ~~`AIMessage.image_urls` before TASK-3715~~ — depends on it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/agent.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_agent.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py#ContractsAgent",
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py#UngatedAnswerRefused"
  ]
}
```

---

## Implementation Notes

### Decisions fixed here
- `context_factory(kwargs)` receives the `ask()` kwargs (`user_id`, `session_id`, plus whatever the wrapper passes, e.g. `tenant_id`, `roles`, `channel`); it returns a `RequestContext` or raises `AuthorizationDenied`. On denial `ask()` returns a `denied` rendering (still an `AIMessage`, no steps) — never an exception into the channel.
- `equipment_serial` persists per session: keep `self._serials: dict[str, str]` keyed by `session_id`, written when the toolkit's `set_equipment_serial` updates its context, and merged into each new context built for that session (Q7 "asked once per session").
- `AIMessage(input=question, output=text, response=text, structured_output=outcome.answer, image_urls=..., media_urls=..., model="procedures-service", provider="parrot", usage=CompletionUsage())` — `model`/`provider`/`usage` are required fields; confirm `CompletionUsage()` constructs with defaults (else pass zeros).
- `ask_stream` yields from `service.stream_answer` (buffered by the service).
- `invoke` is gated like `ask`; when `context_factory` raises for lack of session data ⇒ `UngatedAnswerRefused("invoke")`.
- Tests instantiate via `ProceduresAgent.__new__(ProceduresAgent)` + attribute setup, because `Agent.__init__` builds a real LLM client (default `use_llm="google"`).

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py:214-353` — init ordering, ContextVar, refusal (not copied for ask)
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:539`, `whatsapp/wrapper.py:212`, `telegram/wrapper.py:1505` — the `agent.ask` call sites this adapter serves

---

## Implementation Blueprint

### Steps (in order)
1. Write the module header, prompt and `UngatedAnswerRefused` (block 1).
2. Write `__init__` with toolkit + ContextVar before `super().__init__` — *because* `Agent.__init__` calls `agent_tools()` (bots/agent.py:154).
3. Write `ask`/`ask_stream`/`invoke` + `render` (block 2) — *because* AC8: channels call `ask()` and must get only released content.
4. Tests with `__new__`-constructed agent and a stub service.

### `packages/ai-parrot-tools/src/parrot_tools/procedures/agent.py` (CREATE) — block 1/2
```python
"""ProceduresAgent — a gated transport adapter over ProceduresAnswerService (FEAT-601 M11, R3)."""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, AsyncIterator, Callable, Optional

from parrot.bots import Agent
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot_tools.procedures.retrieval import AuthorizationDenied, Clarification, RequestContext
from parrot_tools.procedures.service import AnswerOutcome, ProceduresAnswerService
from parrot_tools.procedures.toolkit import ProceduresToolkit

logger = logging.getLogger(__name__)

PROCEDURES_SYSTEM_PROMPT = (
    "You help field technicians follow equipment assembly and maintenance procedures. "
    "Only the procedures tools may provide steps, parts, hazards and figures; never invent, reorder or skip steps. "
    "Answer in the technician's language (Spanish or English)."
)
_ANON = RequestContext(authenticated=False, tenant_id="", user_id="")


class UngatedAnswerRefused(PermissionError):
    """An entrypoint was called without the session data needed to build a trusted context."""

    def __init__(self, entrypoint: str) -> None:
        super().__init__(f"{entrypoint}() needs a trusted platform session; refusing an unverified answer")
        self.entrypoint = entrypoint


class ProceduresAgent(Agent):
    """ReAct-capable agent whose every channel entrypoint goes through the procedures release gate.

    Args:
        service: The shared release service (the only answer path).
        context_factory: Builds the trusted ``RequestContext`` from platform-session kwargs.
        **kwargs: Forwarded to :class:`~parrot.bots.Agent`.
    """

    agent_id: str = "procedures_agent"

    def __init__(self, *, service: ProceduresAnswerService, context_factory: Callable[[dict[str, Any]], RequestContext],
                 **kwargs: Any) -> None:
        kwargs.setdefault("system_prompt", PROCEDURES_SYSTEM_PROMPT)
        self.service = service
        self.context_factory = context_factory
        self._request_context: ContextVar[RequestContext] = ContextVar("procedures_request_context", default=_ANON)
        self._serials: dict[str, str] = {}
        self.toolkit = ProceduresToolkit(service=service, request_context=_ANON)
        # Agent.__init__ calls agent_tools(), so the toolkit must exist first.
        super().__init__(**kwargs)

    def agent_tools(self) -> list[Any]:
        """Expose the procedures toolkit's tools to the ReAct loop."""
        return self.toolkit.get_tools()
```

### `agent.py` — block 2/2
```python
    def _context(self, kwargs: dict[str, Any]) -> RequestContext:
        """Build the trusted context; merge the session's remembered serial (Q7)."""
        context = self.context_factory(kwargs)
        serial = self._serials.get(context.session_id or "")
        if serial and not context.equipment_serial:
            context = context.model_copy(update={"equipment_serial": serial})
        self._request_context.set(context)
        # FILL IN: bind the toolkit to this request's context without leaking across concurrent asks — bounded by
        #          "concurrent asks must never share a context" (ContextVar-backed toolkit context or per-call toolkit)
        return context

    async def ask(self, question: str, *args: Any, **kwargs: Any) -> AIMessage:
        """Transport adapter: context from the session → service.answer → AIMessage of released content only."""
        try:
            context = self._context(kwargs)
        except AuthorizationDenied as exc:
            return self._message(question, f"⛔ {exc.reason}", structured=None)
        outcome = await self.service.answer(question, request_context=context)
        return self._message(question, self.render(outcome),
                             structured=outcome.answer if isinstance(outcome, AnswerOutcome) else outcome,
                             image_urls=outcome.image_urls if isinstance(outcome, AnswerOutcome) else [],
                             media_urls=outcome.media_urls if isinstance(outcome, AnswerOutcome) else [])

    async def ask_stream(self, question: str, *args: Any, **kwargs: Any) -> AsyncIterator[str]:
        """Stream the released answer (the service buffers until release)."""
        context = self._context(kwargs)
        async for chunk in self.service.stream_answer(question, request_context=context):
            yield chunk

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Gated like :meth:`ask`; refuses when no trusted context can be built."""
        question = kwargs.pop("question", None) or (args[0] if args else "")
        try:
            self.context_factory(kwargs)
        except Exception as exc:  # noqa: BLE001 — no session ⇒ refuse, never answer ungated
            raise UngatedAnswerRefused("invoke") from exc
        return await self.ask(question, **kwargs)

    @staticmethod
    def render(outcome: AnswerOutcome | Clarification) -> str:
        """Deterministic chat text of a released answer (no model text except the verified intro prose)."""
        # FILL IN: Clarification ⇒ reason + numbered candidates; incomplete/denied/not_found ⇒ reason line only;
        #          procedure/step ⇒ intro prose, "Antes de empezar / Before you start" prerequisites, numbered steps with
        #          ⚠ hazards and "unknown applicability" notes, tips, "Fuente: p.N" citation footers; lookup ⇒ the
        #          "not a verified procedure" line — bounded by AC8/AC20 and the TASK-3700 answer fields
        raise NotImplementedError

    def _message(self, question: str, text: str, *, structured: Any, image_urls: Optional[list[str]] = None,
                 media_urls: Optional[list[str]] = None) -> AIMessage:
        """Wrap released content in an AIMessage (required fields: input, output, model, provider, usage)."""
        return AIMessage(input=question, output=text, response=text, structured_output=structured,
                         image_urls=list(image_urls or []), media_urls=list(media_urls or []),
                         model="procedures-service", provider="parrot", usage=CompletionUsage())
```
**Why this shape**: `ask()` never calls the ReAct loop, so no unverified draft can reach a channel; the toolkit remains available to `agent_tools()` for tool-calling surfaces, each call gated by `_gate`.

### `packages/ai-parrot-tools/tests/procedures/test_agent.py` (CREATE)
Start from the Test Specification below.

### FILL IN checklist
- [ ] `_context` — per-request toolkit binding without cross-request leakage
- [ ] `render` — deterministic rendering per answer kind; AC8/AC20
- [ ] verify `CompletionUsage()` default construction (else pass explicit zeros)

---

## Acceptance Criteria

- [ ] `ask()` returns an `AIMessage` with `structured_output` = released `ProcedureAnswer`, `image_urls`/`media_urls` from the outcome, and `output` containing no text the service did not release (AC8).
- [ ] A denied or unauthenticated session yields an `AIMessage` with the denial reason and no steps (AC9).
- [ ] `invoke()` without session data raises `UngatedAnswerRefused("invoke")`.
- [ ] `ask`, `ask_stream`, `invoke` are defined on `ProceduresAgent` itself (not inherited ungated from `Agent`).
- [ ] The serial set once in a session is reused for later asks in that session (Q7).

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_agent.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/procedures/test_agent.py
import pytest

from parrot_tools.procedures.agent import ProceduresAgent, UngatedAnswerRefused

from ._doubles import make_context


def _agent(service, factory):
    agent = ProceduresAgent.__new__(ProceduresAgent)   # Agent.__init__ builds a real LLM client
    # FILL IN: set service, context_factory, _request_context ContextVar, _serials, toolkit, logger
    return agent


async def test_agent_ask_is_gated():
    """ask() returns AIMessage with structured_output + image_urls; raw draft never in output."""
    # FILL IN: stub service.answer returning an AnswerOutcome with image_urls=["https://fake/f1.png"]; a stub
    #          producer draft "RAW-DRAFT-XYZ" that the verifier dropped ⇒ "RAW-DRAFT-XYZ" not in msg.output
    ...


def test_entrypoints_are_overridden():
    for name in ("ask", "ask_stream", "invoke"):
        assert name in vars(ProceduresAgent)


async def test_invoke_without_session_refuses():
    # FILL IN: context_factory raising ⇒ pytest.raises(UngatedAnswerRefused)
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3725
- Feature: training-agent
- Implementation SHA: 25e51b458350c752d2dbd3b0783cd6003174c1fa
- Closed at (UTC): 2026-09-25T19:04:49+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra - Backend: codex - Model: gpt-5.6-terra - Attempts: 1 - Duration: ~220s - Tokens: n/a |
