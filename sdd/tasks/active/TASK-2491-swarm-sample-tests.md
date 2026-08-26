# TASK-2491: Swarm Sample Tests

**Feature**: FEAT-464 — Matrix Swarm Sample
**Spec**: `sdd/specs/matrix-swarm-sample.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2488, TASK-2489
**Assigned-to**: unassigned

---

## Context

> This task creates the test suite that validates the Matrix swarm sample's
> YAML files load correctly, agent definitions match the swarm config,
> agents instantiate with mock LLM clients, and the demo script is
> syntactically valid.
>
> Implements Spec Module 6 (Tests).

---

## Scope

- Create `examples/matrix_swarm/tests/__init__.py` (empty)
- Create `examples/matrix_swarm/tests/test_swarm_sample.py` with all unit
  and integration tests from the spec's Test Specification (§4).

**NOT in scope**:
- End-to-end tests against a running Matrix homeserver (requires FEAT-463)
- Creating or modifying any sample files (those are TASK-2488/2489/2490)
- Testing MatrixCrewTransport.start() (depends on FEAT-463 wiring)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/matrix_swarm/tests/__init__.py` | CREATE | Empty package marker |
| `examples/matrix_swarm/tests/test_swarm_sample.py` | CREATE | Full test suite |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.

### Verified Imports

```python
from parrot.bots.agent import BasicAgent               # verified: bots/agent.py:29
from parrot.clients.factory import LLMFactory           # verified: clients/factory.py:161
from parrot.manager import BotManager                   # verified: manager/__init__.py → manager/manager.py:109
```

### Existing Signatures to Use

```python
# BasicAgent constructor — agent.py:62-74
BasicAgent(
    name: str = "Agent",
    agent_id: str = "agent",
    use_llm: str = "google",
    llm: str = None,
    tools: List[AbstractTool] = None,
    system_prompt: str = None,
    use_tools: bool = True,
    **kwargs,  # chatbot_id passed here
)

# LLMFactory.parse_llm_string — factory.py:170
LLMFactory.parse_llm_string(llm: str) -> Tuple[str, Optional[str]]

# BotManager.add_agent — manager.py:927
BotManager.add_agent(agent: AbstractBot) -> None
# Keys by str(agent.chatbot_id) at :929
```

### Does NOT Exist

- ~~`LLMFactory.validate_llm_string()`~~ — use `parse_llm_string()` to verify format
- ~~`BotManager.get_agents()`~~ — use `get_bots()` (line 918) which returns `self._bots`
- ~~`MatrixCrewConfig.from_yaml()` without env vars~~ — it calls `_walk_and_substitute()` which reads `os.environ`; mock env vars with `monkeypatch`

---

## Implementation Notes

### Test Categories

**Unit Tests** (no external services):

| Test | Description |
|---|---|
| `test_agents_yaml_loads` | agents.yaml parses with 4 agents |
| `test_agents_have_required_fields` | Each agent has name, llm, system_prompt |
| `test_agents_use_different_providers` | 4 unique providers: openai, anthropic, google, nvidia |
| `test_agents_chatbot_ids_match_config` | chatbot_ids in agents.yaml match swarm_config.yaml |
| `test_swarm_config_loads` | swarm_config.yaml parses with yaml.safe_load |
| `test_swarm_config_channels` | At least 2 channels defined |
| `test_llm_strings_valid` | All llm strings parse via `LLMFactory.parse_llm_string()` |
| `test_env_example_has_all_keys` | .env.example contains all 7 env vars |
| `test_makefile_targets` | Makefile has setup/start/stop/logs/demo/clean |
| `test_demo_script_syntax` | swarm_demo.py compiles with `ast.parse()` |
| `test_readme_exists` | README.md has expected sections |

**Integration Tests** (mock LLM clients):

| Test | Description |
|---|---|
| `test_agent_instantiation` | Create all 4 BasicAgent instances with mock LLM |
| `test_botmanager_registration` | Register agents in BotManager, retrieve by chatbot_id |

### Test Fixtures

```python
@pytest.fixture
def mock_env(monkeypatch):
    """Set minimal env vars for config loading."""
    for k, v in {
        "MATRIX_AS_TOKEN": "test-as-token",
        "MATRIX_HS_TOKEN": "test-hs-token",
        "MATRIX_GENERAL_ROOM_ID": "!test:parrot.local",
        "MATRIX_FINANCE_ROOM_ID": "!finance:parrot.local",
        "OPENAI_API_KEY": "sk-test",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "GOOGLE_API_KEY": "test-google-key",
        "NVIDIA_API_KEY": "nvapi-test",
    }.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def sample_dir():
    """Path to the matrix_swarm sample directory."""
    return Path(__file__).parent.parent
```

### Key Constraints

- Use `pytest` + `pytest-asyncio` (project standard)
- Use `monkeypatch` for env vars — never set real API keys in tests
- Agent instantiation tests must mock the LLM client (don't call real APIs)
- Use `unittest.mock.patch` to mock `LLMFactory.create()` in integration tests
- All test paths should be relative to the sample directory (portable)
- Follow existing test patterns in the codebase

### References in Codebase

- `tests/` — existing test patterns
- `examples/matrix_crew/` — the sample files being tested
- Spec §4 (Test Specification) — defines exact test cases and fixtures

---

## Acceptance Criteria

- [ ] `examples/matrix_swarm/tests/__init__.py` exists (empty)
- [ ] `examples/matrix_swarm/tests/test_swarm_sample.py` exists with all tests
- [ ] All unit tests pass: `pytest examples/matrix_swarm/tests/test_swarm_sample.py -v -k "not integration"`
- [ ] Integration tests pass with mocked LLM: `pytest examples/matrix_swarm/tests/ -v -k "integration"`
- [ ] `ruff check examples/matrix_swarm/tests/`
- [ ] Tests do NOT require real API keys or a running Matrix homeserver

---

## Test Specification

```python
# examples/matrix_swarm/tests/test_swarm_sample.py
import ast
import re
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

SAMPLE_DIR = Path(__file__).parent.parent


# --- Unit Tests ---

class TestAgentsYaml:
    def test_agents_yaml_loads(self):
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        assert "agents" in data
        assert len(data["agents"]) == 4

    def test_agents_have_required_fields(self):
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        for agent_id, agent in data["agents"].items():
            assert "name" in agent
            assert "llm" in agent
            assert "system_prompt" in agent

    def test_agents_use_different_providers(self):
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        providers = [a["llm"].split(":")[0] for a in data["agents"].values()]
        assert set(providers) == {"openai", "anthropic", "google", "nvidia"}


class TestSwarmConfig:
    def test_swarm_config_loads(self):
        data = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        assert "homeserver" in data
        assert "agents" in data

    def test_chatbot_ids_match(self):
        agents = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        config = yaml.safe_load((SAMPLE_DIR / "swarm_config.yaml").read_text())
        assert set(agents["agents"].keys()) == set(config["agents"].keys())


class TestDemoScript:
    def test_demo_script_syntax(self):
        source = (SAMPLE_DIR / "swarm_demo.py").read_text()
        ast.parse(source)


class TestEnvironment:
    def test_env_example_has_all_keys(self):
        content = (SAMPLE_DIR / ".env.example").read_text()
        for key in [
            "MATRIX_AS_TOKEN", "MATRIX_HS_TOKEN", "MATRIX_GENERAL_ROOM_ID",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "NVIDIA_API_KEY",
        ]:
            assert key in content


class TestDocumentation:
    def test_readme_exists(self):
        readme = (SAMPLE_DIR / "README.md").read_text()
        for section in ["Prerequisites", "Quick Start"]:
            assert section.lower() in readme.lower()

    def test_makefile_targets(self):
        makefile = (SAMPLE_DIR / "Makefile").read_text()
        for target in ["setup", "start", "stop", "logs", "demo", "clean"]:
            assert re.search(rf"^{target}\s*:", makefile, re.MULTILINE)


# --- Integration Tests ---

class TestAgentIntegration:
    @pytest.fixture
    def agent_defs(self):
        data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
        return data["agents"]

    @patch("parrot.clients.factory.LLMFactory.create")
    def test_agent_instantiation(self, mock_create, agent_defs):
        """Create all 4 agents with mock LLM clients."""
        mock_create.return_value = MagicMock()
        from parrot.bots.agent import BasicAgent

        agents = []
        for agent_id, defn in agent_defs.items():
            agent = BasicAgent(
                name=defn["name"],
                chatbot_id=agent_id,
                llm=defn["llm"],
                system_prompt=defn["system_prompt"],
                use_tools=bool(defn.get("tools")),
            )
            agents.append(agent)

        assert len(agents) == 4

    @patch("parrot.clients.factory.LLMFactory.create")
    def test_botmanager_registration(self, mock_create, agent_defs):
        """Register agents and retrieve by chatbot_id."""
        mock_create.return_value = MagicMock()
        from parrot.bots.agent import BasicAgent
        from parrot.manager import BotManager

        manager = BotManager()
        for agent_id, defn in agent_defs.items():
            agent = BasicAgent(
                name=defn["name"],
                chatbot_id=agent_id,
                llm=defn["llm"],
                system_prompt=defn["system_prompt"],
            )
            manager.add_agent(agent)

        bots = manager.get_bots()
        assert set(agent_defs.keys()).issubset(set(bots.keys()))
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2488 and TASK-2489 must be complete
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `BasicAgent`, `LLMFactory`, `BotManager` imports resolve
   - Confirm `BotManager.add_agent()` signature and `get_bots()` return
   - Confirm `LLMFactory.parse_llm_string()` exists
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Read the actual sample files** created by TASK-2488 and TASK-2489 to
   ensure tests match their exact structure
5. **Update status** in `sdd/tasks/index/matrix-swarm-sample.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Run tests**: `pytest examples/matrix_swarm/tests/ -v`
8. **Verify** all acceptance criteria are met
9. **Move this file** to `sdd/tasks/completed/TASK-2491-swarm-sample-tests.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
