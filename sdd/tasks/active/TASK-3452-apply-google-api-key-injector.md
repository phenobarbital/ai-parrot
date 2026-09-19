# TASK-3452: `apply_google_api_key()` — non-mutating credential injector

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3451
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half). `apply_google_api_key()` is the one place in
FEAT-575 that touches an agent's private LLM state. It runs on an **already
constructed, not yet configured** agent and adds `api_key` to its `_llm_kwargs`
so that `AbstractBot.configure()` later forwards it into the Google client
through `LLMConfig.extra`.

It is the feature's security-critical function: `agent._llm_kwargs` is the SAME
dict object as `AgentDefinition.config["llm_kwargs"]`, which is persisted to Redis
and returned by `GET /api/v1/crew`. Mutating it in place would leak `CREW_AI_KEY`
into the definition (AC7).

TASK-3454 (`from_definition`) and TASK-3456 (`CrewHandler`) both call this function.

---

## Scope

- Add `apply_google_api_key(agent, api_key) -> bool` to the existing
  `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py`.
- Add its unit tests to the existing
  `packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py`.

**NOT in scope**:
- `crew.py`, `manager.py`, `handler.py` call sites — TASK-3453..3456.
- Any change to `parrot/bots/abstract.py`. The helper only *reads* `_llm_raw`,
  `_default_llm` and *rebinds* `_llm_kwargs`; `abstract.py` is untouched by the
  whole feature (spec §2 Integration Points).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` | MODIFY | Append `apply_google_api_key` |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py` | MODIFY | Append injector tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already in credentials.py after TASK-3451 — reuse, do not re-import:
#   GOOGLE_PROVIDER_KEYS, _CREDENTIAL_KWARGS, is_google_llm, logger
from typing import Any, Optional
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py — READ ONLY, never modified
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin,
                  ToolInterface, VectorInterface, ABC):     # line ~200
    __slots__ = ("name", "_llm", "_llm_config", "_llm_kwargs", "_prompt_pipeline")  # line ~213
    _default_llm: str = "google"                            # line 220

    def __init__(self, ...):
        # A class-level ``llm`` attribute is honoured when no ``llm`` arg arrives:
        if llm is None:                                      # line 448
            _cls_llm = getattr(type(self), "llm", None)      # line 449
            if _cls_llm is not None and not isinstance(_cls_llm, property):  # line 450
                llm = _cls_llm                               # line 451
        self._llm_raw = llm                                  # line 452
        ...
        self._llm_kwargs = kwargs.get("llm_kwargs", {})      # line 516 — SAME OBJECT as the caller's dict
        self._llm_kwargs["temperature"] = _resolve_llm_kwarg("temperature", ...)  # line 517
        self._llm_kwargs["max_tokens"] = _resolve_llm_kwarg("max_tokens", 4096)   # line 518

    # configure() — how the injected key reaches the client (NOT modified here):
    config = self._resolve_llm_config(
        llm=self._llm_raw, model=model_arg, preset=self._llm_preset, **self._llm_kwargs
    )                                                        # lines 1537-1539
    # _apply_llm_params: config.extra.update(kwargs)         # line 998
    # _create_llm_client: client = config.client_class(..., **config.extra)  # lines 1025-1033

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient):                     # line 101
    self.api_key = kwargs.pop("api_key", config.get("GOOGLE_API_KEY"))  # line 189

# packages/ai-parrot/src/parrot/models/crew_definition.py
class AgentDefinition(BaseModel):                            # line 31, model_config extra="forbid"
    config: Dict[str, Any]                                   # forwarded as **kwargs to the agent ctor
```

### Does NOT Exist

- ~~`AgentDefinition.api_key`~~ / ~~`AgentDefinition.credentials`~~ — not fields, and
  the model is `extra="forbid"`. Do NOT add them.
- ~~`AbstractBot.set_api_key()`~~ / any public credential setter — does not exist.
- ~~a top-level `api_key` in `AgentDefinition.config`~~ is NOT forwarded to the client
  by `AbstractBot`. Only `llm_kwargs.api_key` counts as "credential provided".
- ~~`agent.llm_kwargs`~~ (no underscore) — the attribute is `_llm_kwargs`.
- ~~`AbstractBot.__init__` deep-copies `llm_kwargs`~~ — it does NOT
  (`abstract.py:516` assigns by reference). That is precisely the hazard here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **REBIND, never mutate.** `agent._llm_kwargs = {**agent._llm_kwargs, "api_key": key}`.
  `agent._llm_kwargs.update(...)` or `agent._llm_kwargs["api_key"] = key` would write
  the secret into `AgentDefinition.config["llm_kwargs"]` and from there into Redis
  and `GET /api/v1/crew`. This is AC7 and it is the whole reason the function exists.
- **CORRECTION to spec §4's `test_apply_does_not_mutate_definition_dict` wording.**
  The definition's `llm_kwargs` dict is NOT pristine after agent construction:
  `AbstractBot.__init__` already writes `temperature` and `max_tokens` into it in
  place (`abstract.py:517-518`), *before* this helper ever runs. That is
  pre-existing behaviour and out of scope. The test must therefore assert
  **`"api_key" not in definition_llm_kwargs`** — NOT that the dict is unchanged.
  Asserting the latter will fail for reasons unrelated to this feature.
- **Timing.** The helper must run after construction and before `configure()`.
  An agent class that builds its client inside `__init__`, or overrides
  `configure()` to ignore `_llm_kwargs`, will not pick the key up. Document it in
  the docstring; do not try to fix it (spec §7 Known Risks).
- **`getattr` with defaults for every private read**, so a non-`AbstractBot` agent
  is a clean `False` no-op rather than an `AttributeError`.
- A truthy `vertexai` in `_llm_kwargs` counts as "credential provided": Vertex AI
  agents ignore `api_key` entirely (spec §7).

---

## Implementation Blueprint

### Steps (in order)
1. Append `apply_google_api_key` to `credentials.py` below `is_google_llm` — *why*: it calls `is_google_llm`, and callers import both from this one module.
2. Append the six injector tests to the existing test module, reusing its `crew_key` fixture — *why*: the fixture contract is already established by TASK-3451.
3. Run the whole test file, not just the new tests — *why*: the module-level `_warned_unset` latch makes ordering matter.

### `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def is_google_llm' packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py)
# AFTER — append at end of file, below `def is_google_llm(...)` (created by TASK-3451)


def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool:
    """Inject ``api_key`` into a constructed, unconfigured agent's LLM kwargs.

    Rebinds ``agent._llm_kwargs`` to a NEW dict rather than mutating it. The
    existing dict is the very object held by ``AgentDefinition.config["llm_kwargs"]``
    (``abstract.py:516`` assigns by reference), which is persisted to Redis and
    returned by ``GET /api/v1/crew`` — mutating it would leak the credential.

    Must be called after the agent is constructed and before ``configure()``.
    An agent that builds its client inside ``__init__``, or that overrides
    ``configure()`` to ignore ``_llm_kwargs``, will not pick the key up.

    Args:
        agent: A constructed, not-yet-configured agent. Non-``AbstractBot``
            objects are a no-op.
        api_key: The credential to inject. Falsy values are a no-op.

    Returns:
        ``True`` when the key was injected, ``False`` otherwise.
    """
    if not api_key:
        return False
    if not hasattr(agent, "_llm_raw") or not hasattr(agent, "_llm_kwargs"):
        return False
    if not is_google_llm(getattr(agent, "_llm_raw", None), getattr(agent, "_default_llm", "google")):
        return False
    llm_kwargs = getattr(agent, "_llm_kwargs", None) or {}
    # FILL IN: return False when llm_kwargs already holds ANY key in
    # _CREDENTIAL_KWARGS or a truthy "vertexai" — bounded by AC2 (an explicit
    # credential, or Vertex AI, always wins and is left untouched).
    raise NotImplementedError
    # FILL IN: rebind (never mutate) agent._llm_kwargs to {**llm_kwargs,
    # "api_key": api_key}, log at debug WITHOUT the key value, and return True —
    # bounded by AC1 and AC7.
```
**Why this shape**: the signature is fixed by spec §2 New Public Interfaces —
TASK-3454 and TASK-3456 call it as `apply_google_api_key(agent, key)`. The early
`hasattr` guard is what makes a non-`AbstractBot` agent a clean `False`. The two
`FILL IN` markers are deliberately separate so the credential-precedence branch and
the rebind are each reviewed on their own; the rebind form is NOT negotiable.

### `packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def test_get_key_warns_once_when_unset' packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py)
# AFTER — append at end of file; extend the existing import from
# parrot.bots.flows.crew.credentials with `apply_google_api_key`.


class _FakeAgent:
    """Minimal stand-in for a constructed, unconfigured AbstractBot."""

    _default_llm = "google"

    def __init__(self, llm=None, llm_kwargs=None):
        self._llm_raw = llm
        # Mirror abstract.py:516 — assignment BY REFERENCE, not a copy.
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}


def test_apply_injects_for_google_without_credential(crew_key):
    agent = _FakeAgent(llm="google:gemini-3.5-flash")
    assert apply_google_api_key(agent, crew_key) is True
    assert agent._llm_kwargs["api_key"] == crew_key


def test_apply_does_not_mutate_definition_dict(crew_key):
    # The dict an AgentDefinition would own, passed in by reference.
    definition_llm_kwargs = {"temperature": 0.1}
    agent = _FakeAgent(llm="google", llm_kwargs=definition_llm_kwargs)
    assert apply_google_api_key(agent, crew_key) is True
    # AC7: the credential must never reach the definition's dict. NOTE: this
    # asserts only the absence of api_key — AbstractBot itself writes
    # temperature/max_tokens into this same dict (abstract.py:517-518), so the
    # dict is NOT otherwise pristine and must not be compared for equality.
    assert "api_key" not in definition_llm_kwargs
    assert agent._llm_kwargs is not definition_llm_kwargs


@pytest.mark.parametrize(
    "llm_kwargs",
    [
        {"api_key": "own"},
        {"credentials_file": "/tmp/sa.json"},
        {"credentials": object()},
        {"vertexai": True},
    ],
)
def test_apply_respects_explicit_credential(crew_key, llm_kwargs):
    # FILL IN: build a Google _FakeAgent with these llm_kwargs, assert the call
    # returns False and the dict is unchanged — bounded by AC2.
    raise NotImplementedError


def test_apply_skips_non_google_and_falsy_key(crew_key):
    # FILL IN: llm="openai:gpt-5" -> False; and a Google agent with api_key=None
    # -> False — bounded by AC3 and by "a falsy api_key is a no-op".
    raise NotImplementedError


def test_apply_class_level_llm_declaration(crew_key):
    # FILL IN: subclass _FakeAgent with a CLASS attribute llm = "google:gemini-3.5-flash",
    # construct it so _llm_raw picks that class attr up exactly as abstract.py:448-452
    # does, and assert the key is injected — bounded by AC1 ("via a class-level llm").
    raise NotImplementedError


def test_apply_ignores_non_abstractbot_agent(crew_key):
    # FILL IN: pass an object with neither _llm_raw nor _llm_kwargs and assert
    # False with no exception — bounded by spec §3 M1 ("not AbstractBot -> False").
    raise NotImplementedError
```
**Why**: `_FakeAgent` reproduces `abstract.py:516`'s by-reference assignment, which is
the only way `test_apply_does_not_mutate_definition_dict` can actually prove AC7.
Note the falsy `vertexai` case is intentionally absent from the parametrize list —
only a *truthy* `vertexai` blocks injection.

### FILL IN checklist
- [ ] `credentials.py::apply_google_api_key` — credential-precedence branch (`_CREDENTIAL_KWARGS` + truthy `vertexai`); bounded by AC2
- [ ] `credentials.py::apply_google_api_key` — rebind + debug log without the key + `return True`; bounded by AC1/AC7
- [ ] `test_apply_respects_explicit_credential` — bounded by AC2
- [ ] `test_apply_skips_non_google_and_falsy_key` — bounded by AC3
- [ ] `test_apply_class_level_llm_declaration` — bounded by AC1
- [ ] `test_apply_ignores_non_abstractbot_agent` — bounded by spec §3 M1

---

## Acceptance Criteria

- [ ] A Google agent with no credential gets `_llm_kwargs["api_key"]` set (AC1).
- [ ] The dict passed in as `llm_kwargs` never gains `api_key`, and `agent._llm_kwargs` is a different object afterwards (AC7).
- [ ] An explicit `api_key` / `credentials_file` / `credentials` / truthy `vertexai` is left untouched and returns `False` (AC2).
- [ ] A non-Google agent, a falsy `api_key`, and a non-`AbstractBot` object each return `False` (AC3).
- [ ] A class-level `llm = "google:..."` declaration is detected (AC1).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py -q`

---

## Test Specification

See the blueprint's test block — it IS the scaffold. Every `FILL IN` test body must
be completed and passing, and the whole file must pass (not just the new tests).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3451 must be done; `is_google_llm`, `_CREDENTIAL_KWARGS` and the `crew_key` fixture must already exist
3. **Verify the Codebase Contract** — re-read `abstract.py:448-452` and `:516-518`; if the by-reference assignment at `:516` has changed, STOP and report before implementing
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3452-apply-google-api-key-injector.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
