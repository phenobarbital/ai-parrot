# TASK-2489: Swarm Configuration & Demo Script

**Feature**: FEAT-464 — Matrix Swarm Sample
**Spec**: `sdd/specs/matrix-swarm-sample.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2488
**Assigned-to**: unassigned

---

## Context

> This task creates the two core runtime files: the MatrixCrewConfig YAML and
> the runnable Python demo script. Together they form the beating heart of the
> sample — a user runs `python swarm_demo.py` and gets 4 agents live on Matrix.
>
> Implements Spec Modules 2 (Swarm Configuration) and 3 (Demo Script).

---

## Scope

- Create `examples/matrix_swarm/swarm_config.yaml` — a self-contained
  MatrixCrewConfig with extensive inline comments.
- Create `examples/matrix_swarm/swarm_demo.py` — a runnable Python script
  that loads agents from `agents.yaml`, creates LLM clients, registers them
  in BotManager, and starts MatrixCrewTransport.

**NOT in scope**:
- Agent definitions / .env.example (TASK-2488 — already done)
- README / Makefile (TASK-2490)
- Tests (TASK-2491)
- FEAT-463 core module implementation

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/matrix_swarm/swarm_config.yaml` | CREATE | MatrixCrewConfig (channels, tunnels, collaborative mode) |
| `examples/matrix_swarm/swarm_demo.py` | CREATE | Runnable demo script |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
from parrot.bots.agent import BasicAgent               # verified: bots/agent.py:29
from parrot.clients.factory import LLMFactory           # verified: clients/factory.py:161
from parrot.manager import BotManager                   # verified: manager/__init__.py → manager/manager.py:109
from parrot.integrations.matrix.crew import MatrixCrewTransport  # verified: matrix/crew/transport.py
from parrot.integrations.matrix.crew.config import MatrixCrewConfig  # verified: crew/config.py:139
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/agent.py:62-74
class BasicAgent(Chatbot, NotificationMixin):            # :29
    def __init__(
        self,
        name: str = "Agent",
        agent_id: str = "agent",
        use_llm: str = "google",
        llm: str = None,          # accepts "provider:model" strings
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        use_tools: bool = True,
        **kwargs,                  # chatbot_id passed here → abstract.py:353
    ):

# packages/ai-parrot/src/parrot/bots/abstract.py:353
self.chatbot_id: uuid.UUID = kwargs.get('chatbot_id', str(uuid.uuid4().hex))

# packages/ai-parrot/src/parrot/clients/factory.py:192
class LLMFactory:
    @staticmethod
    def create(
        llm: str,                  # "openai:gpt-4o"
        model_args: Optional[Dict[str, Any]] = None,
        tool_manager: Optional[Any] = None,
        **kwargs
    ) -> AbstractClient:

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                        # :109
    def __init__(self, ...):
        self._bots: Dict[str, AbstractBot] = {}          # :141

    def add_agent(self, agent: AbstractBot) -> None:     # :927
        self._bots[str(agent.chatbot_id)] = agent        # :929

# packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/transport.py
class MatrixCrewTransport:
    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewTransport":  # :62

    async def start(self) -> None:                       # :78
        # at :224-226:
        bot = await BotManager.get_bot(
            self._config.agents[agent_name].chatbot_id
        )

# packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/config.py
class MatrixCrewConfig(BaseModel):                       # :139
    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewConfig": # :217
        # yaml.safe_load + _walk_and_substitute (${ENV_VAR} replacement)
```

### Does NOT Exist

- ~~`BotManager.register(name, agent)`~~ — use `add_agent(agent)` (keys by chatbot_id)
- ~~`BotManager.add_bot(agent)` for transport lookup~~ — `add_bot()` keys by `name`, NOT `chatbot_id`. Use `add_agent()`.
- ~~`BotManager.load_agents_from_yaml(path)`~~ — no such method; parse agents.yaml yourself
- ~~`Agent.from_config(dict)`~~ — no factory method; use `BasicAgent(**kwargs)`
- ~~`MatrixCrewTransport.register_agents()`~~ — transport looks up agents from BotManager
- ~~`parrot.integrations.matrix.crew.swarm_toolkit`~~ — `AgentSwarmToolkit` is NOT yet implemented (FEAT-463 TASK-2483). Handle its absence gracefully.

---

## Implementation Notes

### Swarm Configuration (`swarm_config.yaml`)

Adapt from `examples/matrix_crew/swarm_crew.yaml` but make it self-contained
with extensive inline comments explaining each block. Structure:

```yaml
homeserver:
  url: "http://localhost:8008"        # Local Synapse (docker-compose.matrix.yml)
  domain: "parrot.local"

appservice:
  as_token: "${MATRIX_AS_TOKEN}"      # From bootstrap.sh output
  hs_token: "${MATRIX_HS_TOKEN}"

agents:
  web-researcher:                     # Must match agents.yaml chatbot_id
    chatbot_id: "web-researcher"
    display_name: "🔍 Researcher"
  financial-analyst:
    chatbot_id: "financial-analyst"
    display_name: "📊 Analyst"
  report-writer:
    chatbot_id: "report-writer"
    display_name: "✍️ Writer"
  synthesis-agent:
    chatbot_id: "synthesis-agent"
    display_name: "🧠 Synthesizer"

channels:
  general:
    room_id: "${MATRIX_GENERAL_ROOM_ID}"
    answer_policy: "swarm"            # All agents can answer
  finance:
    room_id: "${MATRIX_FINANCE_ROOM_ID}"
    answer_policy: "mention"          # Only mentioned agent answers

tunnels:
  enabled: true                       # Agent-to-agent private channels

collaborative:
  enabled: true
  summarizer_agent: "synthesis-agent"  # Synthesizer produces final answers
```

### Demo Script (`swarm_demo.py`)

Follow `examples/matrix_crew/swarm_example.py` structure:

1. **Shebang + imports**: `#!/usr/bin/env python3`, standard lib + parrot imports
2. **`load_agents(yaml_path)`**: reads `agents.yaml`, returns list of dicts
3. **`setup_agents(agent_defs)`**:
   - For each agent def, create `BasicAgent(name=..., chatbot_id=..., llm=..., system_prompt=..., use_tools=bool(tools))`
   - Register each via `BotManager.add_agent(agent)`
4. **`async def main(args)`**:
   - Load dotenv (optional)
   - Call `load_agents()` + `setup_agents()`
   - Create `transport = MatrixCrewTransport.from_yaml("swarm_config.yaml")`
   - `async with transport:` block — runs until SIGINT/SIGTERM
5. **`if __name__ == "__main__"`**: argparse (--config, --agents), signal setup, `asyncio.run(main(args))`

### Key Constraints

- **Async throughout**: `asyncio.run()`, `async with transport:`, no blocking I/O
- **Graceful shutdown**: handle SIGINT/SIGTERM with `loop.add_signal_handler()`
- **Google-style docstrings** on all functions
- **Type hints** throughout
- **Logging**: `logging.getLogger(__name__)`, set aiohttp/mautrix to WARNING
- The `llm` parameter on BasicAgent accepts `"provider:model"` strings directly —
  no need to call `LLMFactory.create()` separately (the agent does it internally)
- chatbot_id MUST be passed via `**kwargs` to BasicAgent, not as a positional arg

### References in Codebase

- `examples/matrix_crew/swarm_example.py` — the pattern to follow (structure, argparse, signal handling)
- `examples/matrix_crew/swarm_crew.yaml` — the config structure to adapt
- `examples/matrix_crew/collaborative_example.py` — another example of async transport usage

---

## Acceptance Criteria

- [ ] `swarm_config.yaml` loads via `MatrixCrewConfig.from_yaml()` with env defaults
- [ ] `swarm_config.yaml` agent chatbot_ids match `agents.yaml` chatbot_ids exactly
- [ ] `swarm_config.yaml` has 2 channels (general: swarm, finance: mention)
- [ ] `swarm_config.yaml` has tunnels enabled and collaborative mode with synthesizer
- [ ] `swarm_demo.py` compiles without syntax errors (`python -m py_compile`)
- [ ] `swarm_demo.py` loads agents from `agents.yaml` and creates BasicAgent instances
- [ ] `swarm_demo.py` registers agents in BotManager via `add_agent()` (NOT `add_bot()`)
- [ ] `swarm_demo.py` starts MatrixCrewTransport from `swarm_config.yaml`
- [ ] `swarm_demo.py` handles SIGINT/SIGTERM gracefully
- [ ] `ruff check examples/matrix_swarm/swarm_demo.py` passes
- [ ] Type hints on all functions, Google-style docstrings

---

## Test Specification

```python
# examples/matrix_swarm/tests/test_swarm_sample.py (subset)
import ast
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

SAMPLE_DIR = Path(__file__).parent.parent


def test_swarm_config_loads():
    """swarm_config.yaml parses with yaml.safe_load."""
    data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
    assert "homeserver" in data
    assert "agents" in data
    assert "channels" in data


def test_chatbot_ids_match():
    """chatbot_ids in agents.yaml match swarm_config.yaml."""
    agents = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
    config = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
    agent_ids = set(agents["agents"].keys())
    config_ids = set(config["agents"].keys())
    assert agent_ids == config_ids


def test_demo_script_syntax():
    """swarm_demo.py compiles without syntax errors."""
    source = (SAMPLE_DIR / "swarm_demo.py").read_text()
    ast.parse(source)  # Raises SyntaxError if invalid


def test_swarm_config_channels():
    """Config has 2 channels with expected policies."""
    data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
    channels = data["channels"]
    assert len(channels) >= 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2488 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `BasicAgent.__init__` signature and `chatbot_id` via kwargs
   - Confirm `BotManager.add_agent()` still keys by `chatbot_id`
   - Confirm `MatrixCrewTransport.from_yaml()` and `MatrixCrewConfig.from_yaml()` signatures
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Read `examples/matrix_crew/swarm_example.py`** for the established pattern
5. **Read `examples/matrix_crew/swarm_crew.yaml`** for the config structure
6. **Update status** in `sdd/tasks/index/matrix-swarm-sample.json` → `"in-progress"`
7. **Implement** following the scope, codebase contract, and notes above
8. **Verify** all acceptance criteria are met
9. **Move this file** to `sdd/tasks/completed/TASK-2489-swarm-config-and-demo-script.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
