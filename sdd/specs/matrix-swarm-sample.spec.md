---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Matrix Swarm Sample — Multi-Provider Agent Swarm Demo

**Feature ID**: FEAT-464
**Date**: 2026-08-26
**Author**: Jesus Lara / AI-Parrot Team
**Status**: draft
**Target version**: 0.28.0 (next minor — ships with FEAT-463)
**Proposal**: `sdd/proposals/matrix-swarm-sample.proposal.md`
**Depends on**: FEAT-463 (`matrix-agents-swarm`) — core swarm modules must be implemented first

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-463 (matrix-agents-swarm) delivers the core swarm infrastructure: declared
channels with answer policies, private agent-to-agent tunnels, concurrent
collaborative sessions, a full docker-compose dev stack, and bootstrap script.
However, the existing example (`examples/matrix_crew/swarm_example.py`) **cannot
run end-to-end** — its `_setup_bots()` function only logs a warning instead of
creating real Agent instances:

```python
# examples/matrix_crew/swarm_example.py:142
logger.warning(
    "No real agents configured — edit _setup_bots() to register your agents."
)
```

A user who `git clone`s AI-Parrot and wants to see a swarm in action has no
runnable path from checkout to working demo.

### Goals

- **Zero-to-swarm in under 10 minutes**: a standalone sample directory with
  step-by-step README that goes from `git clone` to 4 agents talking on Matrix.
- **Multi-provider showcase**: each agent uses a different LLM provider (OpenAI,
  Anthropic, Google Gemini, Nvidia NIM) to demonstrate AI-Parrot's vendor-agnostic
  `AbstractClient` architecture.
- **Self-contained**: all files needed live in `examples/matrix_swarm/` — no
  need to cross-reference other example directories.
- **Reusable infrastructure**: leverages the existing docker-compose dev stack
  and bootstrap script from FEAT-463 (no duplication).

### Non-Goals (explicitly out of scope)

- Core swarm Python modules — those are FEAT-463's scope.
- Modifications to `docker-compose.matrix.yml` or `scripts/matrix/bootstrap.sh`.
- Bridge configuration (FEAT-463 TASK-2486).
- Updates to `examples/matrix_crew/MATRIX_CREW_GUIDE.md` (FEAT-463 TASK-2487).
- Production deployment guidance — this is a dev/demo sample.
- The option to extend `examples/matrix_crew/` was rejected in the proposal —
  a standalone directory provides cleaner onboarding.

---

## 2. Architectural Design

### Overview

The sample creates a standalone `examples/matrix_swarm/` directory containing:

1. **`agents.yaml`** — defines 4 agents with different LLM providers, system
   prompts, skills, and tool attachments.
2. **`swarm_config.yaml`** — Matrix crew configuration (channels, tunnels,
   collaborative mode) adapted from `swarm_crew.yaml` to be self-contained.
3. **`swarm_demo.py`** — runnable Python script that instantiates real Agent
   instances from the YAML, registers them in BotManager, starts
   MatrixCrewTransport, and runs until interrupted.
4. **`README.md`** — step-by-step quickstart guide.
5. **`Makefile`** — convenience targets for the full lifecycle.
6. **`.env.example`** — all required environment variables with descriptions.

### Component Diagram

```
examples/matrix_swarm/
├── README.md               ← Step-by-step quickstart
├── Makefile                ← setup / start / stop / logs / demo / clean
├── .env.example            ← Template: API keys + Matrix tokens
├── agents.yaml             ← 4 agent definitions (multi-provider)
├── swarm_config.yaml       ← MatrixCrewConfig (channels, tunnels, collaborative)
└── swarm_demo.py           ← Runnable demo script

External dependencies (not in this directory):
├── docker-compose.matrix.yml     ← FEAT-463: Synapse + Postgres + Element + bridges
├── scripts/matrix/bootstrap.sh   ← FEAT-463: 6-step automated setup
└── docker/matrix/                ← FEAT-463: configs, templates, .env
```

### Agent Allocation (Multi-Provider)

| Agent | chatbot_id | Provider Key | Model | System Prompt Focus | Tools |
|-------|-----------|-------------|-------|-------------------|-------|
| Researcher | `web-researcher` | `openai` | `gpt-4o` | Web research, document analysis | `web_search`, `url_reader` |
| Analyst | `financial-analyst` | `anthropic` | `claude-sonnet-4-20250514` | Financial analysis, SQL queries | `sql_query`, `calculator` |
| Writer | `report-writer` | `google` | `gemini-2.5-flash` | Report writing, editing, formatting | *(no external tools — pure LLM)* |
| Summarizer | `synthesis-agent` | `nvidia` | `meta/llama-3.3-70b-instruct` | Synthesis, scoring, final answers | *(no external tools — pure LLM)* |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LLMFactory.create()` | uses | `"provider:model"` strings for each agent |
| `BasicAgent.__init__()` | instantiates | 4 agents with `chatbot_id`, `llm`, `system_prompt`, `tools` |
| `BotManager.add_agent()` | calls | Registers agents so `MatrixCrewTransport.start()` can resolve them via `BotManager.get_bot(chatbot_id)` |
| `MatrixCrewTransport.from_yaml()` | calls | Loads `swarm_config.yaml` |
| `MatrixCrewTransport.__aenter__()` | calls | Starts the crew (AppService, channels, tunnels, toolkit attachment) |
| `docker-compose.matrix.yml` | references | The Makefile targets `start`/`stop` invoke compose commands |
| `scripts/matrix/bootstrap.sh` | references | The Makefile `setup` target calls the bootstrap script |

### Data Models

No new Pydantic models required. The sample uses existing models:

```python
# Agent definition in agents.yaml — loaded as dicts, passed to BasicAgent()
agent_def = {
    "name": "Researcher",
    "chatbot_id": "web-researcher",
    "llm": "openai:gpt-4o",
    "system_prompt": "You are a web research specialist...",
    "tools": ["web_search", "url_reader"],
}
```

### New Public Interfaces

None — this is a sample/example, not a library component.

---

## 3. Module Breakdown

### Module 1: Agent Definitions (`agents.yaml`)

- **Path**: `examples/matrix_swarm/agents.yaml`
- **Responsibility**: Declarative definitions for 4 agents with different LLM
  providers, system prompts, skills, and optional tool lists.
- **Depends on**: nothing (pure data)
- **Format**:
  ```yaml
  agents:
    web-researcher:
      name: "Researcher"
      llm: "openai:gpt-4o"
      system_prompt: |
        You are a web research specialist. Your role is to find,
        analyze, and summarize information from the web...
      tools:
        - web_search
        - url_reader

    financial-analyst:
      name: "Financial Analyst"
      llm: "anthropic:claude-sonnet-4-20250514"
      system_prompt: |
        You are a financial analyst. Your role is to analyze
        financial data, run SQL queries, and produce insights...
      tools:
        - sql_query
        - calculator

    report-writer:
      name: "Report Writer"
      llm: "google:gemini-2.5-flash"
      system_prompt: |
        You are a report writer. Your role is to compose clear,
        well-structured reports from research findings...

    synthesis-agent:
      name: "Synthesizer"
      llm: "nvidia:meta/llama-3.3-70b-instruct"
      system_prompt: |
        You are a synthesis specialist. Your role is to combine
        multiple agent findings into a coherent final answer...
  ```

### Module 2: Swarm Configuration (`swarm_config.yaml`)

- **Path**: `examples/matrix_swarm/swarm_config.yaml`
- **Responsibility**: MatrixCrewConfig for the swarm — homeserver, agents,
  channels, tunnels, collaborative mode. Adapted from
  `examples/matrix_crew/swarm_crew.yaml` but self-contained with comments.
- **Depends on**: Module 1 (chatbot_ids must match)
- **Key differences from `swarm_crew.yaml`**:
  - Extensive inline comments for onboarding
  - References to README sections for each block
  - Same structure and values (drop-in compatible)

### Module 3: Demo Script (`swarm_demo.py`)

- **Path**: `examples/matrix_swarm/swarm_demo.py`
- **Responsibility**: Runnable Python script that:
  1. Loads `.env` (via `python-dotenv` or manual `os.environ`)
  2. Reads `agents.yaml` and instantiates `BasicAgent` for each entry
  3. Creates LLM clients via `LLMFactory.create(agent_def["llm"])`
  4. Registers agents in `BotManager` via `manager.add_agent(agent)`
  5. Loads `MatrixCrewTransport.from_yaml("swarm_config.yaml")`
  6. Runs `async with transport:` until SIGINT/SIGTERM
- **Depends on**: Module 1, Module 2, FEAT-463 core modules
- **Pattern**: follows `examples/matrix_crew/swarm_example.py` structure
  (argparse CLI, asyncio.run, signal handlers) but with REAL agent setup

### Module 4: README & Makefile

- **Path**: `examples/matrix_swarm/README.md`, `examples/matrix_swarm/Makefile`
- **Responsibility**:
  - README: prerequisites → setup → configure → run → interact → troubleshoot
  - Makefile targets: `setup` (bootstrap.sh), `start` (compose up), `stop`
    (compose down), `logs` (compose logs), `demo` (python swarm_demo.py),
    `clean` (compose down -v)
- **Depends on**: Module 3

### Module 5: Environment Template (`.env.example`)

- **Path**: `examples/matrix_swarm/.env.example`
- **Responsibility**: Template listing ALL required env vars with descriptions
- **Depends on**: nothing (pure data)
- **Contents**:
  ```bash
  # === Matrix Homeserver (from bootstrap.sh output) ===
  MATRIX_AS_TOKEN=          # AppService token from registration.yaml
  MATRIX_HS_TOKEN=          # Homeserver token from registration.yaml
  MATRIX_GENERAL_ROOM_ID=   # Room ID of the general/swarm room

  # === LLM Provider API Keys ===
  OPENAI_API_KEY=           # For Researcher agent (gpt-4o)
  ANTHROPIC_API_KEY=        # For Analyst agent (claude-sonnet-4-20250514)
  GOOGLE_API_KEY=           # For Writer agent (gemini-2.5-flash)
  NVIDIA_API_KEY=           # For Summarizer agent (meta/llama-3.3-70b-instruct)
  ```

### Module 6: Tests

- **Path**: `examples/matrix_swarm/tests/test_swarm_sample.py`
- **Responsibility**: Validates that the sample's YAML files load correctly
  and that agent definitions match swarm config expectations.
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_agents_yaml_loads` | 1 | agents.yaml parses, has 4 agents, each with required fields |
| `test_agents_chatbot_ids_match_config` | 1, 2 | chatbot_ids in agents.yaml match agent entries in swarm_config.yaml |
| `test_swarm_config_loads` | 2 | swarm_config.yaml loads via `MatrixCrewConfig.from_yaml()` with env defaults |
| `test_swarm_config_channels` | 2 | Config has 2 channels: general (swarm policy) + finance (mention policy) |
| `test_swarm_config_tunnels` | 2 | Tunnels enabled with expected defaults |
| `test_swarm_config_collaborative` | 2 | Collaborative mode configured with summarizer_agent |
| `test_llm_strings_valid` | 1 | Every agent's `llm` string parses via `LLMFactory.parse_llm_string()` |
| `test_env_example_has_all_keys` | 5 | .env.example lists all 7 required env vars |
| `test_makefile_targets` | 4 | Makefile has setup/start/stop/logs/demo/clean targets |
| `test_demo_script_syntax` | 3 | swarm_demo.py compiles without syntax errors |

### Integration Tests

| Test | Description |
|---|---|
| `test_agent_instantiation` | Creates all 4 agents with mock LLM clients (no real API keys) |
| `test_botmanager_registration` | Registers agents in BotManager and retrieves them by chatbot_id |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_env(monkeypatch):
    """Set minimal env vars for config loading."""
    for k, v in {
        "MATRIX_AS_TOKEN": "test-as-token",
        "MATRIX_HS_TOKEN": "test-hs-token",
        "MATRIX_GENERAL_ROOM_ID": "!test:parrot.local",
        "OPENAI_API_KEY": "sk-test",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "GOOGLE_API_KEY": "test-google-key",
        "NVIDIA_API_KEY": "nvapi-test",
    }.items():
        monkeypatch.setenv(k, v)
```

---

## 5. Acceptance Criteria

- [ ] `examples/matrix_swarm/` directory exists with all 6 files (agents.yaml, swarm_config.yaml, swarm_demo.py, README.md, Makefile, .env.example)
- [ ] `agents.yaml` defines 4 agents using 4 different providers: `openai`, `anthropic`, `google`, `nvidia`
- [ ] Each agent has: name, chatbot_id, llm string, system_prompt (≥3 sentences)
- [ ] `swarm_config.yaml` loads successfully via `MatrixCrewConfig.from_yaml()` with env defaults
- [ ] `swarm_config.yaml` chatbot_ids match `agents.yaml` chatbot_ids exactly
- [ ] `swarm_demo.py` instantiates all 4 agents with correct LLM clients and registers them in BotManager
- [ ] `swarm_demo.py` starts MatrixCrewTransport and shuts down cleanly on SIGINT
- [ ] `README.md` includes: prerequisites, setup (bootstrap.sh), env configuration, running the demo, interacting with agents, troubleshooting
- [ ] `Makefile` targets work: `make setup`, `make start`, `make stop`, `make logs`, `make demo`, `make clean`
- [ ] `.env.example` lists all 7 required env vars with descriptions
- [ ] All tests pass: `pytest examples/matrix_swarm/tests/ -v`
- [ ] `ruff check examples/matrix_swarm/`
- [ ] No FEAT-463 core modules are modified — sample is purely additive

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.bots.agent import BasicAgent               # verified: bots/agent.py:29
from parrot.clients.factory import LLMFactory           # verified: clients/factory.py:161
from parrot.manager import BotManager                   # verified: manager/__init__.py → manager/manager.py:109
from parrot.integrations.matrix.crew import MatrixCrewTransport  # verified: matrix/crew/transport.py (lazy map in matrix/__init__.py)
from parrot.integrations.matrix.crew.config import MatrixCrewConfig  # verified: crew/config.py:139
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):            # :29
    def __init__(
        self,
        name: str = "Agent",                             # :64
        agent_id: str = "agent",                         # :65
        use_llm: str = "google",                         # :66
        llm: str = None,                                 # :67
        tools: List[AbstractTool] = None,                # :68
        system_prompt: str = None,                       # :69
        human_prompt: str = None,                        # :70
        use_tools: bool = True,                          # :71
        instructions: Optional[str] = None,              # :72
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,  # :73
        **kwargs,                                        # :74 — passes chatbot_id, etc.
    ):

class Agent(BasicAgent):                                 # :1236

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:                                       # :187
    def __init__(self,
        name: str = 'Nav',                               # :281
        system_prompt: str = None,                       # :282
        llm: Union[str, Type[AbstractClient], AbstractClient, Callable, str] = None,  # :283
        ...
        **kwargs                                         # :301
    ):
        self.chatbot_id: uuid.UUID = kwargs.get(         # :353
            'chatbot_id',
            str(uuid.uuid4().hex)
        )
```

```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                        # :161
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # :170
        # "provider:model" → (provider, model)
        # "provider" → (provider, None)

    @staticmethod
    def create(                                          # :192
        llm: str,                                        # "openai:gpt-4o"
        model_args: Optional[Dict[str, Any]] = None,
        tool_manager: Optional[Any] = None,
        **kwargs
    ) -> AbstractClient:

SUPPORTED_CLIENTS = {                                    # :107
    "openai": OpenAIClient,                              # :128
    "anthropic": AnthropicClient,                        # :109 (also "claude")
    "google": GoogleGenAIClient,                         # :127
    "nvidia": NvidiaClient,                              # :135
    ...
}
```

```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                        # :109
    def __init__(self, ...):
        self._bots: Dict[str, AbstractBot] = {}          # :141

    def add_agent(self, agent: AbstractBot) -> None:     # :927
        """Add a Agent to the manager."""
        self._bots[str(agent.chatbot_id)] = agent        # :929

    async def get_bot(self, name: str, ...) -> AbstractBot:  # :671
        # Used by MatrixCrewTransport.start() to resolve agents

    def get_bots(self) -> Dict[str, AbstractBot]:        # :918
        return self._bots
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/transport.py
class MatrixCrewTransport:
    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewTransport":   # :62
        config = MatrixCrewConfig.from_yaml(path)
        return cls(config)

    async def start(self) -> None:                       # :78
        # ... at :224-226:
        from parrot.manager import BotManager
        bot = await BotManager.get_bot(
            self._config.agents[agent_name].chatbot_id   # ← must match
        )

# packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/config.py
class MatrixCrewConfig(BaseModel):                       # :139
    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewConfig": # :217
        # yaml.safe_load + _walk_and_substitute (${ENV_VAR} replacement)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `swarm_demo.py` | `LLMFactory.create()` | `"openai:gpt-4o"` string | `factory.py:192` |
| `swarm_demo.py` | `BasicAgent(chatbot_id=...)` | kwargs | `abstract.py:353` |
| `swarm_demo.py` | `BotManager.add_agent(agent)` | method call | `manager.py:927` |
| `swarm_demo.py` | `MatrixCrewTransport.from_yaml()` | classmethod | `transport.py:62` |
| `swarm_config.yaml` | `MatrixCrewConfig.from_yaml()` | YAML load + env substitution | `config.py:217` |
| `Makefile` | `docker-compose.matrix.yml` | `docker compose -f` | repo root |
| `Makefile` | `scripts/matrix/bootstrap.sh` | shell call | `scripts/matrix/` |

### Does NOT Exist (Anti-Hallucination)

- ~~`BotManager.register(name, agent)`~~ — the method is `add_agent(agent)`, not `register()`. The existing `swarm_example.py` comment is wrong (line 137).
- ~~`BotManager.add_bot(agent)` for MatrixCrewTransport lookup~~ — `add_bot()` (line 665) keys by `bot.name`; `add_agent()` (line 927) keys by `str(agent.chatbot_id)`. Since `MatrixCrewTransport.start()` calls `BotManager.get_bot(chatbot_id)`, the sample MUST use `add_agent()`, NOT `add_bot()`.
- ~~`BotManager.load_agents_from_yaml(path)`~~ — no such method; the sample must parse `agents.yaml` itself and call `add_agent()` for each.
- ~~`Agent.from_config(dict)`~~ — no factory method; use `BasicAgent(**kwargs)`.
- ~~`MatrixCrewTransport.register_agents()`~~ — transport looks up agents from BotManager, not from a registration call.
- ~~`parrot.integrations.matrix.crew.swarm_toolkit`~~ — `AgentSwarmToolkit` is NOT yet implemented (FEAT-463 TASK-2483, status: pending). The sample must handle its absence gracefully.
- ~~`examples/matrix_swarm/`~~ — does not exist yet; you create the entire directory.
- ~~`parrot.tools.web_search`~~ — verify before use; tool names may differ from what seems obvious.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Example script pattern**: follow `examples/matrix_crew/swarm_example.py` —
  argparse CLI, `asyncio.run()`, signal handlers for graceful shutdown, `async with transport`.
- **Agent instantiation**: use `BasicAgent(name=..., chatbot_id=..., llm=..., system_prompt=..., tools=..., use_tools=True)` — the `llm` parameter accepts `"provider:model"` strings directly.
- **BotManager singleton**: import `from parrot.manager import BotManager` and
  use `BotManager.add_agent(agent)` — the global instance is used by
  `MatrixCrewTransport.start()` to resolve agents.
- **Config env substitution**: `MatrixCrewConfig.from_yaml()` replaces
  `${VAR_NAME}` with `os.environ[VAR_NAME]` via `_walk_and_substitute()`.
- **Logging**: use `logging.getLogger(__name__)` — set aiohttp/mautrix to WARNING.
- **Google-style docstrings** on all functions.
- **Type hints** throughout.

### Known Risks / Gotchas

1. **FEAT-463 dependency**: FEAT-464 cannot be fully tested end-to-end until
   FEAT-463 core modules (especially TASK-2478 config models and TASK-2484
   transport wiring) are implemented. Unit tests for YAML loading and agent
   instantiation work independently.
2. **BotManager global state**: `BotManager` is a singleton-ish pattern — the
   sample must instantiate it before calling `add_agent()`. In a standalone
   script context (no aiohttp app), a simple `BotManager()` suffices.
3. **Tool availability**: the sample references tools by name (`web_search`,
   `sql_query`, etc.) — these must exist in `parrot_tools` or be mocked. If
   a tool doesn't exist, the agent should still work (tools are optional).
4. **API keys**: all 4 providers require API keys. The README must clearly
   state which keys are needed and link to each provider's key creation page.
5. **Nvidia NIM model path**: Nvidia models use `org/model` format (e.g.
   `meta/llama-3.3-70b-instruct`), not bare model names.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `ai-parrot[all]` | `>=0.28.0` | Core framework + all LLM clients |
| `ai-parrot-server` | `>=0.28.0` | BotManager |
| `ai-parrot-integrations[matrix]` | `>=0.28.0` | MatrixCrewTransport |
| `docker` + `docker compose` | `>=24.0` | Matrix dev stack |
| `python-dotenv` | `>=1.0` | .env file loading (optional, convenience) |

---

## 8. Open Questions

### Resolved (from proposal)

- [x] Should the sample create a new directory or extend `examples/matrix_crew/`?
  — *Resolved in proposal*: New `examples/matrix_swarm/` for clean separation.

- [x] Which LLM providers should the sample use?
  — *Resolved in proposal*: 4 different providers — OpenAI (researcher),
  Anthropic (analyst), Google Gemini (writer), Nvidia NIM (summarizer).

### Remaining

- [ ] Should `swarm_demo.py` include a `--mock` flag for running with echo/stub
  agents (no API keys needed)? — *Owner: implementation agent*
  Recommendation: yes — makes the demo accessible without 4 API keys.

- [ ] Which specific tools from `parrot_tools` should be attached to researcher
  and analyst? Verify what exists before assigning. — *Owner: implementation agent*

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Parallelism**: None needed. Tasks are small and sequential (YAML → script → docs → tests).
- **Cross-feature dependency**: FEAT-463 must be merged to `dev` before
  FEAT-464 can be fully integration-tested. Unit tests (YAML loading, agent
  instantiation with mocks) can run independently.
- **Worktree creation** (after `/sdd-task`):
  ```bash
  git checkout dev && git pull origin dev
  git worktree add -b feat-464-matrix-swarm-sample \
    .claude/worktrees/feat-464-matrix-swarm-sample HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-26 | Jesus Lara (via Claude) | Initial draft from FEAT-464 proposal |
