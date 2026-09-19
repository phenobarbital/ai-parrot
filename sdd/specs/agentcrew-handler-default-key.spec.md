---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: AgentCrew Handler Default Google Key (`CREW_AI_KEY`)

**Feature ID**: FEAT-575
**Date**: 2026-09-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.5

---

## 1. Motivation & Business Requirements

### Problem Statement

Crews created and executed through the AgentCrew (Crew builder) HTTP
handlers (`/api/v1/crew`, crew execution) build every agent from a
`CrewDefinition`. When an agent's LLM is a Google provider and the
definition supplies no credential, the Google client silently falls back
to the process-wide `GOOGLE_API_KEY`
(`GoogleGenAIClient.__init__`, `client.py:189`). That is the same key every
other Google consumer in the server uses (chatbots, agents, tools), so
crew-builder traffic cannot be metered, rate-limited, budgeted or rotated
separately.

The crew's own orchestration LLM has the same problem: when no `llm` is
passed, `AgentCrew.__init__` silently builds a default Google client
(`crew.py:232-234`), and that client is also billed to `GOOGLE_API_KEY`. It is
used for run_loop stop-conditions, executive summaries and the infographic
ResultAgent.

### Goals

- G1: Any agent in a handler-built crew whose LLM is a Google provider
  (`google`, `gemini-live`, `google-compat`), and which declares **no**
  credential of its own, authenticates with `CREW_AI_KEY` instead of
  `GOOGLE_API_KEY`.
- G2: The crew-level orchestration LLM that `AgentCrew` builds by default
  (Google) also uses `CREW_AI_KEY`. So do its lazy Google fallbacks in
  `run_loop` and `summary(mode="executive_summary")`.
- G3: Both crew build paths are covered: `CrewHandler._create_crew_from_definition`
  (PUT/POST) and `BotManager._create_crew_from_definition` →
  `AgentCrew.from_definition` (execution with `as_new=True`, Redis reload,
  `load_crews`).
- G4: When `CREW_AI_KEY` is unset, behavior is exactly today's: no
  injection, fall back to `GOOGLE_API_KEY`, and log **one** warning per
  process.
- G5: The key is never written into the `CrewDefinition` (and therefore
  never persisted to Redis or returned by `GET /api/v1/crew`) and never
  logged.

### Non-Goals (explicitly out of scope)

- Programmatic `AgentCrew(...)` / `AgentCrew.from_definition(...)` use
  outside the server keeps `GOOGLE_API_KEY`. The new key is **opt-in** via an
  explicit parameter, and only the server build paths pass it.
- Non-Google providers (OpenAI, Anthropic, Groq, …) are unchanged.
- Vertex AI credentials (service-account JSON, `VERTEX_*`) are unchanged.
  An agent that declares `vertexai`/`credentials_file` counts as "credential
  provided" and is left alone.
- `AgentsFlow` (`parrot/bots/flows/flow/`), the flow-authoring assembler and
  the dev-loop flows are out of scope.
- Refactoring `CrewHandler._create_crew_from_definition` to delegate to
  `AgentCrew.from_definition` is out of scope. The handler gets the same
  wiring in place.

---

## 2. Architectural Design

### Overview

1. **Config**: add `CREW_AI_KEY = config.get("CREW_AI_KEY")` to core
   `parrot/conf.py`, next to `GOOGLE_API_KEY`.
2. **Credential helper** (new core module
   `parrot/bots/flows/crew/credentials.py`):
   - `GOOGLE_PROVIDER_KEYS = frozenset({"google", "gemini-live", "google-compat"})`,
     which are the three `parrot.clients` entry points of `ai-parrot-client-google`.
   - `get_crew_google_api_key()` reads `parrot.conf.CREW_AI_KEY`. When it is
     unset it returns `None` and logs a one-time warning:
     `"CREW_AI_KEY is not set; crew Google agents fall back to GOOGLE_API_KEY"`.
   - `is_google_llm(llm, default_provider)` classifies an agent's raw LLM
     declaration. A string is parsed as `provider[:model]` and matched against the
     keys (case-insensitive). An `AbstractClient` subclass matches when it is a
     subclass of any class those keys resolve to in `SUPPORTED_CLIENTS`
     (resolved lazily, and `False` when the Google satellite is not installed).
     An `AbstractClient` **instance**, or any other callable, is never Google
     here, because a live instance carries its own credentials. `None` means
     `default_provider` decides (AbstractBot's `_default_llm`, which is `"google"`).
   - `apply_google_api_key(agent, api_key) -> bool` works on an **already
     constructed, not yet configured** agent. It reads `agent._llm_raw`, which
     already reflects a class-level `llm = "google:..."` declaration
     (`abstract.py:447-452`), and `agent._llm_kwargs`. When the LLM is Google and
     `_llm_kwargs` holds none of `api_key`, `credentials_file`, `credentials`,
     or a truthy `vertexai`, it **rebinds** `agent._llm_kwargs` to a new dict
     with `api_key` added. It never mutates the dict in place, because that dict
     is the same object as `agent_def.config["llm_kwargs"]`. Returns whether it
     injected. A falsy `api_key` is a no-op that returns `False`.
3. **Why the key reaches the client**: `AbstractBot.configure()` calls
   `_resolve_llm_config(..., **self._llm_kwargs)` (`abstract.py:1537-1539`).
   Unknown kwargs land in `LLMConfig.extra` (`_apply_llm_params`, `abstract.py:998`),
   and `_create_llm_client` passes them into the client constructor as
   `**config.extra` (`abstract.py:1025-1033`). `GoogleGenAIClient` takes
   `api_key` from kwargs before it falls back to `GOOGLE_API_KEY`
   (`client.py:189`). `GeminiLiveClient` (`live.py:435`) and
   `GeminiOpenAICompatClient` (`openai_compat.py:30`) do the same. No client
   code changes.
4. **AgentCrew wiring** (core `crew.py`):
   - `AgentCrew.__init__` gains `google_api_key: Optional[str] = None`, stored
     as `self._google_api_key`. When the crew builds its **default** Google
     orchestration client (no `llm`, or `llm` is a string in
     `GOOGLE_PROVIDER_KEYS`) and `google_api_key` is set, it passes
     `api_key=google_api_key` unless `kwargs` already has `api_key`. The lazy
     fallbacks in `run_loop` (`crew.py:2125-2132`) and the executive summary
     (`crew.py:4379-4383`) pass `api_key=self._google_api_key` when set.
   - `AgentCrew.from_definition` gains a keyword-only
     `google_api_key: Optional[str] = None`. For every constructed agent it
     calls `apply_google_api_key(agent, google_api_key)` right after
     `_apply_definition_prompt`, then forwards `google_api_key` to `cls(...)`.
     With the default `None`, the method behaves exactly as today.
5. **Server wiring**:
   - `BotManager._create_crew_from_definition` (`manager.py:3081`) passes
     `google_api_key=get_crew_google_api_key()` to `AgentCrew.from_definition`.
   - `CrewHandler._create_crew_from_definition` (`handler.py:90`) resolves the
     key once per call. It calls `apply_google_api_key(agent, key)` after each
     `agent_class(...)` (`handler.py:129`) and system-prompt assignment, and
     passes `google_api_key=key` to `AgentCrew(...)` (`handler.py:142`).

### Component Diagram

```
CREW_AI_KEY (env/navconfig)
      │
parrot.conf.CREW_AI_KEY ──→ credentials.get_crew_google_api_key()  (warn-once if unset)
                                   │
        ┌──────────────────────────┴──────────────────────────┐
BotManager._create_crew_from_definition        CrewHandler._create_crew_from_definition
        │ google_api_key=                              │ apply_google_api_key(agent) per agent
        ▼                                              │ AgentCrew(..., google_api_key=)
AgentCrew.from_definition(google_api_key=)             │
        │ apply_google_api_key(agent) per agent        │
        ▼                                              ▼
AgentCrew.__init__(google_api_key=) ──→ default Google orchestration client(api_key=)
        │
agent._llm_kwargs["api_key"] ──→ AbstractBot.configure() ──→ LLMConfig.extra
        ──→ GoogleGenAIClient / GeminiLiveClient / GeminiOpenAICompatClient(api_key=)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/conf.py` | modifies | adds `CREW_AI_KEY` |
| `AbstractBot` (`_llm_raw`, `_llm_kwargs`, `_default_llm`) | reads / rebinds | `_llm_kwargs` is rebound, never mutated in place. `abstract.py` is **not** modified |
| `AgentCrew.__init__` / `from_definition` / `run_loop` / `summary` | modifies | opt-in `google_api_key` |
| `BotManager._create_crew_from_definition` | modifies | passes the key |
| `CrewHandler._create_crew_from_definition` | modifies | applies helper + passes key |
| Google clients (`client.py`, `live.py`, `openai_compat.py`) | uses | already accept `api_key=`, so unchanged |

### Data Models

No new Pydantic models. `CrewDefinition` / `AgentDefinition` are **unchanged**,
and the key is never stored in them.

### New Public Interfaces

```python
# parrot/bots/flows/crew/credentials.py
GOOGLE_PROVIDER_KEYS: frozenset[str]
def get_crew_google_api_key() -> Optional[str]: ...
def is_google_llm(llm: Any, default_provider: Optional[str] = "google") -> bool: ...
def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool: ...

# AgentCrew
AgentCrew.__init__(..., google_api_key: Optional[str] = None, **kwargs)
AgentCrew.from_definition(crew_def, *, class_resolver, tool_resolver=None,
                          google_api_key: Optional[str] = None, **kwargs)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: config + credential helper | yes | signatures below; rebind-not-mutate; warn-once flag; lazy `SUPPORTED_CLIENTS` | — |
| M2: AgentCrew wiring | yes | `google_api_key` kwarg on `__init__`/`from_definition`; 3 default-client sites fixed | — |
| M3: server wiring | yes | 2 call sites, exact lines below | — |
| M4: docs | yes | sections named below | — |

### Module 1: Config key + crew credential helper
- **Path**: `packages/ai-parrot/src/parrot/conf.py` (modify), `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` (new)
- **Responsibility**: define `CREW_AI_KEY`; classify an agent's LLM as Google; inject the key into an agent's LLM kwargs without mutating the definition.
- **Depends on**: existing `AbstractBot`, `parrot.clients.factory.SUPPORTED_CLIENTS`, `_resolve_supported_client`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/conf.py  (modifies conf.py:379 — "## Google Services:" block)
  CREW_AI_KEY = config.get("CREW_AI_KEY")  # next to GOOGLE_API_KEY (verified: conf.py:379)

  # packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py  (new)
  """Default Google credential for handler-built AgentCrews (CREW_AI_KEY)."""
  GOOGLE_PROVIDER_KEYS: frozenset[str] = frozenset({"google", "gemini-live", "google-compat"})
  # keys verified: packages/ai-parrot-client-google/pyproject.toml:36-38
  _CREDENTIAL_KWARGS: tuple[str, ...] = ("api_key", "credentials_file", "credentials")

  def get_crew_google_api_key() -> Optional[str]:
      """Return ``parrot.conf.CREW_AI_KEY`` or ``None``.

      Logs a single warning per process (module-level flag) when the key is
      unset. Never logs the key value.
      """

  def is_google_llm(llm: Any, default_provider: Optional[str] = "google") -> bool:
      """True when ``llm`` (an agent's raw LLM declaration) resolves to a Google provider.

      str → provider part of ``provider[:model]`` (lower-cased) in GOOGLE_PROVIDER_KEYS;
      AbstractClient subclass → issubclass of any class those keys resolve to via
      SUPPORTED_CLIENTS (verified: parrot/clients/factory.py) + _resolve_supported_client
      (verified: parrot/bots/abstract.py:178); satellite missing / lookup error → False;
      AbstractClient instance or other callable → False;
      None → ``default_provider`` in GOOGLE_PROVIDER_KEYS.
      """

  def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool:
      """Inject ``api_key`` into a constructed, unconfigured agent's LLM kwargs.

      No-op (returns False) when ``api_key`` is falsy, the agent is not Google
      (``is_google_llm(agent._llm_raw, getattr(agent, "_default_llm", "google"))``),
      or ``agent._llm_kwargs`` already holds any _CREDENTIAL_KWARGS key or a truthy
      ``vertexai``. Otherwise REBINDS ``agent._llm_kwargs = {**agent._llm_kwargs,
      "api_key": api_key}`` (never mutates in place — the dict is shared with
      ``AgentDefinition.config["llm_kwargs"]``) and returns True.
      Agents without ``_llm_raw``/``_llm_kwargs`` (not AbstractBot) → False.
      """
  ```

### Module 2: AgentCrew wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (modify)
- **Responsibility**: opt-in `google_api_key` on the crew. Applies it to definition-built agents and to every default Google client the crew builds.
- **Depends on**: Module 1 (`apply_google_api_key`, `GOOGLE_PROVIDER_KEYS`).
- **Interface Skeleton**:
  ```python
  # modifies crew.py:156 (__init__)
  def __init__(self, name: str = "AgentCrew", ..., llm: Optional[Union[str, AbstractClient]] = None,
               ..., infographic_theme: Optional[str] = None,
               google_api_key: Optional[str] = None,   # NEW — before **kwargs
               **kwargs):
      """... google_api_key: Gemini API key for every Google client this crew
      builds by default (orchestration LLM, run_loop / executive-summary
      fallbacks). None → provider default (GOOGLE_API_KEY)."""
      # crew.py:227-234: when the resolved default client is Google (llm None or llm str in
      # GOOGLE_PROVIDER_KEYS) and google_api_key and "api_key" not in kwargs →
      # client_cls(api_key=google_api_key, **kwargs). Stored as self._google_api_key.
      # crew.py:2132  GoogleGenAIClient(model="gemini-2.5-pro", max_tokens=8192[, api_key=self._google_api_key])
      # crew.py:4383  _resolve_supported_client(SUPPORTED_CLIENTS["google"])([api_key=self._google_api_key])

  # modifies crew.py:767 (from_definition)
  @classmethod
  def from_definition(cls, crew_def: "CrewDefinition", *,
                      class_resolver: Callable[[str], Optional[type]],
                      tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]] = None,
                      google_api_key: Optional[str] = None,   # NEW
                      **kwargs) -> "AgentCrew":
      """... google_api_key: when set, every Google agent without its own credential
      gets it (apply_google_api_key, after _apply_definition_prompt at crew.py:801)
      and it is forwarded to AgentCrew.__init__."""
  ```

### Module 3: Server wiring
- **Path**: `packages/ai-parrot-server/src/parrot/manager/manager.py`, `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` (modify)
- **Responsibility**: both server crew build paths pass `CREW_AI_KEY`.
- **Depends on**: Module 1, Module 2 (the `google_api_key` parameters).
- **Interface Skeleton**:
  ```python
  # manager.py:3081 — BotManager._create_crew_from_definition (signature unchanged)
  from ..bots.flows.crew.credentials import get_crew_google_api_key
  return AgentCrew.from_definition(
      crew_def,
      class_resolver=self.get_bot_class,
      google_api_key=get_crew_google_api_key(),   # NEW
  )

  # handler.py:90 — CrewHandler._create_crew_from_definition (signature unchanged)
  from parrot.bots.flows.crew.credentials import apply_google_api_key, get_crew_google_api_key
  google_key = get_crew_google_api_key()            # once per call
  # after agent_class(...) (handler.py:129) and system_prompt assignment:
  apply_google_api_key(agent, google_key)
  # handler.py:142
  crew = AgentCrew(name=..., agents=agents, max_parallel_tasks=..., google_api_key=google_key)
  ```

### Module 4: Documentation
- **Path**: `docs/crew_handler.md` (modify), `.env` sample if one lists `GOOGLE_API_KEY` (unverified — check before use)
- **Responsibility**: document `CREW_AI_KEY`: what it covers (declared Google agents without credentials plus the crew orchestration LLM), the fallback when unset, and the fact that an explicit `llm_kwargs.api_key` always wins.
- **Depends on**: Modules 1–3 (behavior being documented).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_is_google_llm_strings` | M1 | `"google"`, `"google:gemini-3.5-flash"`, `"GOOGLE"`, `"gemini-live"`, `"google-compat:x"` → True; `"openai:gpt-5"`, `"anthropic"` → False |
| `test_is_google_llm_none_uses_default_provider` | M1 | `None` + `"google"` → True; `None` + `"openai"` → False |
| `test_is_google_llm_instance_is_false` | M1 | a client **instance** → False |
| `test_is_google_llm_class` | M1 | `GoogleGenAIClient` class → True (skip if satellite absent); a non-Google client class → False |
| `test_apply_injects_for_google_without_credential` | M1 | agent `llm="google:..."`, no llm_kwargs → returns True, `agent._llm_kwargs["api_key"] == key` |
| `test_apply_does_not_mutate_definition_dict` | M1 | the `llm_kwargs` dict passed into the agent (the `AgentDefinition.config` one) has no `api_key` afterwards |
| `test_apply_respects_explicit_credential` | M1 | `llm_kwargs={"api_key": "own"}` / `{"credentials_file": ...}` / `{"vertexai": True}` → False, unchanged |
| `test_apply_skips_non_google_and_falsy_key` | M1 | `llm="openai:..."` → False; `api_key=None` → False |
| `test_apply_class_level_llm_declaration` | M1 | agent subclass with class attr `llm = "google:gemini-3.5-flash"` and no ctor `llm` → injected |
| `test_get_key_warns_once_when_unset` | M1 | monkeypatched unset key → returns None; warning logged exactly once over 2 calls; key value never in log records |
| `test_from_definition_injects_google_agents` | M2 | mixed google/openai definition + `google_api_key="k"` → only the Google agent gets `api_key`; `crew_def` model_dump has no `"k"` |
| `test_from_definition_default_none_unchanged` | M2 | no `google_api_key` → no agent `_llm_kwargs` gains `api_key` (regression) |
| `test_crew_default_llm_gets_key` | M2 | `AgentCrew(google_api_key="k")` with the Google client class patched → called with `api_key="k"`; explicit `llm=<instance>` untouched |
| `test_run_loop_and_summary_fallback_use_key` | M2 | `_llm=None` fallbacks construct the Google client with `api_key=self._google_api_key` |
| `test_manager_create_crew_passes_crew_key` | M3 | patched `CREW_AI_KEY` → `from_definition` receives it |
| `test_handler_create_crew_applies_crew_key` | M3 | handler build: Google agent injected, non-Google untouched, `AgentCrew` got `google_api_key` |

### Integration Tests
| Test | Description |
|---|---|
| `test_handler_built_google_agent_client_uses_crew_key` | Build a crew through `CrewHandler._create_crew_from_definition` with a Google agent, `configure()` the agent with the Google SDK client factory mocked, and assert the constructed `GoogleGenAIClient.api_key == CREW_AI_KEY`, not `GOOGLE_API_KEY` |

### Test Data / Fixtures
```python
@pytest.fixture
def crew_key(monkeypatch):
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "crew-test-key", raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    return "crew-test-key"
```
Tests live next to their distribution: core M1/M2 under
`packages/ai-parrot/tests/bots/flows/` (see `test_from_definition.py`),
server M3 under `packages/ai-parrot-server/tests/handlers/` /
`packages/ai-parrot-server/tests/manager/`.

---

## 5. Acceptance Criteria

- [ ] AC1: With `CREW_AI_KEY` set, an agent in a handler-built crew whose LLM is `google`, `gemini-live` or `google-compat` (via `config.llm`, a class-level `llm`, or the `_default_llm` default) and that has no `llm_kwargs` credential is constructed with `api_key == CREW_AI_KEY`.
- [ ] AC2: An agent with an explicit `llm_kwargs.api_key`, `credentials_file`, `credentials` or truthy `vertexai`, or with an `AbstractClient` instance as `llm`, is unchanged.
- [ ] AC3: Non-Google agents are unchanged.
- [ ] AC4: The crew's default Google orchestration client and its `run_loop` / executive-summary fallbacks use `CREW_AI_KEY` when the crew was built by the server.
- [ ] AC5: Both server build paths (`CrewHandler._create_crew_from_definition`, `BotManager._create_crew_from_definition`) apply the key.
- [ ] AC6: With `CREW_AI_KEY` unset, behavior is identical to today (clients use `GOOGLE_API_KEY`), and exactly one warning is logged per process.
- [ ] AC7: `CREW_AI_KEY` never appears in `CrewDefinition` (and so never in Redis / `GET /api/v1/crew`), and never in log output.
- [ ] AC8: `AgentCrew(...)` and `AgentCrew.from_definition(...)` called without `google_api_key` behave exactly as before (no public API break).
- [ ] AC9: `pytest packages/ai-parrot/tests/bots/flows/ -v` and the new server tests pass; `ruff check` is clean on the touched files.
- [ ] AC10: `docs/crew_handler.md` documents `CREW_AI_KEY`.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.bots.flows.crew import AgentCrew                  # verified: handlers/crew/handler.py:20
from parrot.bots.abstract import AbstractBot, _resolve_supported_client  # verified: bots/flows/crew/crew.py:57 (relative), abstract.py:178
from parrot.clients import AbstractClient                      # verified: crew.py:58 (relative)
from parrot.clients.factory import SUPPORTED_CLIENTS           # verified: crew.py:59 (relative)
from navconfig import config                                   # parrot/conf.py uses config.get(...) (conf.py:379)
from navconfig.logging import logging                          # verified: crew.py:53
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/conf.py
GOOGLE_API_KEY = config.get("GOOGLE_API_KEY")        # line 379 (and duplicated at line 424)

# packages/ai-parrot/src/parrot/bots/abstract.py
def _resolve_supported_client(entry): ...           # line 178
class AbstractBot:
    _default_llm: str = "google"                     # line 220
    # __init__: class-level ``llm`` honored when no llm arg     # lines 447-451
    self._llm_raw = llm                              # line 452
    self._llm_kwargs = kwargs.get("llm_kwargs", {})  # line 516 — SAME object as caller's dict
    def _parse_llm_string(self, llm: str) -> Tuple[str, Optional[str]]:   # line 807
    def _resolve_llm_config(self, llm=None, model=None, preset=None, model_config=None, **kwargs) -> LLMConfig:  # line 811
    def _apply_llm_params(self, config, preset=None, **kwargs) -> LLMConfig:  # line ~974; config.extra.update(kwargs) ~998
    def _create_llm_client(self, config: LLMConfig) -> AbstractClient:        # line 1002; **config.extra at ~1033
    # configure(): _resolve_llm_config(llm=self._llm_raw, ..., **self._llm_kwargs)  # lines 1537-1539

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew:
    def __init__(self, name="AgentCrew", agents=None, shared_tool_manager=None,
                 max_parallel_tasks=10, llm=None, auto_configure=True, ...,
                 tenant=None, generate_infographic=False, result_agent_name="result-agent",
                 infographic_theme=None, **kwargs):             # lines 156-181
        # llm resolution: str → client_cls(**kwargs); instance → as-is;
        # else default SUPPORTED_CLIENTS["google"] → client_cls(**kwargs)   # lines 227-234
    @classmethod
    def _apply_definition_prompt(cls, agent, system_prompt) -> None:       # line 657
    @classmethod
    def from_definition(cls, crew_def, *, class_resolver, tool_resolver=None, **kwargs) -> "AgentCrew":  # line 767
        # agent_class(name=..., tools=list(agent_def.tools), **agent_def.config)  # ~796-800
        # cls._apply_definition_prompt(agent, agent_def.system_prompt)           # line 801
    # run_loop fallback: GoogleGenAIClient(model="gemini-2.5-pro", max_tokens=8192)  # lines 2125-2132
    # summary executive fallback: _resolve_supported_client(SUPPORTED_CLIENTS["google"])()  # lines 4379-4383
    # infographic: agent_cls(name=self.result_agent_name, llm=self._llm)      # line 609 (instance → covered by crew llm)

# packages/ai-parrot/src/parrot/models/crew_definition.py
class AgentDefinition(BaseModel):                    # line 31, extra="forbid"
    config: Dict[str, Any]                           # forwarded as **kwargs to the agent ctor
class CrewDefinition(BaseModel):                     # line 178

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient):             # line 101
    client_name: str = "google"                      # line 117
    self.api_key = kwargs.pop("api_key", config.get("GOOGLE_API_KEY"))   # line 189
# .../google/live.py
class GeminiLiveClient(AbstractClient):              # line 328; client_name "google_live" (line 373)
    self.api_key = api_key or config.get("GOOGLE_API_KEY")               # line 435
# .../google/openai_compat.py
class GeminiOpenAICompatClient(OpenAIBaseClient):    # line 17
    resolved_key = api_key or config.get("GEMINI_API_KEY") or config.get("GOOGLE_API_KEY")  # line 30
# packages/ai-parrot-client-google/pyproject.toml  [project.entry-points."parrot.clients"]  lines 36-38
#   google, gemini-live, google-compat

# packages/ai-parrot-server/src/parrot/handlers/crew/handler.py
class CrewHandler(BaseView):
    async def _create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew:  # line 90
        # agent = agent_class(name=..., tools=tools, **agent_def.config)   # line 129
        # crew = AgentCrew(name=..., agents=agents, max_parallel_tasks=...) # line 142
    # callers: PUT upload line 265, create/update line 388

# packages/ai-parrot-server/src/parrot/manager/manager.py
from ..bots.flows.crew import AgentCrew              # line 82
class BotManager:
    async def get_crew(self, identifier, as_new=False, tenant=None)       # line 2818
    async def load_crews(self) -> None                                     # line 2981
    async def _create_crew_from_definition(self, crew_def) -> AgentCrew:  # line 3081 → from_definition(crew_def, class_resolver=self.get_bot_class)
# packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py
#   execution loads the crew via bot_manager.get_crew(crew_id, as_new=True, tenant=tenant)  # lines 683-687
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `apply_google_api_key` | `AbstractBot._llm_raw` / `_llm_kwargs` / `_default_llm` | attribute read + rebind | `abstract.py:452`, `:516`, `:220` |
| injected `api_key` | Google client ctor | `LLMConfig.extra` → `**config.extra` | `abstract.py:1537-1539`, `:1025-1033`; `client.py:189` |
| `from_definition(google_api_key=)` | `AgentCrew.__init__(google_api_key=)` | kwarg | `crew.py:767`, `:156` |
| `BotManager._create_crew_from_definition` | `from_definition` | kwarg | `manager.py:3096` |
| `CrewHandler._create_crew_from_definition` | `apply_google_api_key`, `AgentCrew(...)` | call + kwarg | `handler.py:129`, `:142` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.conf.CREW_AI_KEY`~~: does not exist yet (M1 adds it). There is no `CREW_AI_KEY` anywhere in the repo today.
- ~~`packages/ai-parrot-server/src/parrot/conf.py`~~: the server has no own `conf.py`. `manager.py:93` `from ..conf import ...` resolves to **core** `parrot/conf.py`.
- ~~`packages/ai-parrot/src/parrot/clients/google/`~~ source: the Google clients live in the **`ai-parrot-client-google`** satellite (`packages/ai-parrot-client-google/src/parrot/clients/google/`). Core holds only stale `__pycache__`.
- ~~`AgentDefinition.credentials` / `AgentDefinition.api_key`~~: not fields, and `extra="forbid"`. Do not add them.
- ~~`AbstractBot.set_api_key()`~~ / any public credential setter on AbstractBot does not exist, and this spec does not add one.
- ~~`GeminiLiveClient.client_name == "gemini-live"`~~: its class attr is `"google_live"`. Match classes via `SUPPORTED_CLIENTS` keys, never via `client_name`.
- A top-level `api_key` in `AgentDefinition.config` is **not** forwarded to the client by `AbstractBot`. Only `llm_kwargs.api_key` counts as "credential provided".

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Opt-in parameter with a `None` default. It mirrors how `from_definition` already threads `tenant` / `generate_infographic` through to `__init__` (`crew.py:804-842`).
- Lazy provider lookup: never import `parrot.clients.google` at module scope in core (FEAT-523 rule, see `crew.py:2127-2130`). Resolve Google classes through `SUPPORTED_CLIENTS` inside `is_google_llm`.
- `self.logger` / `logging.getLogger(__name__)`. Never `print`. Never log the key value.
- Google-style docstrings and strict type hints.

### Known Risks / Gotchas
- **Secret leak into Redis**: `AbstractBot` stores `kwargs.get("llm_kwargs", {})` **by reference** (`abstract.py:516`), and that dict is `AgentDefinition.config["llm_kwargs"]`. Mutating it in place would write `CREW_AI_KEY` into the definition, which gets persisted to Redis and returned by `GET /api/v1/crew`. Mitigation: always rebind `agent._llm_kwargs` to a new dict. Covered by `test_apply_does_not_mutate_definition_dict` and AC7.
- **Timing**: the helper must run after construction and before `configure()`. Crew agents are configured lazily when the crew runs. An agent class that builds its client inside `__init__`, or overrides `configure()` to ignore `_llm_kwargs`, will not pick the key up. Document this; no fix in scope.
- **Private attribute coupling**: the helper reads `_llm_raw` / `_llm_kwargs` / `_default_llm`. Keep that coupling in the one helper module and use `getattr` with defaults, so non-`AbstractBot` agents are a clean no-op.
- **Satellite not installed**: `SUPPORTED_CLIENTS` has no Google keys, so class-based detection returns False. String detection still works, but those agents would fail at configure anyway.
- **Crew `**kwargs` already flows into the default client** (`crew.py:229/234`). Do not also add `api_key` when the caller already passed one in `kwargs`.
- Vertex AI agents (`vertexai=True`) ignore `api_key`. They are treated as "credential provided" so nothing is injected.

### External Dependencies
None. `navconfig` is already a dependency.

---

## Worktree Strategy

- **Isolation**: one feature worktree for the spec (`feat-FEAT-575-agentcrew-handler-default-key`). The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (`crew.py` imports `apply_google_api_key` / `GOOGLE_PROVIDER_KEYS` from `credentials.py`).
  - M3 → M1 (imports `get_crew_google_api_key`, `apply_google_api_key`).
  - M3 → M2 (passes the new `google_api_key` kwarg to `from_definition` / `AgentCrew`).
  - M4 → M1–M3 (documents the final behavior). It could be drafted concurrently, but has no code edge.
- **Shared files**: none. M1 owns `conf.py` + `credentials.py`, M2 owns `crew.py`, M3 owns `manager.py` + `handler.py`, M4 owns `docs/crew_handler.md`.
- **Exclusive resources**: none (no migrations, lockfile or extension rebuilds).
- **Cross-feature dependencies**: none. The FEAT-524 memory-less-clients work is already on `dev`.

---

## 8. Open Questions

- [x] Should the crew-level orchestration Google client also use `CREW_AI_KEY`? *Resolved by user (2026-09-18)*: **Yes.** The crew's default Google LLM and its run_loop / executive-summary fallbacks use it too (G2, AC4).
- [x] What happens when `CREW_AI_KEY` is unset? *Resolved by user (2026-09-18)*: **Fall back to `GOOGLE_API_KEY`** (no injection), with a single warning per process (G4, AC6).
- [x] Which provider keys count as "Google"? *Resolved by user (2026-09-18)*: **`google`, `gemini-live`, `google-compat`**. Vertex AI (`vertexai` / `credentials_file`) counts as "credential provided" (AC1, AC2).
- [ ] Should `AgentsFlow` / flow-authoring-built crews also adopt `CREW_AI_KEY` in a follow-up? *Owner: Jesus Lara* (not blocking; out of scope here)

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (no accepted exploration document: spec created directly from inline notes, no brainstorm/proposal)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-18 | Jesus Lara | Initial draft |
