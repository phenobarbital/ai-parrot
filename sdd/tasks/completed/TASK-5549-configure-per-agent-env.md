# TASK-5549: Apply `<AGENT>_MODEL` / `<AGENT>_<PROVIDER>_API_KEY` in `AbstractBot.configure()`

**Feature**: FEAT-882 — Per-Agent Env LLM Credentials + AgentsFlow Default Key
**Spec**: `sdd/specs/per-agent-env-llm-credentials.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5548
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 + §2 precedence table (rows #1–#4) and rev 0.2 component-default detection.
`configure()` is the one choke point every construction route (registry, `AgentCrew`, `AgentsFlow`,
the Agent HTTP handler, direct instantiation) passes through before the LLM client is built
(`abstract.py:1680`). This task makes an agent read its own model and key from the environment there,
with D2's precedence: a live client instance and an explicit credential always win; the env beats the
`llm`/`model` declared in code, a `CrewDefinition` or the DB; and the env key beats component defaults
(`CREW_*`, `AGENT_*`, `EXPERT_*`, `FLOW_*`) already sitting in `llm_kwargs`.

---

## Scope

- Add `AbstractBot._apply_agent_env_overrides()` returning `(llm, model, llm_kwargs)` for `_resolve_llm_config`.
- Call it from `configure()` in place of the direct `self._llm_raw` / `self._llm_kwargs` arguments.
- When `<AGENT>_MODEL` applies, make it the agent's `_llm_model` (ask()/conversation() read it).
- Reserved names (`AGENT`, `CREW`, `FLOW`, `DEFAULT`, `EXPERT_*` components): log a WARNING and skip the per-agent lookup.
- Create `packages/ai-parrot/tests/test_per_agent_env_credentials.py`.

**NOT in scope**: the resolver functions (TASK-5548), AgentsFlow (TASK-5550), docs (TASK-5552); any change
to `_resolve_llm_config`, `_create_llm_client`, `clients/base.py`, crew credentials, the Agent handler or experts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `_apply_agent_env_overrides` + configure wiring |
| `packages/ai-parrot/tests/test_per_agent_env_credentials.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# abstract.py already imports (module level):
from typing import Any, ClassVar, Dict, List, Sequence, Tuple, Type, Union, Optional, AsyncIterator, TYPE_CHECKING  # verified: abstract.py:6
from ..clients.base import LLM_PRESETS, AbstractClient   # verified: abstract.py:36
# NEW — import LAZILY inside the method (abstract.py does not import llm_defaults today; keep bots' import time lean):
from ..llm_defaults import (  # created by TASK-5548 in packages/ai-parrot/src/parrot/llm_defaults.py
    COMPONENTS, agent_env_token, is_component_default_key, resolve_agent_api_key, resolve_agent_llm,
)
# tests:
from parrot.bots.agent import BasicAgent        # verified: bots/agent.py:40 (class BasicAgent(Chatbot, NotificationMixin))
from parrot import llm_defaults as ld           # verified: tests/unit/test_llm_defaults.py:5
from parrot.clients import factory              # verified: tests/unit/test_llm_defaults.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
_default_llm: str = "google"                                            # :235
self._llm_raw = llm                                                      # :483
self._llm_model_explicit = _explicit_llm_model not in (None, "")        # :509
self._llm_model = _explicit_llm_model or self.default_model             # :510  (non-empty even when not explicit)
self._llm_kwargs = kwargs.get("llm_kwargs", {})                         # :547  SHARED with AgentDefinition.config — never mutate
def _parse_llm_string(self, llm: str) -> Tuple[str, Optional[str]]:    # :847  "provider:model" -> (provider, model|None)
def _resolve_llm_config(self, llm=None, model=None, preset=None, model_config=None, **kwargs) -> LLMConfig  # :851
    # string llm -> provider/model parsed; explicit `model` arg wins over parsed; **kwargs -> config.extra (fresh dict)
# configure(), LLM section:
model_arg = self._llm_model if self._llm_model_explicit else None       # :1680
config = self._resolve_llm_config(                                      # :1681
    llm=self._llm_raw, model=model_arg, preset=self._llm_preset, **self._llm_kwargs   # :1682
)
if not self._llm_model and config.model:                                # just below — mirrors model onto _llm_model
    self._llm_model = config.model

# TASK-5548 (packages/ai-parrot/src/parrot/llm_defaults.py)
COMPONENTS: tuple[str, ...]   # ("AGENT","CREW","FLOW","EXPERT_JUDGMENT","EXPERT_BALANCED","EXPERT_TEMPLATED")
def agent_env_token(name: str) -> str
def resolve_agent_llm(name: str, *, default_provider: str) -> Optional[ComponentLLM]   # raises ValueError on malformed
def resolve_agent_api_key(name: str, provider: str) -> Optional[str]
def is_component_default_key(api_key: Optional[str], provider: str) -> bool

# test pattern: offline BasicAgent + configure() — packages/ai-parrot/tests/docs/test_getting_started_claims.py:370-397
agent = BasicAgent(name="HelperAgent", llm="google", from_database=False); await agent.configure()
```

### Does NOT Exist
- ~~`AbstractBot.agent_id`~~ — use `self.name`.
- ~~`AbstractBot._apply_agent_env_overrides`~~ — created by THIS task.
- ~~`from ..llm_defaults import ...` at abstract.py module level~~ — none today; keep the import inside the method.
- ~~`LLMConfig.api_key`~~ — no such field; the key travels as `llm_kwargs["api_key"]` -> `config.extra["api_key"]` -> client kwargs (`abstract.py:1066-1074`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_per_agent_env_credentials.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._resolve_llm_config",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._parse_llm_string",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Precedence (spec §2): #1 client instance -> return everything unchanged; #2 explicit credential
  (`credentials_file`, `credentials`, `vertexai`, or an `api_key` that is NOT a component default) ->
  keep it, no env key; #3 env; #4 declared llm/model.
- The key is resolved for the provider that RESULTS from the model decision.
- If the env switches the provider and `llm_kwargs["api_key"]` is a component default of the OLD
  provider, drop it (it would be sent to the wrong provider) unless a per-agent key for the new provider
  replaces it. If an explicit credential coexists with an env provider switch, keep the credential and
  log a WARNING naming the variable (no values).
- Never mutate `self._llm_kwargs`; return a copy.
- Async-first is unaffected (pure sync helper); `self.logger` only; never log a key.

---

## Implementation Blueprint

### Steps (in order)
1. Insert `_apply_agent_env_overrides` directly above `_resolve_llm_config` — *why*: it is a pre-processor of that method's arguments and belongs next to it.
2. Replace the two-statement call in `configure()` — *why*: this is the single choke point every construction route passes.
3. Write the tests and run them — *why*: AC1 (no env -> unchanged) is the regression guard for every existing bot.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — 1/2)
```python
# occurrences: 1 (verified: grep -c '    def _resolve_llm_config(' abstract.py)
# BEFORE — insert above `    def _resolve_llm_config(` (verified: abstract.py:851)
    def _apply_agent_env_overrides(self) -> tuple[Any, Optional[str], dict[str, Any]]:
        """Return ``(llm, model, llm_kwargs)`` for ``_resolve_llm_config`` (FEAT-882).

        A live client instance is returned unchanged. ``<AGENT>_MODEL`` replaces the declared
        provider/model and becomes ``self._llm_model``. ``<AGENT>_<PROVIDER>_API_KEY`` fills
        ``api_key`` in a COPY of ``llm_kwargs`` unless an explicit credential is present; a component
        default key (CREW/AGENT/EXPERT/FLOW) is not explicit and is replaced.

        Raises:
            ValueError: When ``<AGENT>_MODEL`` is malformed (names the variable).
        """
        from ..llm_defaults import (  # noqa: PLC0415 — keep llm_defaults out of bots' import time
            COMPONENTS,
            agent_env_token,
            is_component_default_key,
            resolve_agent_api_key,
            resolve_agent_llm,
        )

        llm: Any = self._llm_raw
        model: Optional[str] = self._llm_model if self._llm_model_explicit else None
        llm_kwargs: dict[str, Any] = dict(self._llm_kwargs or {})
        if isinstance(llm, AbstractClient):
            return llm, model, llm_kwargs
        token = agent_env_token(self.name or "")
        if not token:
            return llm, model, llm_kwargs
        if token in COMPONENTS or token == "DEFAULT":
            self.logger.warning(
                "Agent name %r maps to reserved env prefix %s_; per-agent LLM env variables are ignored",
                self.name,
                token,
            )
            return llm, model, llm_kwargs
        # FILL IN: current_provider from `llm` — str -> self._parse_llm_string(llm)[0].lower();
        #   None -> self._default_llm; client class -> getattr(llm, "client_name", None); else None.
        #   Bounded by spec §2 row #4.
        override = resolve_agent_llm(self.name, default_provider=current_provider or self._default_llm)
        provider = current_provider
        if override is not None:
            llm, model, provider = f"{override.provider}:{override.model}", override.model, override.provider
            self._llm_model = override.model
        # FILL IN: key step — explicit = credentials_file/credentials/vertexai truthy, or api_key truthy and
        #   not is_component_default_key(api_key, <provider it was injected for>); if not explicit and
        #   provider: key = resolve_agent_api_key(self.name, provider) -> llm_kwargs["api_key"] = key;
        #   provider switch: drop a component default of the old provider when no new key replaces it;
        #   explicit credential + switch -> self.logger.warning naming f"{token}_MODEL". Bounded by AC2-AC4.
        return llm, model, llm_kwargs

```
**Why this shape**: the method computes arguments and never touches `self._llm_kwargs` (AC8) — the dict
is shared with persisted crew definitions. Setting `self._llm_model` on override is required because the
mirror below the call only fills an EMPTY `_llm_model`, and `_llm_model` is already the class
`default_model`; without it ask() would keep sending the old model. Reserved tokens are skipped because an
agent named `crew` would otherwise read `CREW_GOOGLE_API_KEY` as its own key.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — 2/2)
```python
# occurrences: 1 (verified: grep -c 'model_arg = self._llm_model if self._llm_model_explicit else None' abstract.py)
# REPLACE the three lines at abstract.py:1680-1682:
#                    model_arg = self._llm_model if self._llm_model_explicit else None
#                    config = self._resolve_llm_config(
#                        llm=self._llm_raw, model=model_arg, preset=self._llm_preset, **self._llm_kwargs
# WITH:
                    llm_arg, model_arg, llm_kwargs = self._apply_agent_env_overrides()
                    config = self._resolve_llm_config(
                        llm=llm_arg, model=model_arg, preset=self._llm_preset, **llm_kwargs
```
**Why**: keeps the closing `)` and everything after it untouched; the rest of the block reads `config`.

### `packages/ai-parrot/tests/test_per_agent_env_credentials.py` (CREATE)
```python
"""FEAT-882 — per-agent env model/key applied in AbstractBot.configure()."""

import pytest

from parrot import llm_defaults as ld
from parrot.bots.agent import BasicAgent
from parrot.clients import factory


class _FakeClient:
    """Records constructor kwargs instead of reaching a provider."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Hermetic FEAT-882 variables layered over the real config; offline google/openai clients."""
    values: dict[str, str] = {}
    real_get = ld.config.get
    monkeypatch.setattr(
        ld.config, "get", lambda key, *args, **kwargs: values[key] if key in values else real_get(key, *args, **kwargs)
    )
    monkeypatch.setitem(factory.SUPPORTED_CLIENTS, "google", _FakeClient)
    monkeypatch.setitem(factory.SUPPORTED_CLIENTS, "openai", _FakeClient)
    return values


# FILL IN: the tests listed in the Test Specification — bounded by AC1-AC6; construct agents with
#   BasicAgent(name="feat882-agent", llm=..., from_database=False) and assert on the
#   (llm, model, llm_kwargs) tuple of agent._apply_agent_env_overrides(); one test drives a full
#   `await agent.configure()` and asserts _FakeClient.last_kwargs["api_key"] (pattern:
#   tests/docs/test_getting_started_claims.py:370-397). If configure() needs a service that is not
#   available offline, monkeypatch that bot method to a no-op — never drop the api_key assertion.
#   If parrot.clients.factory's lazy entry-point discovery overwrites the setitem'd entries, switch the
#   fixture to that file's EntryPoint pattern (test_getting_started_claims.py:378-389).
```

### FILL IN checklist
- [ ] `_apply_agent_env_overrides` current-provider branches — spec §2 row #4.
- [ ] `_apply_agent_env_overrides` key step + provider-switch handling — AC2–AC4.
- [ ] Test bodies — AC1–AC6.

---

## Acceptance Criteria

- [ ] AC1: no FEAT-882 variable set -> `_apply_agent_env_overrides()` returns `(self._llm_raw, model_arg, <equal copy of self._llm_kwargs>)`; `configure()` builds the same client as before.
- [ ] AC2: `<AGENT>_MODEL=openai:gpt-x` overrides a class/kwarg `llm="google"`; `agent._llm_model == "gpt-x"` after configure.
- [ ] AC3: the key follows the resulting provider (`FEAT882_AGENT_OPENAI_API_KEY` after a switch to openai).
- [ ] AC4: an explicit `llm_kwargs` credential beats the env key; a component default (e.g. value equal to `CREW_GOOGLE_API_KEY`) is replaced by the env key.
- [ ] AC5: a live client instance as `llm` ignores every env variable.
- [ ] AC6: `self._llm_kwargs` is the same object with the same content after configure (no mutation).
- [ ] Reserved name (`name="crew"`) logs a WARNING and ignores `CREW_MODEL`/`CREW_GOOGLE_API_KEY` as per-agent vars.
- [ ] No key value appears in captured logs; `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_per_agent_env_credentials.py -q`
- `pytest packages/ai-parrot/tests/unit/test_llm_defaults.py -q`

---

## Test Specification

```python
def test_configure_no_env_unchanged(env): ...
def test_configure_env_model_overrides_declared_llm(env): ...
def test_configure_env_model_bare_inherits_provider(env): ...
def test_configure_env_key_provider_follows_model(env): ...
def test_configure_explicit_credential_beats_env_key(env): ...
def test_configure_component_default_key_replaced_by_env_key(env): ...
def test_configure_client_instance_ignores_env(env): ...
def test_configure_does_not_mutate_shared_llm_kwargs(env): ...
def test_configure_reserved_name_warns_and_ignores(env, caplog): ...
def test_configure_malformed_env_model_raises(env): ...
async def test_configure_passes_env_key_to_client(env): ...   # full configure() -> _FakeClient.last_kwargs["api_key"]
```

---

## Agent Instructions

1. Work in the feature worktree; never on `dev`. TASK-5548 must be `done` in `sdd/tasks/index/per-agent-env-llm-credentials.json`.
2. Verify the contract (re-run the `grep -c` of both anchors); set the task `in-progress`.
3. Implement from the blueprint; complete every `# FILL IN:`; run the Validation Commands.
4. Commit only the listed files; `parrot sdd task close TASK-5549 per-agent-env-llm-credentials verified`; fill the Completion Note.

---

## Completion Note


- Task: TASK-5549
- Feature: per-agent-env-llm-credentials
- Implementation SHA: fda6a81904c982ca303ee41a7f21f40df97c8de8
- Closed at (UTC): 2026-11-12T19:31:07+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 517s · Tokens: n/a |
