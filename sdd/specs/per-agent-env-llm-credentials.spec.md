---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [llm-defaults, credentials, agentsflow, env-config, api-keys]
docs:
  policy: required
  pages: [wiki/operations/configuration/llm-defaults.md]
  api_modules: [parrot.llm_defaults]
---

# Feature Specification: Per-Agent Env LLM Credentials + AgentsFlow Default Key

**Feature ID**: FEAT-882
**Date**: 2026-11-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-796 (`per-component-llm-defaults`) gave each *component* its own model and API key:
`AGENT_*`, `CREW_*`, `EXPERT_<TIER>_*`, resolved by `parrot.llm_defaults`. Two gaps remain:

1. **AgentsFlow has no default key.** `AgentCrew` injects `CREW_GOOGLE_API_KEY` into every Google
   agent that carries no credential of its own (`crew.py:859`), so crew traffic can be metered
   and rotated apart from `GOOGLE_API_KEY`. `AgentsFlow` has no equivalent: no `FLOW_LLM`, no
   `FLOW_<PROVIDER>_API_KEY`, no `component="FLOW"` usage tag. Agents run inside a flow bill
   to the process-wide provider key.
2. **No per-agent env lookup.** An individual agent cannot read its own model or credential from
   the environment. The only per-agent channel is `llm_kwargs["api_key"]` in code or in a
   `CrewDefinition`/DB row. Operators cannot give agent `odoo-helpdesk` its own key, or pin it
   to `google:gemini-3.5-flash`, without editing code or data.

Structural constraint found while researching: `AgentsFlow` does **not** construct its agents.
It resolves already-built instances from an `AgentRegistry`
(`flow.py:635 agent_registry.get_bot_instance(agent_ref)`), and the registry calls
`instance.configure()` before handing them out (`registry.py:217`). The crew-style
"inject before `configure()`" trick (`apply_google_api_key`) therefore cannot be the only
mechanism for flows.

### Goals

- G1. **Per-agent env override.** At `configure()` time every `AbstractBot` reads, from the
  environment, `<AGENT>_MODEL` (value `provider:model`, e.g. `google:gemini-3.5-flash`) and
  `<AGENT>_<PROVIDER>_API_KEY`, where `<AGENT>` is the bot's `name` normalized to an env token
  (§2). This works for every construction path (registry, crew, flow, direct instantiation).
- G2. **FLOW component.** `FLOW_LLM` and `FLOW_<PROVIDER>_API_KEY` exist with the same cascade
  semantics as `CREW_*` (no legacy alias). Agents placed in an `AgentsFlow` that carry no
  explicit credential receive the FLOW key, where the flow can still influence them
  (unconfigured agents; see Decision D3 for already-configured registry instances).
- G3. `UsageRecord.component == "FLOW"` for LLM calls made inside `AgentsFlow.run_flow()`.
- G4. Zero behaviour change when none of the new variables is set.
- G5. Deterministic precedence, documented (§2 table). Explicit credentials and live client
  instances always win; no key value is ever logged.

### Non-Goals (explicitly out of scope)

- Changing `clients/base.py` or adding a client-level "rebind API key at runtime" method.
- Per-agent env for non-LLM secrets (tool credentials, DB passwords).
- Per-agent `<AGENT>_LLM` for temperature/max_tokens/top_k etc. Only model + key.
- Replacing FEAT-796's `AGENT_*` / `CREW_*` / `EXPERT_*` components or `CREW_AI_KEY` alias.
- A UI or HTTP surface to edit these variables.
- Hot-reload: env is read when the agent is configured, not on every call.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:5d29cdf2be8ffeda4deeac420d97d0de452e7f00b93099817b924bfe95f07842 evaluation_digest=sha256:490c87eaa9660cc19052ea8c3beccc0374d35fa0fa3e8878ce05fedc39fcde9b rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One new resolver pair in `parrot/llm_defaults.py` serves both gaps.

**Per-agent identity token.** `<AGENT>` = `bot.name`, upper-cased, every run of characters
outside `[A-Za-z0-9]` replaced by a single `_`, leading/trailing `_` stripped
(`odoo-helpdesk` → `ODOO_HELPDESK`). *Resolved with the author (D1).*

**Variables.**

| Variable | Meaning |
|---|---|
| `<AGENT>_MODEL` | `provider:model` for that agent (bare `model` inherits the agent's current provider) |
| `<AGENT>_<PROVIDER>_API_KEY` | key for that agent; `<PROVIDER>` uses `provider_key_token()` (`GOOGLE` for the whole Google family) |
| `FLOW_LLM` | model default for agents of an `AgentsFlow` (same format as `CREW_LLM`) |
| `FLOW_<PROVIDER>_API_KEY` | default key for agents of an `AgentsFlow`, e.g. `FLOW_GOOGLE_API_KEY` |

**Precedence** (highest first) *(D2 — env beats code, never beats an instance or credentials)*:

| # | Source | Model | Key |
|---|---|---|---|
| 1 | Live `AbstractClient` instance as `llm` | wins; env ignored | wins; env ignored |
| 2 | Explicit credential in `llm_kwargs` (`api_key`, `credentials_file`, `credentials`, `vertexai`) | — | wins |
| 3 | `<AGENT>_MODEL` / `<AGENT>_<PROVIDER>_API_KEY` | overrides declared `llm`/`model` | applies |
| 4 | `llm` / `model` declared in code, `CrewDefinition` or DB | applies | — |
| 5 | Component default: `FLOW_*` (flow agents) / `CREW_*` (crew agents) / `AGENT_*` (handler) | applies when #4 absent | applies |
| 6 | `DEFAULT_LLM` | applies when #4,#5 absent | — |
| 7 | Provider-wide key (`GOOGLE_API_KEY`, …) | — | final fallback |

The key for #3 is resolved for the **provider that results from the model decision**
(so `ODOO_HELPDESK_MODEL=openai:gpt-5` selects `ODOO_HELPDESK_OPENAI_API_KEY`).

**Component-default keys are not "explicit" (rev 0.2).** `AgentCrew` (`apply_google_api_key`,
`credentials.py:123`), the Agent HTTP handler (`AGENT_<P>_API_KEY`) and `ExpertAgent`
(`EXPERT_<TIER>_<P>_API_KEY`) put their component default into `llm_kwargs["api_key"]` before
`configure()`, and FLOW injection (M3) does the same. Precedence #2 must not swallow those, or #3
could never beat #5. M1 therefore adds `COMPONENTS` and `is_component_default_key(api_key, provider)`:
an `api_key` whose value equals a configured `<COMPONENT>_<TOKEN>_API_KEY` (any of `COMPONENTS`) or
the legacy `CREW_AI_KEY` is treated as #5 and is replaced by `<AGENT>_<PROVIDER>_API_KEY` when that
is set. `credentials_file` / `credentials` / `vertexai` and any other `api_key` value stay #2.
Detection by value keeps the three existing injectors untouched.

**Where each gap is wired.**

- Gap 2 hooks `AbstractBot.configure()` immediately before `_resolve_llm_config(...)`
  (`abstract.py:1680`). That is the single choke point every construction route passes through,
  and it runs after the registry/crew/flow has finished building the bot. The override is
  computed into local `llm`/`model`/`llm_kwargs` copies and passed to `_resolve_llm_config`;
  `self._llm_kwargs` is **not** mutated (it is shared by reference with
  `AgentDefinition.config["llm_kwargs"]`, which is persisted and served by `GET /api/v1/crew`
  — see `credentials.py:123` docstring).
- Gap 1 mirrors `apply_google_api_key` for flows, generalized to any provider:
  `apply_component_api_key(agent, component)` called from `AgentsFlow.from_definition` for each
  resolved agent/agent-group member **only when the agent is not yet configured**
  (D3). Already-configured registry instances keep their client; for them the per-agent path
  (G1) is the supported way to give a key. This limitation is logged at INFO once per agent and
  documented, not papered over.
- `AgentsFlow.run_flow` is wrapped in `usage_component("FLOW")` exactly like
  `_crew_usage_scope` (`crew.py:150`).

### Component Diagram
```
env ──► llm_defaults.resolve_agent_llm(name) ─┐
                                              ├─► AbstractBot.configure() ─► _resolve_llm_config ─► client
env ──► llm_defaults.resolve_component_* ─────┘            ▲
                                                           │ (unconfigured agents only)
AgentsFlow.from_definition ─► apply_component_api_key(agent, "FLOW")
AgentsFlow.run_flow ────────► usage_component("FLOW")
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.llm_defaults` | extends | new `agent_env_token`, `resolve_agent_llm`, `resolve_agent_api_key`, `apply_component_api_key` |
| `AbstractBot.configure` | modifies | env override just before `_resolve_llm_config` |
| `AgentsFlow.from_definition` | modifies | FLOW key injection on unconfigured agents |
| `AgentsFlow.run_flow` | modifies | `usage_component("FLOW")` |
| `has_explicit_google_credential` | reuses | generalized check for non-Google providers |
| `observability.context.usage_component` | reuses | new tag value `FLOW` |

### Data Models
```python
# reuses parrot.llm_defaults.ComponentLLM (provider, model, source)
# `source` Literal gains "agent" (env override for a named agent)
```

### New Public Interfaces
```python
def agent_env_token(name: str) -> str: ...
def resolve_agent_llm(name: str, *, default_provider: str) -> Optional[ComponentLLM]: ...
def resolve_agent_api_key(name: str, provider: str) -> Optional[str]: ...
def apply_component_api_key(agent: Any, component: str) -> bool: ...
def is_component_default_key(api_key: Optional[str], provider: str) -> bool: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: resolver | yes | signatures below; `ValueError` naming the variable on malformed `<AGENT>_MODEL`; no key logging | — |
| M2: configure wiring | no | precedence table §2 is fixed, but the "is a credential explicit" + provider-after-model ordering needs care around `_llm_model_explicit` | subtle interaction with `_resolve_llm_config` model/kwargs handling |
| M3: FLOW key + usage tag | yes | unconfigured-only injection; reuse `has_explicit_*`; tag via `usage_component("FLOW")` | — |
| M4: docs | yes | extend `wiki/operations/configuration/llm-defaults.md` | — |

### Module 1: Resolver
- **Path**: `packages/ai-parrot/src/parrot/llm_defaults.py`
- **Responsibility**: env token normalization, per-agent model/key lookup, component-key injection helper.
- **Depends on**: existing `provider_key_token`, `_split`, `ComponentLLM`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/llm_defaults.py  (modifies)
  def agent_env_token(name: str) -> str:
      """Upper-case ``name``; collapse non-alphanumeric runs to ``_``; strip edge ``_``."""

  def resolve_agent_llm(name: str, *, default_provider: str) -> Optional[ComponentLLM]:
      """Parse ``<AGENT>_MODEL`` (``provider:model`` or bare model -> ``default_provider``).

      Returns None when unset/empty. Raises ValueError naming the variable when malformed or
      the provider is not a SUPPORTED_CLIENTS key.
      """  # reuses _split  # verified: llm_defaults.py:25

  def resolve_agent_api_key(name: str, provider: str) -> Optional[str]:
      """``<AGENT>_<PROVIDER_TOKEN>_API_KEY`` or None. Never logs the value."""
      # provider_key_token verified: llm_defaults.py:62

  COMPONENTS: tuple[str, ...] = (
      "AGENT", "CREW", "FLOW", "EXPERT_JUDGMENT", "EXPERT_BALANCED", "EXPERT_TEMPLATED",
  )
  """Every component with a ``<COMPONENT>_<PROVIDER>_API_KEY`` default (rev 0.2)."""

  def is_component_default_key(api_key: Optional[str], provider: str) -> bool:
      """True when ``api_key`` equals a configured component default for ``provider``.

      Checks ``<C>_<TOKEN>_API_KEY`` for every C in ``COMPONENTS`` plus legacy ``CREW_AI_KEY``.
      Falsy ``api_key`` -> False. Never logs a value.
      """

  def apply_component_api_key(agent: Any, component: str) -> bool:
      """Inject ``<COMPONENT>_<PROVIDER>_API_KEY`` into an UNCONFIGURED agent's llm_kwargs.

      Rebinds ``agent._llm_kwargs`` to a new dict (never mutates the shared one). No-op when
      the agent is configured, its ``llm`` is a live client instance, or llm_kwargs already
      carries api_key/credentials_file/credentials/vertexai. Returns True when injected.
      """
  ```

### Module 2: AbstractBot.configure wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: apply precedence #3 before building the LLM config.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies configure(), near :1680)
  def _apply_agent_env_overrides(self) -> tuple[Any, Optional[str], dict[str, Any]]:
      """Return ``(llm, model, llm_kwargs)`` for ``_resolve_llm_config``.

      llm instance -> unchanged. ``<AGENT>_MODEL`` set -> its provider/model replace the
      declared pair. Key: skip when llm_kwargs has an explicit credential; else
      ``<AGENT>_<PROVIDER>_API_KEY`` fills ``api_key`` in a COPY of llm_kwargs.
      """
  ```

### Module 3: AgentsFlow default key + usage tag
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
- **Responsibility**: apply FLOW defaults (`_apply_flow_defaults(agent)`) to every agent resolved in
  `from_definition` (single agents and decision-group members) **and** to the agent of every
  `AgentNode` passed to `add_node` (programmatic flows, rev 0.2); wrap `run_flow` in
  `usage_component("FLOW")`. `_apply_flow_defaults` skips configured agents (one INFO log per agent
  name per process), sets `_llm_raw` from `FLOW_LLM` only when the agent declares no `llm` **and**
  `FLOW_LLM` itself is set (`source == "component"`; `DEFAULT_LLM` alone changes nothing — G4), then
  calls `apply_component_api_key(agent, "FLOW")`.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # flow.py  (modifies from_definition near :635/:661 and run_flow :1226)
  # from ....observability.context import usage_component   # verified: crew.py:63 (relative form differs)
  ```

### Module 4: Docs
- **Path**: `wiki/operations/configuration/llm-defaults.md`
- **Responsibility**: add FLOW rows, the per-agent section, the precedence table and the
  already-configured-instance limitation.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_agent_env_token_normalizes` | M1 | `odoo-helpdesk`, `My Agent`, `a__b` → `ODOO_HELPDESK`, `MY_AGENT`, `A_B` |
| `test_resolve_agent_llm_unset_none` | M1 | unset/empty → `None` |
| `test_resolve_agent_llm_provider_model` | M1 | `google:gemini-3.5-flash` parsed; bare model inherits provider |
| `test_resolve_agent_llm_malformed_names_var` | M1 | bad value → `ValueError` containing `<AGENT>_MODEL` |
| `test_resolve_agent_api_key_google_family` | M1 | `gemini-live`/`google-compat` → `…_GOOGLE_API_KEY` |
| `test_apply_component_api_key_flow` | M1 | injects into unconfigured agent; copy semantics (shared dict not mutated) |
| `test_apply_component_api_key_noop_explicit` | M1 | each of api_key/credentials_file/credentials/vertexai blocks injection |
| `test_apply_component_api_key_noop_configured` | M1 | configured agent untouched |
| `test_configure_env_model_overrides_declared_llm` | M2 | `<AGENT>_MODEL` beats class `llm` |
| `test_configure_env_key_provider_follows_model` | M2 | model env switches provider → matching key var used |
| `test_configure_client_instance_ignores_env` | M2 | live client instance untouched |
| `test_configure_explicit_credential_beats_env_key` | M2 | explicit `llm_kwargs` credential wins |
| `test_configure_no_env_unchanged` | M2 | G4 regression |
| `test_flow_from_definition_injects_flow_key` | M3 | unconfigured Google agent gets `FLOW_GOOGLE_API_KEY` |
| `test_flow_configured_agent_not_injected` | M3 | registry-configured instance left alone |
| `test_flow_run_tags_usage_component` | M3 | `UsageRecord.component == "FLOW"` |
| `test_no_key_value_logged` | M1–M3 | caplog never contains the secret |

### Integration Tests
| Test | Description |
|---|---|
| `test_flow_agent_uses_per_agent_env_key_end_to_end` | registry agent + `<AGENT>_GOOGLE_API_KEY` inside a flow built via `from_definition`; client receives that key |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/test_llm_defaults.py
- packages/ai-parrot/tests/test_llm_defaults_documented.py
- packages/ai-parrot/tests/bots/flows/test_from_definition.py
- packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py
- packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py
- packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py
- packages/ai-parrot/tests/test_per_agent_env_credentials.py
- packages/ai-parrot/tests/bots/flows/test_flow_default_key.py
- packages/ai-parrot/tests/bots/flows/test_flow_per_agent_env_integration.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def agent_env(monkeypatch):
    monkeypatch.setenv("ODOO_HELPDESK_MODEL", "google:gemini-3.5-flash")
    monkeypatch.setenv("ODOO_HELPDESK_GOOGLE_API_KEY", "k-agent")
    monkeypatch.setenv("FLOW_GOOGLE_API_KEY", "k-flow")
```

---

## 5. Acceptance Criteria

- [ ] AC1: With none of the new variables set, every agent, crew, flow and expert behaves exactly as before (asserted).
- [ ] AC2: `<AGENT>_MODEL=provider:model` overrides the agent's declared `llm`/`model` at `configure()` for registry, crew, flow and directly-built agents; a live client instance is never overridden.
- [ ] AC3: `<AGENT>_<PROVIDER>_API_KEY` is used as that agent's key for the provider that results from the model decision; explicit `llm_kwargs` credentials still win.
- [ ] AC4: `FLOW_LLM` and `FLOW_<PROVIDER>_API_KEY` apply to flow agents that are unconfigured and carry no explicit credential; Google family collapses to `GOOGLE`.
- [ ] AC5: Already-configured registry instances are not mutated by FLOW injection; the limitation is documented.
- [ ] AC6: `UsageRecord.component == "FLOW"` for calls inside `AgentsFlow.run_flow()`; metric label sets unchanged.
- [ ] AC7: Malformed `<AGENT>_MODEL` raises `ValueError` naming the variable; no key value is ever logged.
- [ ] AC8: `self._llm_kwargs` (shared with `AgentDefinition.config`) is never mutated by either path.
- [ ] AC9: Validation Contract tests pass; `ruff check` clean; wiki page updated (`parrot sdd techwiki check`).

---

## 6. Codebase Contract

> Verified against `origin/dev` @ `64dc31e39b` on 2026-11-12.

### Verified Imports
```python
from parrot.llm_defaults import (  # verified: packages/ai-parrot/src/parrot/llm_defaults.py
    ComponentLLM, resolve_component_llm, resolve_component_api_key, provider_key_token,
)
from parrot.bots.flows.crew.credentials import (  # verified: credentials.py:24,30,98,123
    GOOGLE_PROVIDER_KEYS, has_explicit_google_credential, is_google_llm, apply_google_api_key,
)
from parrot.observability.context import usage_component  # verified: observability/context.py:171
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/llm_defaults.py
def _split(value: str, *, var: str, default_provider: str) -> tuple[str, str]  # :25
def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM       # :47
def provider_key_token(provider: str) -> str                                     # :62
def resolve_component_api_key(components: Sequence[str], provider: str, *, legacy: Sequence[str] = ()) -> Optional[str]  # :71

# packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py
_CREDENTIAL_KWARGS = ("api_key", "credentials_file", "credentials")              # :27
def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool             # :123 (rebinds a NEW dict)

# packages/ai-parrot/src/parrot/bots/abstract.py
self._llm_raw = llm                                                               # :483
self._llm_model_explicit = _explicit_llm_model not in (None, "")                  # :509
self._llm_kwargs = kwargs.get("llm_kwargs", {})                                   # :547
config = self._resolve_llm_config(llm=self._llm_raw, model=model_arg, preset=self._llm_preset, **self._llm_kwargs)  # ~:1681

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
def from_definition(cls, definition, *, agent_registry=None, node_factories=None, ...)  # :550
agent = agent_registry.get_bot_instance(agent_ref)                                # :635
agent = agent_registry.get_bot_instance(ref)                                      # :661 (decision-group members)
async def run_flow(self, ctx=None, *, on_complete=())                            # :1226

# packages/ai-parrot/src/parrot/registry/registry.py
def get_bot_instance(self, name: str) -> Optional[AbstractBot]                    # :592 (cached instance, already configured)
await instance.configure()   # inside BotMetadata.get_instance when not at_startup  # :217
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_apply_agent_env_overrides` | `_resolve_llm_config` | pre-call | `abstract.py:1680` |
| `apply_component_api_key("FLOW")` | `AgentsFlow.from_definition` | per resolved agent | `flow.py:635`, `:661` |
| `usage_component("FLOW")` | `AgentsFlow.run_flow` | context manager | `flow.py:1226`; pattern `crew.py:150-157` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractBot.agent_id`~~ — no such attribute on `AbstractBot` (identity is `name`; `chatbot_id` is a uuid unless declared).
- ~~`FLOW_LLM` / `FLOW_*_API_KEY` / `component="FLOW"`~~ — not implemented today.
- ~~per-agent env lookup in `llm_defaults`~~ — only component-level resolvers exist.
- ~~client-level runtime API-key rebind~~ — `AbstractClient.api_key` is set in `__init__` (`clients/base.py:527`); there is no supported rebind method and `clients/base.py` must not change.

### Edit Sites (Blueprint Anchors)

Verified against: `64dc31e39b`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/llm_defaults.py` | MODIFY | `def provider_key_token(provider: str) -> str:` | `:62` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `model_arg = self._llm_model if self._llm_model_explicit else None` | `:1680` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `agent = agent_registry.get_bot_instance(agent_ref)` | `:635` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `agent = agent_registry.get_bot_instance(ref)` | `:661` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `async def run_flow(` | `:1226` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `def add_node(self, node: Node) -> None:` | `:407` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `import asyncio` | `:20` | 1 |
| `packages/ai-parrot/tests/bots/flows/test_flow_per_agent_env_integration.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/test_llm_defaults_documented.py` | MODIFY | `"name", ["DEFAULT_LLM", "CREW_LLM", "AGENT_LLM", "EXPERT_JUDGMENT_LLM", "CREW_GOOGLE_API_KEY", "CREW_AI_KEY"]` | `:11` | 1 |
| `wiki/operations/configuration/llm-defaults.md` | MODIFY | `## API keys` | — | 1 |
| `packages/ai-parrot/tests/unit/test_llm_defaults.py` | MODIFY | (append tests) | — | — |
| `packages/ai-parrot/tests/bots/flows/test_flow_default_key.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/test_per_agent_env_credentials.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Resolve through `navconfig.config.get(...)` exactly like `resolve_component_api_key` (`llm_defaults.py:74`); never `os.environ` directly.
- Copy `llm_kwargs`; never mutate the shared dict (`credentials.py:123` docstring, leak via `GET /api/v1/crew`).
- Async-first, `self.logger`, no `print`; Google-style docstrings; Pydantic only where already used.

### Known Risks / Gotchas
- **Env-token collisions:** `odoo-helpdesk` and `odoo_helpdesk` normalize identically. Mitigation: document; first-match semantics, no attempt to disambiguate.
- **Component-name collision:** an agent literally named `crew`, `flow` or `agent` would read `CREW_*`/`FLOW_*`/`AGENT_*` as *its own* per-agent vars. Mitigation: per-agent lookup suffix is `_MODEL` / `_<P>_API_KEY` — identical shape to component keys, so document that agents must not use reserved names, and log a WARNING at configure when `name` normalizes to `AGENT`, `CREW`, `FLOW`, `DEFAULT`, `EXPERT_*`.
- **Already-configured registry agents** miss FLOW injection (D3). Mitigated by the per-agent path; surfaced in docs and a one-time INFO log.
- **Value-equality detection (rev 0.2):** if an operator sets a component key to the same value as an
  `api_key` hard-coded for an agent, that agent's key is treated as a component default and a
  per-agent env key replaces it. Documented; the per-agent key is the operator's explicit intent anyway.
- **Name changes:** `bot.name` is mutable in a few subclasses before `configure()`; the lookup uses the name at `configure()` time.
- Interaction with FEAT-796 `AGENT_LLM` handler default (`abstract.py` handler `_create_agent`): the handler already resolves `AGENT_*` and passes `llm`/`llm_kwargs`; per-agent env then overrides *that* result (#3 > #5) by design.

### External Dependencies
None.

---

## Decisions

```yaml
schema_version: 1
document_id: per-agent-env-llm-credentials
entries:
  - id: agent-identity-is-normalized-name
    statement: Per-agent env variables are keyed by the bot name upper-cased with non-alphanumeric runs collapsed to underscores.
    relation: constrains
    about: [config]
    targets: ["sym:packages/ai-parrot/src/parrot/llm_defaults.py#provider_key_token"]
    contradicts: []
    supersedes: []
    rationale: "bot.name is stable across restarts and matches the registry key in practice; chatbot_id is a random uuid unless declared; AbstractBot has no agent_id."
    rejected_alternatives: ["registry key only (unavailable for hand-built agents)", "chatbot_id (unstable)"]
  - id: per-agent-env-beats-code-not-instances
    statement: Per-agent env model and key override code-declared llm/model but never a live client instance or an explicit credential.
    relation: constrains
    about: [bots]
    targets: ["sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure"]
    contradicts: []
    supersedes: []
    rationale: "Lets operators re-point an agent without a code or data change while keeping caller-supplied credentials authoritative."
    rejected_alternatives: ["code wins over env (env could never retarget a pinned agent)"]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:5d29cdf2be8ffeda4deeac420d97d0de452e7f00b93099817b924bfe95f07842 evaluation_digest=sha256:490c87eaa9660cc19052ea8c3beccc0374d35fa0fa3e8878ce05fedc39fcde9b rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:per-agent-env-llm-credentials#agent-identity-is-normalized-name@1; scope: sym:packages/ai-parrot/src/parrot/llm_defaults.py#provider_key_token; message: sym:packages/ai-parrot/src/parrot/llm_defaults.py#provider_key_token impacts 4 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py#AgentHandler._create_agent, sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#_build_crew_client, sym:packages/ai-parrot/src/parrot/experts/agent.py#ExpertAgent.__init__, sym:packages/ai-parrot/src/parrot/llm_defaults.py#resolve_component_api_key; inferred: sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#get_crew_google_api_key, sym:packages/ai-parrot/tests/unit/test_llm_defaults.py#test_api_key_cascade_order, sym:packages/ai-parrot/tests/unit/test_llm_defaults.py#test_provider_token_google_family
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:per-agent-env-llm-credentials#per-agent-env-beats-code-not-instances@1; scope: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure; message: sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure impacts 35 dependent(s): sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.__aenter__, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._configure_prompt_builder, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.reconfigure, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.create_system_prompt, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_configure_none_then_build_with_language_kwarg, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_prompt_byte_identical_when_unset, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_prompt_contains_directive_when_set, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_unsupported_language_is_treated_as_unset, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#_PostSuperBot.configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#_PreSuperBot.configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_is_noop_is_prospective_before_any_increment, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_is_noop_matches_configure_decision, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_false_after_first_configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_false_after_reconfigure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_false_when_app_arrives_later, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_true_on_bare_repeat_entry, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_true_on_repeat_same_app, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_post_super_work_runs_again_after_reconfigure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_post_super_work_runs_when_app_arrives_later, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_post_super_work_skipped_on_repeat_configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_noop_path_still_increments_counter, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_work_runs_again_after_reconfigure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_work_runs_when_app_arrives_later, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_work_skipped_on_repeat_configure, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_configure_twice_end_to_end, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_configure_with_new_app_reruns, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_configure_without_app_after_app_keeps_binding, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_failed_configure_still_marks_configured, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_reconfigure_reruns_pipeline, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_second_configure_is_noop, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_two_agents_parallel_configure, sym:packages/ai-parrot/tests/bots/test_tool_loop_warning.py#test_configure_calls_warning_after_client_creation, sym:packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py#tenant_bot, sym:packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py#test_configure_calls_apply_tooling_specs_once, sym:packages/ai-parrot/tests/test_jira_specialist_output_language.py#_rendered_prompt

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: agentsflow, api-keys, credentials, env-config, llm-defaults
- Targets resolved: 2/2
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 2,
    "targets_total": 2,
    "unmapped_tags": [
      "agentsflow",
      "api-keys",
      "credentials",
      "env-config",
      "llm-defaults"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:490c87eaa9660cc19052ea8c3beccc0374d35fa0fa3e8878ce05fedc39fcde9b",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:449305c7c2429b418cabc179ba9b3521ed022d9c8b7cc817cba2badd7c6217b3",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/llm_defaults.py#provider_key_token impacts 4 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py#AgentHandler._create_agent, sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#_build_crew_client, sym:packages/ai-parrot/src/parrot/experts/agent.py#ExpertAgent.__init__, sym:packages/ai-parrot/src/parrot/llm_defaults.py#resolve_component_api_key; inferred: sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#get_crew_google_api_key, sym:packages/ai-parrot/tests/unit/test_llm_defaults.py#test_api_key_cascade_order, sym:packages/ai-parrot/tests/unit/test_llm_defaults.py#test_provider_token_google_family",
      "participants": [
        {
          "decision_id": "adr:spec:per-agent-env-llm-credentials#agent-identity-is-normalized-name",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/llm_defaults.py#provider_key_token"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:ee75d56a5143943f6af2b93459c0b99db099d4ebbf7ba9ee6cae2e2697f6c9aa",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure impacts 35 dependent(s): sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.__aenter__, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._configure_prompt_builder, sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.reconfigure, sym:packages/ai-parrot/src/parrot/bots/voice.py#VoiceBot.create_system_prompt, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_configure_none_then_build_with_language_kwarg, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_prompt_byte_identical_when_unset, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_prompt_contains_directive_when_set, sym:packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py#test_unsupported_language_is_treated_as_unset, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#_PostSuperBot.configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#_PreSuperBot.configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_is_noop_is_prospective_before_any_increment, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_is_noop_matches_configure_decision, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_false_after_first_configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_false_after_reconfigure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_false_when_app_arrives_later, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_true_on_bare_repeat_entry, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_configure_skipped_true_on_repeat_same_app, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_post_super_work_runs_again_after_reconfigure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_post_super_work_runs_when_app_arrives_later, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_post_super_work_skipped_on_repeat_configure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_noop_path_still_increments_counter, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_work_runs_again_after_reconfigure, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_work_runs_when_app_arrives_later, sym:packages/ai-parrot/tests/bots/test_configure_override_guards.py#test_pre_super_work_skipped_on_repeat_configure, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_configure_twice_end_to_end, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_configure_with_new_app_reruns, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_configure_without_app_after_app_keeps_binding, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_failed_configure_still_marks_configured, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_reconfigure_reruns_pipeline, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_second_configure_is_noop, sym:packages/ai-parrot/tests/bots/test_double_configure.py#test_two_agents_parallel_configure, sym:packages/ai-parrot/tests/bots/test_tool_loop_warning.py#test_configure_calls_warning_after_client_creation, sym:packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py#tenant_bot, sym:packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py#test_configure_calls_apply_tooling_specs_once, sym:packages/ai-parrot/tests/test_jira_specialist_output_language.py#_rendered_prompt",
      "participants": [
        {
          "decision_id": "adr:spec:per-agent-env-llm-credentials#per-agent-env-beats-code-not-instances",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:5d29cdf2be8ffeda4deeac420d97d0de452e7f00b93099817b924bfe95f07842",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:0c4cdd7cbb2e0f47206bf277a2e10f159bd4baaf785864eb697c8da1f18e1c4d",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] What identifies the agent in `<AGENT_ID>_...`? — *Resolved with author*: `bot.name`, normalized to an env token (D1).
- [x] Does `<AGENT>_MODEL` beat the model declared in code/definition? — *Resolved with author*: env beats code, never a live client instance or explicit credentials (D2).
- [x] Component name for AgentsFlow defaults? — *Resolved with author*: `FLOW` (`FLOW_LLM`, `FLOW_<PROVIDER>_API_KEY`), no legacy alias.
- [x] D3 — Registry instances are already configured when `AgentsFlow` receives them, so FLOW key injection cannot reach their client. — *Resolved with author*: accept the limitation. `FLOW_<PROVIDER>_API_KEY` applies only to agents not yet configured (in practice, programmatic flows); registry-built agents use `<AGENT>_<PROVIDER>_API_KEY`. No `component` hint on `AgentRegistry.get_instance`.
- [x] Should per-agent env also apply to `AgentCrew` agents? — *Resolved with author*: yes, no opt-out. `<AGENT>_MODEL` / `<AGENT>_<PROVIDER>_API_KEY` apply to crew agents via `configure()` and beat `CREW_*` (#3 > #5); see rev 0.2 component-default detection.

---

## 9. Design Research Cross-Check

> Status: skipped (no accepted exploration document; spec seeded from a direct request and codebase research).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/operations/configuration/llm-defaults.md` — update: FLOW rows, per-agent `<AGENT>_MODEL` / `<AGENT>_<PROVIDER>_API_KEY`, precedence table, already-configured-instance limitation
- **API modules**:
  - `parrot.llm_defaults`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-12 | Jesus Lara | Initial draft |
| 0.2 | 2026-11-12 | Jesus Lara | Task-time amendment: component-default keys detected by value (`COMPONENTS`, `is_component_default_key`) so #3 beats #5 for CREW/AGENT/EXPERT/FLOW; FLOW defaults also applied in `add_node`; `FLOW_LLM` only when set; crew opt-out question closed |
