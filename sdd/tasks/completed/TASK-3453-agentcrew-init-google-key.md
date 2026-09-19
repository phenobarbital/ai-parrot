# TASK-3453: `AgentCrew.__init__(google_api_key=)` + the three default-Google-client sites

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3451
**Assigned-to**: unassigned

---

## Context

Spec §2 step 4 (first half) + §3 Module 2. `AgentCrew` builds a Google client for
itself in three places, each of which silently bills `GOOGLE_API_KEY`:

1. `__init__` — the default orchestration LLM when no `llm` is passed (`crew.py:232-233`).
2. `run_loop` — a lazy fallback when `self._llm` is still `None` (`crew.py:2132`).
3. `summary(mode="executive_summary")` — the same lazy fallback (`crew.py:4383`).

This task adds the opt-in `google_api_key` parameter and threads it to all three.
It is goal G2 / AC4. `from_definition` is TASK-3454.

---

## Scope

- Add `google_api_key: Optional[str] = None` to `AgentCrew.__init__`, immediately
  before `**kwargs`, and store it as `self._google_api_key`.
- Pass it to the default Google orchestration client in `__init__`, for both the
  "`llm` is a Google provider string" branch and the "no `llm`" branch — but never
  when the caller already supplied `api_key` in `kwargs`.
- Pass `self._google_api_key` to the `run_loop` and executive-summary lazy fallbacks.
- Write unit tests in a NEW test module.

**NOT in scope**:
- `AgentCrew.from_definition` — TASK-3454 (same file; that task depends on this one).
- `manager.py` / `handler.py` call sites — TASK-3455 / TASK-3456.
- The infographic ResultAgent at `crew.py:609`: it is already constructed as
  `agent_cls(name=self.result_agent_name, llm=self._llm)`, i.e. it receives the
  crew's client **instance**, so it is covered for free. Do not touch it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | `google_api_key` param + 3 default-client sites |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already at the top of crew.py — reuse, do not re-add:
from navconfig.logging import logging                       # verified: crew.py:53
from ...abstract import AbstractBot, _resolve_supported_client  # verified: crew.py:57
from ....clients import AbstractClient                      # verified: crew.py:58
from ....clients.factory import SUPPORTED_CLIENTS           # verified: crew.py:59

# NEW import this task adds to crew.py:
from .credentials import GOOGLE_PROVIDER_KEYS               # created by TASK-3451
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew:
    def __init__(
        self,
        name: str = "AgentCrew",                        # line 158
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None,
        max_parallel_tasks: int = 10,
        llm: Optional[Union[str, AbstractClient]] = None,   # line 162
        auto_configure: bool = True,
        truncation_length: Optional[int] = None,
        truncate_context_summary: bool = True,
        embedding_model: Any = None,
        enable_analysis: bool = False,
        dimension: int = 384,
        index_type: str = "Flat",
        agent_execution_timeout: float = 600.0,
        persist_results: bool = True,
        result_storage: Union[str, "ResultStorage", None] = None,
        persist_agent_results: bool = True,
        enable_execution_wiki: bool = True,
        execution_wiki_path: Union[str, "Path", None] = None,
        tenant: Optional[str] = None,
        generate_infographic: bool = False,
        result_agent_name: str = "result-agent",
        infographic_theme: Optional[str] = None,        # line 179 — UNIQUE anchor
        **kwargs,                                       # line 180
    ):

    # default-orchestration-client resolution — crew.py:227-233, VERBATIM:
        if isinstance(llm, str):
            client_cls = _resolve_supported_client(SUPPORTED_CLIENTS.get(llm.lower(), None))
            self._llm = client_cls(**kwargs) if client_cls else None
        elif isinstance(llm, AbstractClient):
            self._llm = llm  # Optional LLM for orchestration tasks
        else:
            client_cls = _resolve_supported_client(SUPPORTED_CLIENTS.get("google"))
            self._llm = client_cls(**kwargs) if client_cls else None

    # run_loop lazy fallback — crew.py:2125-2132, VERBATIM:
        if not self._llm:
            # FEAT-523 (TASK-2852): lazy import — core must not import a
            # provider module at module scope (AC-3)
            from ....clients.google import GoogleGenAIClient
            self._llm = GoogleGenAIClient(model="gemini-2.5-pro", max_tokens=8192)

    # summary executive fallback — crew.py:4379-4383, VERBATIM:
        if mode == "executive_summary" and not self._llm:
            try:
                self.logger.warning("No LLM provided for executive summary. Defaulting to Google GenAI.")
                self._llm = _resolve_supported_client(SUPPORTED_CLIENTS["google"])()

    # infographic ResultAgent — crew.py:609, ALREADY COVERED, do not touch:
        agent_cls(name=self.result_agent_name, llm=self._llm)

# packages/ai-parrot/src/parrot/bots/abstract.py
def _resolve_supported_client(entry): ...               # line 178
```

### Does NOT Exist

- ~~`AgentCrew.google_api_key`~~ (public attribute) — the spec fixes the attribute as
  the private `self._google_api_key`. Do not add a public alias or property.
- ~~`AgentCrew._llm_kwargs`~~ — `AgentCrew` is NOT an `AbstractBot`. It has no
  `_llm_kwargs`. Its extra kwargs go straight into the client ctor as `**kwargs`.
- ~~`SUPPORTED_CLIENTS["gemini"]`~~ — the key is `"google"`; there is no `"gemini"` key.
- ~~a second `**kwargs` anchor~~ — `        **kwargs,` occurs 8 times in `crew.py`.
  NEVER anchor on it; anchor on `        infographic_theme: Optional[str] = None,`
  (1 occurrence).
- ~~`GeminiLiveClient` / `GeminiOpenAICompatClient` imported in crew.py~~ — only
  `GoogleGenAIClient` is, and only lazily inside `run_loop`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/crew.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew.__init__",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew.run_loop",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew.summary",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#_resolve_supported_client"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **`google_api_key` must be an explicit named parameter, never left in `**kwargs`.**
  `crew.py:228`/`:233` forward `**kwargs` straight into the client constructor —
  a stray `google_api_key=` kwarg would reach `GoogleGenAIClient(...)` and blow up.
- **Do not override a caller-supplied `api_key`.** Spec §7: "Crew `**kwargs` already
  flows into the default client. Do not also add `api_key` when the caller already
  passed one in `kwargs`."
- **The `isinstance(llm, str)` branch is Google-conditional.** `llm="openai"` must
  NOT receive the Google key. Gate that branch on `llm.lower() in GOOGLE_PROVIDER_KEYS`.
- **The `isinstance(llm, AbstractClient)` branch is untouched** — a live instance
  carries its own credentials (AC2).
- Set `self._google_api_key` **before** any code path that can read it.
- `AgentCrew(...)` with no `google_api_key` must behave byte-for-byte as before (AC8).
- Keep the FEAT-523 lazy import in `run_loop` exactly where it is; only the ctor call
  gains a kwarg.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `from .credentials import GOOGLE_PROVIDER_KEYS` import — *why*: the string branch must distinguish a Google provider string from any other.
2. Add the parameter + its docstring entry, then store `self._google_api_key` — *why*: the two lazy fallbacks read the attribute, so it must exist on every instance.
3. Rewrite the `crew.py:227-233` client-resolution block — *why*: it is the G2 site and both the string and default branches need the conditional kwarg.
4. Add the kwarg at the `run_loop` and `summary` fallbacks — *why*: AC4 names both explicitly.
5. Write the tests with the client class patched — *why*: no network, and asserting the ctor kwargs is the only direct proof.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^from \.\.\.\.clients\.factory import SUPPORTED_CLIENTS$' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# AFTER — insert below `from ....clients.factory import SUPPORTED_CLIENTS` (verified: crew.py:59)
from .credentials import GOOGLE_PROVIDER_KEYS
```
**Why**: same-package sibling import, so no cycle and no provider module pulled in.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — signature)
```python
# occurrences: 1 (verified: grep -c '^        infographic_theme: Optional\[str\] = None,$' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# AFTER — insert below `        infographic_theme: Optional[str] = None,` (verified: crew.py:179),
# i.e. as the LAST named parameter, immediately before `        **kwargs,` (crew.py:180).
        google_api_key: Optional[str] = None,
```
**Why**: it must be a named parameter so it never leaks into `**kwargs` and from there
into the client constructor. Appending it last keeps every existing positional call
site valid (AC8). Also add to the `__init__` docstring Args block:
`google_api_key: Gemini API key for every Google client this crew builds by default
(orchestration LLM, run_loop / executive-summary fallbacks). None -> provider default
(GOOGLE_API_KEY).`

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — client resolution)
```python
# occurrences: 1 (verified: grep -c 'SUPPORTED_CLIENTS.get("google")' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# REPLACE the block at crew.py:227-233 (verified verbatim in the Codebase Contract
# above) with the following. The anchor is the unique
# `client_cls = _resolve_supported_client(SUPPORTED_CLIENTS.get("google"))` line.
        self._google_api_key = google_api_key
        if isinstance(llm, str):
            client_cls = _resolve_supported_client(SUPPORTED_CLIENTS.get(llm.lower(), None))
            # FILL IN: build the ctor kwargs — start from **kwargs and add
            # api_key=google_api_key ONLY when google_api_key is truthy,
            # llm.lower() is in GOOGLE_PROVIDER_KEYS, and "api_key" not in kwargs —
            # bounded by AC4 and by spec §7 ("do not override a caller-supplied
            # api_key") and AC3 (a non-Google provider string gets nothing).
            raise NotImplementedError
        elif isinstance(llm, AbstractClient):
            self._llm = llm  # Optional LLM for orchestration tasks
        else:
            client_cls = _resolve_supported_client(SUPPORTED_CLIENTS.get("google"))
            # FILL IN: same rule, minus the provider check — this branch is always
            # Google. Add api_key=google_api_key when truthy and "api_key" not in
            # kwargs; otherwise call client_cls(**kwargs) exactly as today —
            # bounded by AC4 and AC8 (no google_api_key -> identical behaviour).
            raise NotImplementedError
```
**Why**: this is the G2 site. The `AbstractClient` branch is reproduced unchanged on
purpose — a caller-supplied instance is never re-credentialed (AC2). Keeping
`client_cls(**kwargs) if client_cls else None`'s `None` guard is required: the Google
satellite may not be installed.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — run_loop fallback)
```python
# occurrences: 1 (verified: grep -c 'GoogleGenAIClient(model="gemini-2.5-pro", max_tokens=8192)' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# REPLACE the single line `            self._llm = GoogleGenAIClient(model="gemini-2.5-pro", max_tokens=8192)`
# (verified: crew.py:2132). Leave the FEAT-523 lazy import above it untouched.
            # FILL IN: call GoogleGenAIClient(model="gemini-2.5-pro", max_tokens=8192)
            # and add api_key=self._google_api_key ONLY when it is truthy — bounded
            # by AC4 and AC8 (unset -> the call must be byte-identical to today's).
            raise NotImplementedError
```
**Why**: passing `api_key=None` explicitly would still be safe here
(`client.py:189` uses `kwargs.pop("api_key", config.get("GOOGLE_API_KEY"))`, and a
popped `None` would override the fallback) — so it must be conditional, not
unconditional. That subtlety is the reason this is a `FILL IN` rather than a literal.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — summary fallback)
```python
# occurrences: 1 (verified: grep -c 'SUPPORTED_CLIENTS\["google"\])()' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# REPLACE the single line `                self._llm = _resolve_supported_client(SUPPORTED_CLIENTS["google"])()`
# (verified: crew.py:4383). Keep the surrounding try/except and warning untouched.
                # FILL IN: resolve the class as today, then instantiate it with
                # api_key=self._google_api_key ONLY when truthy, else with no args —
                # bounded by AC4 and AC8. Same api_key=None hazard as run_loop.
                raise NotImplementedError
```
**Why**: same conditional rule; the existing `try/except Exception` and its
`ValueError` re-raise are the contract for a missing satellite and must survive.

### `packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py` (CREATE)
```python
"""AgentCrew default-Google-client credential wiring (FEAT-575, TASK-3453)."""
import pytest

from parrot.bots.flows.crew import AgentCrew


class _FakeClient:
    """Records the kwargs it was constructed with."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)


def test_crew_default_llm_gets_key(monkeypatch):
    # FILL IN: patch the "google" entry in parrot.clients.factory.SUPPORTED_CLIENTS
    # to _FakeClient, build AgentCrew(google_api_key="k"), and assert
    # _FakeClient.last_kwargs["api_key"] == "k" — bounded by AC4.
    raise NotImplementedError


def test_crew_default_llm_without_key_unchanged(monkeypatch):
    # FILL IN: same patch, build AgentCrew() with NO google_api_key, assert
    # "api_key" not in _FakeClient.last_kwargs — bounded by AC8 (regression).
    raise NotImplementedError


def test_crew_explicit_api_key_kwarg_wins(monkeypatch):
    # FILL IN: AgentCrew(google_api_key="k", api_key="explicit") -> the client is
    # constructed with api_key="explicit" — bounded by spec §7.
    raise NotImplementedError


def test_crew_llm_instance_untouched():
    # FILL IN: pass an AbstractClient INSTANCE as llm together with
    # google_api_key="k"; assert crew._llm is that same object — bounded by AC2.
    raise NotImplementedError


def test_crew_non_google_llm_string_gets_no_key(monkeypatch):
    # FILL IN: patch a non-Google SUPPORTED_CLIENTS key (e.g. "openai") to
    # _FakeClient, build AgentCrew(llm="openai", google_api_key="k"), assert
    # "api_key" not in the recorded kwargs — bounded by AC3.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_run_loop_and_summary_fallback_use_key(monkeypatch):
    # FILL IN: with crew._llm forced to None and crew._google_api_key set, drive the
    # run_loop fallback and the summary(mode="executive_summary") fallback (patching
    # the lazily imported GoogleGenAIClient and the SUPPORTED_CLIENTS["google"] entry
    # respectively) and assert each recorded api_key == the crew key — bounded by AC4.
    raise NotImplementedError
```
**Why**: patching the registry entry rather than importing the satellite keeps this
test green whether or not `ai-parrot-client-google` is installed, and asserting the
recorded ctor kwargs is the only direct evidence for AC4/AC8.

### FILL IN checklist
- [ ] `crew.py::AgentCrew.__init__` string branch — Google-only conditional `api_key`; bounded by AC3/AC4/spec §7
- [ ] `crew.py::AgentCrew.__init__` default branch — conditional `api_key`; bounded by AC4/AC8
- [ ] `crew.py::AgentCrew.run_loop` fallback — conditional `api_key`; bounded by AC4/AC8
- [ ] `crew.py::AgentCrew.summary` fallback — conditional `api_key`, try/except preserved; bounded by AC4/AC8
- [ ] all six tests in `test_crew_google_key.py`

---

## Acceptance Criteria

- [ ] `AgentCrew(google_api_key="k")` constructs its default Google client with `api_key="k"` (AC4).
- [ ] The `run_loop` and executive-summary lazy fallbacks do the same (AC4).
- [ ] `AgentCrew(llm=<AbstractClient instance>, google_api_key="k")` leaves `_llm` as that instance (AC2).
- [ ] `AgentCrew(llm="openai", google_api_key="k")` passes no `api_key` (AC3).
- [ ] An explicit `api_key` in `kwargs` wins over `google_api_key` (spec §7).
- [ ] `AgentCrew(...)` without `google_api_key` behaves exactly as before (AC8).
- [ ] `grep -n "google_api_key" packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` shows it as a named parameter, never popped from `kwargs`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/crew/test_nodes.py -q`

---

## Test Specification

See the blueprint's test block — it IS the scaffold. `test_crew_default_llm_without_key_unchanged`
is the AC8 regression guard and must not be dropped.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3451 must be done; `GOOGLE_PROVIDER_KEYS` must exist in `credentials.py`
3. **Verify the Codebase Contract** — re-read `crew.py:156-180`, `:227-233`, `:2125-2132`, `:4379-4383`; if any block has moved or changed, update the contract FIRST
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3453-agentcrew-init-google-key.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) via native seat `sonnet`
**Date**: 2026-09-19
**Notes**: Added `google_api_key: Optional[str] = None` to `AgentCrew.__init__`
(before `**kwargs`), stored as `self._google_api_key`. Threaded it into the
default Google orchestration client construction and the two lazy fallbacks
(`run_loop`, executive-summary `summary()`), passing `api_key=` only when set
and not already present in kwargs. Did not touch `from_definition` (TASK-3454).
Created `test_crew_google_key.py` (6 tests: AC2 instance untouched, AC3 non-Google
string untouched, AC4 all three sites get the key, AC8 no-key path unchanged,
explicit api_key kwarg wins). Test run: `test_crew_google_key.py` +
`test_crew_credentials.py` + `test_nodes.py` → 41 passed. `ruff check` flagged
2 pre-existing `B905 zip() without strict=` findings at crew.py:1325/2723,
outside this task's diff hunks — pre-existing, deferred to feature-completion
ledger, not fixed here (scope discipline).

**Deviations from spec**: none
