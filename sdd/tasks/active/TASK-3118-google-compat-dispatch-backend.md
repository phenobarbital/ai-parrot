# TASK-3118: `google-compat` dev-loop backend — profile, dispatcher (thought_signature echo), builder branch

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3117
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (dispatcher half). Mirrors the `NovaCodeDispatcher` pattern: a
`LLMCodeDispatcher` subclass that swaps `client_factory` for `GeminiOpenAICompatClient`
and adds exactly two overrides. `_completion_args` replaces `extra_body` (silently
ignored by Google's layer) with `reasoning_effort`; `_tool_call_to_openai_dict` carries
the raw tool call's `extra_content` — Gemini 3 answers **HTTP 400 "Function call is
missing a thought_signature"** when the echoed assistant turn drops it (verified live,
spec §6 "Spike evidence"; design research S9). Also registers the `"google-compat"`
`DevAgentBackend` and the `build_dispatcher` branch so roster seats can name it.

---

## Scope

- Create `models/google_compat.py` with `GoogleCompatCodeDispatchProfile(LLMCodeDispatchProfile)`.
- Create `dispatchers/google_compat.py` with `GoogleCompatCodeDispatcher(LLMCodeDispatcher)`.
- Add `"google-compat"` to `DevAgentBackend`; add the `build_dispatcher` branch (+ env `DEV_LOOP_GOOGLE_COMPAT_MODEL`, `DEV_LOOP_GOOGLE_COMPAT_REASONING_EFFORT`).
- Export the two new symbols from `models/__init__.py`, `dispatchers/__init__.py`, `flows/dev_loop/__init__.py`.
- Unit tests (no network): profile defaults, `_completion_args`, `extra_content` carry-over, multi-turn wire format, builder branch.

**NOT in scope**: the client (TASK-3117); the live round-trip test (TASK-3125); changes to `LLMCodeDispatcher` itself (the carry-over stays in the subclass — spec §8 Q2 default).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_compat.py` | CREATE | profile |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_compat.py` | CREATE | dispatcher with the two overrides |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | `DevAgentBackend` gains `"google-compat"` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` | MODIFY | import + branch before the final `raise` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py` | MODIFY | import + `__all__` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/__init__.py` | MODIFY | import + `__all__` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | re-export both |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_compat_dispatcher.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Dict, List, Literal, Optional
from pydantic import Field, model_validator
from parrot.clients.factory import LLMFactory                                   # verified: clients/factory.py:163; parse_llm_string :174
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher              # verified: dispatchers/llm.py:51
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile              # verified: models/llm.py:10
# lazy, INSIDE the factory method only (FEAT-523 AC-3 — core never imports a provider at module scope; see nova.py:59-64):
from parrot.clients.google.openai_compat import GeminiOpenAICompatClient        # TASK-3117
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                                                                      # line 51
    def __init__(self, *, max_concurrent: int, redis_url: str, stream_ttl_seconds: int,
                 client_factory: Callable[..., Any] = LLMFactory.create) -> None                # line 60
    def _create_client(self, profile, *, run_id=None) -> Any                                   # line 846 — calls self._client_factory(profile.llm, model_args={"temperature","max_tokens"})
    def _completion_args(self, profile: LLMCodeDispatchProfile, tools: List[Dict[str, Any]]) -> Dict[str, Any]   # line 949 — tools, tool_choice="auto", parallel_tool_calls, max_tokens, temperature, extra_body (only if enable_thinking)
    def _tool_call_to_openai_dict(self, call: Any, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]   # line 2237 — returns {"id","type":"function","function":{"name","arguments"}} ONLY
    @classmethod
    def _parse_tool_arguments(cls, call) -> Tuple[Optional[Dict], str]                         # line 2176 — accepts dict OR JSON string
# TEMPLATE — packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py
class NovaCodeDispatcher(LLMCodeDispatcher):                                                  # line 66
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds): super().__init__(..., client_factory=self._create_mantle_client)   # :78-88
    def _create_mantle_client(self, llm: str, *, model_args=None, **kwargs) -> Any             # :91 — parse_llm_string → init_params (model, temperature, max_tokens) → client(...)
# TEMPLATE — packages/ai-parrot/src/parrot/flows/dev_loop/models/nova.py
class NovaCodeDispatchProfile(LLMCodeDispatchProfile):                                        # line 93
    model: str = Field(default="minimax.minimax-m2.5", ...); llm: str = "nova:minimax.minimax-m2.5"   # :102, :110
    @model_validator(mode="after")
    def _sync_llm_with_model(self): if "llm" not in self.model_fields_set: self.llm = f"nova:{self.model}"; return self
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:407-409
DevAgentBackend = Literal[
    "claude-code", "codex", "gemini", "nvidia", "grok", "zai", "moonshot", "google_coding", "nova"
]
# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
from parrot.flows.dev_loop import (GoogleCodingDispatcher, ..., NovaCodeDispatcher, NovaCodeDispatchProfile, ...)   # lines 36-58 (NovaCodeDispatchProfile at :55)
llm_max_turns = _get_int(config_getter, ENV_LLM_MAX_TURNS, DEFAULT_LLM_MAX_TURNS)             # :175
if spec.agent == "nova": ... return dispatcher, profile                                        # :253-260
raise ValueError(f"Unknown DevAgentBackend: {spec.agent!r}")                                  # :262
# exports (each anchor occurs exactly once per file — verified by grep):
#   models/__init__.py:80      `    NovaCodeDispatchProfile,`      and :118 `    "NovaCodeDispatchProfile",`
#   dispatchers/__init__.py:33 `    NovaCodeDispatcher,`           and :45  `    "NovaCodeDispatcher",`
#   dev_loop/__init__.py:22    `    NovaCodeDispatcher,`  :53 `    NovaCodeDispatchProfile,`  :113 `    "NovaCodeDispatcher",`  :114 `    "NovaCodeDispatchProfile",`
```

### Spike facts this task encodes (spec §6)
- Raw tool call shape from Google: `{"id", "type", "function", "extra_content": {"google": {"thought_signature": "<base64>"}}}` — `extra_content` is on each **tool_call**, not on the message.
- Echoing `{id,type,function}` only ⇒ HTTP 400; echoing with `extra_content` carried ⇒ OK.
- Unknown kwargs are silently ignored ⇒ `extra_body.chat_template_kwargs` is useless; `reasoning_effort="none"` accepted.

### Does NOT Exist
- ~~`extra_content` handling in `LLMCodeDispatcher._tool_call_to_openai_dict`~~ — base drops it (llm.py:2237-2269); only this subclass carries it.
- ~~`"google-compat"` in `DevAgentBackend`~~ / ~~`GoogleCompatCodeDispatchProfile`~~ / ~~`GoogleCompatCodeDispatcher`~~ — created here.
- ~~`GeminiCodeDispatcher` as the Gemini route~~ — the `gemini` CLI is unusable on this account (spec Non-Goals); leave that class untouched.
- ~~`DEV_LOOP_GOOGLE_COMPAT_MODEL`~~ — new env key introduced here (read through `config_getter`, default `"gemini-3.5-flash"`).
- ~~module-scope import of `parrot.clients.google`~~ in core — forbidden (FEAT-523 AC-3); import inside `_create_compat_client`.

---

## Implementation Notes

### Pattern to Follow
`dispatchers/nova.py:66-140` for the dispatcher; `models/nova.py:93-130` for the profile (incl. `_sync_llm_with_model`).

### Key Constraints
- `enable_thinking` must stay `False` on this profile — document it in the field description.
- `_completion_args`: call `super()`, `pop("extra_body", None)`, set `args["reasoning_effort"] = profile.reasoning_effort`.
- `_tool_call_to_openai_dict`: call `super()`, then copy `extra_content` from `call` (attribute on SDK objects; key on dicts) when present.
- Builder branch placed **before** the final `raise`, after the `nova` branch; defaults via `config_getter`.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py:37-63` — `_completion_args` override precedent.
- `packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py:23-40` — `FakeDispatcher` shape for tests.

---

## Implementation Blueprint

### Steps (in order)
1. Profile — *why*: `build_dispatcher` returns `(dispatcher, profile)`; the profile carries the defaults the roster may override.
2. Dispatcher with `client_factory` + two overrides — *why*: the loop, tool schemas and cwd guard are inherited unchanged (verified live); only wire format and kwargs differ.
3. Literal + builder branch + exports — *why*: `RosterSeat.backend: DevAgentBackend` (TASK-3115) must accept `"google-compat"` and `DevAgentPool`/engine build seats through `build_dispatcher`.
4. Tests, then `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_compat_dispatcher.py -v` and the whole `tests/flows/dev_loop` for regressions (AC-16).

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_compat.py` (CREATE)
```python
"""Dispatch profile for the `google-compat` seat (FEAT-549, spec §3 M3). Template: models/nova.py:93."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile  # verified: models/llm.py:10


class GoogleCompatCodeDispatchProfile(LLMCodeDispatchProfile):
    """Gemini via Google's OpenAI-compatible endpoint. ``enable_thinking`` MUST stay False:
    ``extra_body.chat_template_kwargs`` is silently ignored by Google's layer — use ``reasoning_effort``."""

    model: str = Field(default="gemini-3.5-flash", description="Gemini model id served by the compat endpoint.")
    llm: str = "google-compat:gemini-3.5-flash"
    reasoning_effort: Literal["none", "low", "medium", "high"] = Field(
        default="none", description="Forwarded as the OpenAI `reasoning_effort` kwarg; 'none' disables thinking.")

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "GoogleCompatCodeDispatchProfile":
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly (nova.py precedent)."""
        if "llm" not in self.model_fields_set:
            self.llm = f"google-compat:{self.model}"
        return self
```
**Why this shape**: fixed by spec §3 M3 skeleton; `model`/`llm` sync copies Nova so `build_dispatcher` can pass either.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_compat.py` (CREATE)
```python
"""GoogleCompatCodeDispatcher — LLMCodeDispatcher over Gemini's OpenAI-compatible endpoint (FEAT-549).

Two overrides beyond the client factory: ``_completion_args`` (reasoning_effort, no extra_body) and
``_tool_call_to_openai_dict`` (carry ``extra_content`` — Gemini 3 returns HTTP 400
"Function call is missing a thought_signature" otherwise; verified live 2026-09-10).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from parrot.clients.factory import LLMFactory                          # verified: clients/factory.py:163
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher     # verified: dispatchers/llm.py:51
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile     # verified: models/llm.py:10


class GoogleCompatCodeDispatcher(LLMCodeDispatcher):
    """Gemini seat for the sdd_coder kernel and the dev-loop pool."""

    def __init__(self, *, max_concurrent: int, redis_url: str, stream_ttl_seconds: int) -> None:
        super().__init__(max_concurrent=max_concurrent, redis_url=redis_url, stream_ttl_seconds=stream_ttl_seconds,
                         client_factory=self._create_compat_client)
        self.logger = logging.getLogger(__name__)

    def _create_compat_client(self, llm: str, *, model_args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        """Build ``GeminiOpenAICompatClient`` for ``llm='google-compat:<model>'`` (lazy provider import, FEAT-523 AC-3)."""
        from parrot.clients.google.openai_compat import GeminiOpenAICompatClient  # noqa: PLC0415 — provider import stays lazy
        _provider, model = LLMFactory.parse_llm_string(llm)
        init_params: Dict[str, Any] = {}
        if model:
            init_params["model"] = model
        for key in ("temperature", "max_tokens"):
            if model_args and model_args.get(key) is not None:
                init_params[key] = model_args[key]
        init_params.update(kwargs)
        return GeminiOpenAICompatClient(**init_params)

    def _completion_args(self, profile: LLMCodeDispatchProfile, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """super() minus ``extra_body`` (ignored by Google) plus ``reasoning_effort`` from the profile."""
        args = super()._completion_args(profile, tools)
        args.pop("extra_body", None)
        args["reasoning_effort"] = getattr(profile, "reasoning_effort", "none")
        return args

    def _tool_call_to_openai_dict(self, call: Any, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """super() dict + ``extra_content`` copied verbatim when the raw call carries it (thought_signature)."""
        rendered = super()._tool_call_to_openai_dict(call, arguments)
        extra = call.get("extra_content") if isinstance(call, dict) else getattr(call, "extra_content", None)
        if extra:
            rendered["extra_content"] = extra  # FILL IN: if `extra` is a pydantic object, use .model_dump() — bounded by test_compat_dispatcher_carries_extra_content
        return rendered
```
**Why this shape**: mirrors nova.py so the class reads as a known pattern; the `extra_content` copy is the minimal fix proven by spike variant C (spec §6). Never touch `_chat_completion` — `OpenAIBaseClient` already exposes it.

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^DevAgentBackend = Literal\[' packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py)
# REPLACE the literal body (verified: models/base.py:407-409) with:
DevAgentBackend = Literal[
    "claude-code", "codex", "gemini", "nvidia", "grok", "zai", "moonshot", "google_coding", "nova", "google-compat"
]
```
**Why**: `RosterSeat.backend` and `DevAgentSpec.agent` are typed with it.

### `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` (MODIFY — two edits)
```python
# occurrences: 1 (verified: grep -c '^    NovaCodeDispatchProfile,$' packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py)
# AFTER — insert below `    NovaCodeDispatchProfile,` inside the `from parrot.flows.dev_loop import (` block (verified: agent_builder.py:55)
    GoogleCompatCodeDispatcher,
    GoogleCompatCodeDispatchProfile,

# occurrences: 1 (verified: grep -c 'raise ValueError(f"Unknown DevAgentBackend' packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py)
# BEFORE — insert above `    raise ValueError(f"Unknown DevAgentBackend: {spec.agent!r}")` (verified: agent_builder.py:262)
    if spec.agent == "google-compat":
        dispatcher = GoogleCompatCodeDispatcher(**common)
        compat_model = spec.model or config_getter("DEV_LOOP_GOOGLE_COMPAT_MODEL", "gemini-3.5-flash")
        profile = GoogleCompatCodeDispatchProfile(
            model=compat_model,
            llm=f"google-compat:{compat_model}",
            max_turns=llm_max_turns,
            reasoning_effort=config_getter("DEV_LOOP_GOOGLE_COMPAT_REASONING_EFFORT", "none"),
        )
        return dispatcher, profile
```
**Why**: same shape as the `nova` branch (:253-260); `common` and `llm_max_turns` are already in scope (:166-175).

### Export edits (MODIFY, each anchor occurs once — verified by grep)
```python
# models/__init__.py — AFTER `    NovaCodeDispatchProfile,` (:80) add a new import line:
from parrot.flows.dev_loop.models.google_compat import GoogleCompatCodeDispatchProfile
#                     — AFTER `    "NovaCodeDispatchProfile",` (:118) add:   "GoogleCompatCodeDispatchProfile",
# dispatchers/__init__.py — AFTER the `from ...nova import (...)` block (:31-34) add:
from parrot.flows.dev_loop.dispatchers.google_compat import GoogleCompatCodeDispatcher
#                     — AFTER `    "NovaCodeDispatcher",` (:45) add:   "GoogleCompatCodeDispatcher",
# flows/dev_loop/__init__.py — AFTER `    NovaCodeDispatcher,` (:22) add `    GoogleCompatCodeDispatcher,`; AFTER `    NovaCodeDispatchProfile,` (:53) add `    GoogleCompatCodeDispatchProfile,`;
#                     — AFTER `    "NovaCodeDispatcher",` (:113) and `    "NovaCodeDispatchProfile",` (:114) add the two quoted names.
```
**Why**: `agent_builder.py` imports from the package (`from parrot.flows.dev_loop import (...)`, :36), so the package must re-export both.

### FILL IN checklist
- [ ] `dispatchers/google_compat.py::_tool_call_to_openai_dict` — pydantic-object `extra_content` serialisation; bounded by `test_compat_dispatcher_carries_extra_content`
- [ ] `test_google_compat_dispatcher.py` bodies (scaffold below)

---

## Acceptance Criteria

- [ ] `GoogleCompatCodeDispatchProfile()` ⇒ `llm == "google-compat:gemini-3.5-flash"`, `reasoning_effort == "none"`, `enable_thinking is False`.
- [ ] `_completion_args` output has `reasoning_effort`, no `extra_body`, and keeps `tools`, `tool_choice`, `parallel_tool_calls`, `max_tokens`.
- [ ] `_tool_call_to_openai_dict` carries `extra_content` verbatim when present; emits no key otherwise; the base `LLMCodeDispatcher` on the same input emits no `extra_content` (S9).
- [ ] Multi-turn synthetic exchange reproduces the spike's accepted `messages` shape (assistant `tool_calls` with `extra_content` → `tool` results).
- [ ] `build_dispatcher(DevAgentSpec(agent="google-compat"), redis_url="redis://x", max_concurrent=1, stream_ttl_seconds=60, config_getter=fake)` returns the new pair; `spec.model` wins over env.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop -v` passes (AC-16, no regressions); `ruff`/`mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_google_compat_dispatcher.py
from types import SimpleNamespace
from parrot.flows.dev_loop import GoogleCompatCodeDispatcher, GoogleCompatCodeDispatchProfile, LLMCodeDispatcher
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.models import DevAgentSpec

def _disp(cls=GoogleCompatCodeDispatcher):
    return cls(max_concurrent=1, redis_url="redis://localhost:1/0", stream_ttl_seconds=60)

def _call(extra=None):
    fn = SimpleNamespace(name="read_file", arguments='{"path": "README.md"}')
    return SimpleNamespace(id="c1", type="function", function=fn, extra_content=extra)

def test_compat_profile_defaults():
    p = GoogleCompatCodeDispatchProfile()
    assert p.llm == "google-compat:gemini-3.5-flash" and p.reasoning_effort == "none" and p.enable_thinking is False
    assert GoogleCompatCodeDispatchProfile(model="gemini-3.8-flash").llm == "google-compat:gemini-3.8-flash"

def test_compat_dispatcher_completion_args():
    args = _disp()._completion_args(GoogleCompatCodeDispatchProfile(enable_thinking=True), tools=[{"type": "function"}])
    assert args["reasoning_effort"] == "none" and "extra_body" not in args
    assert {"tools", "tool_choice", "parallel_tool_calls", "max_tokens"} <= set(args)

def test_compat_dispatcher_carries_extra_content():
    sig = {"google": {"thought_signature": "abc=="}}
    assert _disp()._tool_call_to_openai_dict(_call(sig))["extra_content"] == sig
    assert "extra_content" not in _disp()._tool_call_to_openai_dict(_call(None))
    assert "extra_content" not in _disp(LLMCodeDispatcher)._tool_call_to_openai_dict(_call(sig))

def test_compat_dispatcher_multiturn_wire_format():
    # FILL IN: assistant turn = {"role":"assistant","content":"","tool_calls":[rendered]} + tool result message;
    #          assert rendered["extra_content"] survives and arguments is a JSON string — bounded by spec §6 spike variant C

def test_build_dispatcher_google_compat():
    getter = lambda k, fb=None: {"DEV_LOOP_GOOGLE_COMPAT_MODEL": "gemini-3.6-flash"}.get(k, fb)
    d, p = build_dispatcher(DevAgentSpec(agent="google-compat"), redis_url="redis://x", max_concurrent=1, stream_ttl_seconds=60, config_getter=getter)
    assert isinstance(d, GoogleCompatCodeDispatcher) and p.model == "gemini-3.6-flash"
    _, p2 = build_dispatcher(DevAgentSpec(agent="google-compat", model="gemini-3.5-flash"), redis_url="redis://x", max_concurrent=1, stream_ttl_seconds=60, config_getter=getter)
    assert p2.llm == "google-compat:gemini-3.5-flash"
```

---

## Agent Instructions

1. **Read the spec** §3 Module 3, §6 "Spike evidence", §7 Known Risks.
2. **Check dependencies** — TASK-3117 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-run every `grep -c` anchor above; read nova.py:66-140 and llm.py:2237-2269.
4. **Update status** in `sdd/tasks/index/sdd-worker-subagents.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete the `FILL IN`s.
6. **Verify** all acceptance criteria, including the full `tests/flows/dev_loop` run.
7. **Move this file** to `sdd/tasks/completed/TASK-3118-google-compat-dispatch-backend.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
