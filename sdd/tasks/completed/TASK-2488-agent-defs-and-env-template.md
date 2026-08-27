# TASK-2488: Agent Definitions & Environment Template

**Feature**: FEAT-464 — Matrix Swarm Sample
**Spec**: `sdd/specs/matrix-swarm-sample.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task creates the foundational data files for the Matrix swarm sample:
> the 4-agent definition YAML and the environment template. These are pure-data
> files with no Python code, so they can be implemented first with zero
> dependencies. Every subsequent task references the chatbot_ids and env vars
> defined here.
>
> Implements Spec Modules 1 (Agent Definitions) and 5 (Environment Template).

---

## Scope

- Create `examples/matrix_swarm/agents.yaml` with 4 agent definitions,
  each using a different LLM provider.
- Create `examples/matrix_swarm/.env.example` listing all 7 required
  environment variables with descriptive comments.
- Verify that every `llm` string in `agents.yaml` uses a provider key
  present in `LLMFactory.SUPPORTED_CLIENTS`.

**NOT in scope**:
- The swarm config YAML (TASK-2489)
- The Python demo script (TASK-2489)
- README / Makefile (TASK-2490)
- Tests (TASK-2491)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/matrix_swarm/agents.yaml` | CREATE | 4 agent definitions (multi-provider) |
| `examples/matrix_swarm/.env.example` | CREATE | Environment variable template |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
# Not directly needed for this task (pure data files), but these are the
# consumers of agents.yaml — keep the contract aligned:
from parrot.bots.agent import BasicAgent               # verified: bots/agent.py:29
from parrot.clients.factory import LLMFactory           # verified: clients/factory.py:161
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/factory.py:107
SUPPORTED_CLIENTS = {
    "openai": OpenAIClient,       # :128
    "anthropic": AnthropicClient,  # :109 (also "claude")
    "google": GoogleGenAIClient,   # :127
    "nvidia": NvidiaClient,        # :135
}

# LLMFactory.parse_llm_string("openai:gpt-4o") → ("openai", "gpt-4o")
# factory.py:170

# BasicAgent constructor (agent.py:62-74)
# Accepts: name, agent_id, use_llm, llm, tools, system_prompt, use_tools, **kwargs
# chatbot_id is passed via **kwargs → abstract.py:353
```

### Does NOT Exist

- ~~`BotManager.load_agents_from_yaml(path)`~~ — no such method; the demo script (TASK-2489) must parse agents.yaml itself
- ~~`Agent.from_config(dict)`~~ — no factory method on Agent or BasicAgent
- ~~`parrot.tools.web_search`~~ — verify actual tool names before referencing; use WikiToolkit and WorkingMemoryToolkit as resolved in spec

---

## Implementation Notes

### Agent Definitions (`agents.yaml`)

The YAML must define exactly these 4 agents with these chatbot_ids (matching
the swarm_crew.yaml pattern from FEAT-463):

| Agent | chatbot_id | llm string | Tools |
|-------|-----------|-----------|-------|
| Researcher | `web-researcher` | `openai:gpt-4o` | WikiToolkit, WorkingMemoryToolkit |
| Financial Analyst | `financial-analyst` | `anthropic:claude-sonnet-4-20250514` | WikiToolkit, WorkingMemoryToolkit |
| Report Writer | `report-writer` | `google:gemini-2.5-flash` | *(none — pure LLM)* |
| Synthesizer | `synthesis-agent` | `nvidia:meta/llama-3.3-70b-instruct` | *(none — pure LLM)* |

Each agent entry must have:
- `name`: human-readable display name
- `chatbot_id`: string key used by BotManager and MatrixCrewTransport
- `llm`: `"provider:model"` string consumed by `LLMFactory.create()`
- `system_prompt`: multi-line, ≥3 sentences describing the agent's role
- `tools`: list of tool names (optional — omit for agents without tools)

### Environment Template (`.env.example`)

List all 7 required env vars in two sections:
1. **Matrix Homeserver** (3 vars): `MATRIX_AS_TOKEN`, `MATRIX_HS_TOKEN`, `MATRIX_GENERAL_ROOM_ID`
2. **LLM Provider API Keys** (4 vars): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `NVIDIA_API_KEY`

Include a comment per var explaining where to get the value.

### Key Constraints

- System prompts must be substantive (≥3 sentences) — they drive agent behavior.
- LLM strings must use provider keys from SUPPORTED_CLIENTS (verified above).
- Nvidia model uses `org/model` format: `meta/llama-3.3-70b-instruct`.
- chatbot_ids must be exact strings — `MatrixCrewTransport.start()` resolves
  agents via `BotManager.get_bot(chatbot_id)`.

### References in Codebase

- `examples/matrix_crew/swarm_crew.yaml` — existing YAML structure for agents, channels, tunnels
- `docker/matrix/.env.example` — existing env template for docker stack
- `packages/ai-parrot/src/parrot/clients/factory.py` — SUPPORTED_CLIENTS map

---

## Acceptance Criteria

- [ ] `examples/matrix_swarm/agents.yaml` exists and parses with `yaml.safe_load()`
- [ ] Defines exactly 4 agents with chatbot_ids: `web-researcher`, `financial-analyst`, `report-writer`, `synthesis-agent`
- [ ] Each agent has: `name`, `chatbot_id`, `llm`, `system_prompt` (≥3 sentences)
- [ ] LLM strings use 4 different providers: `openai`, `anthropic`, `google`, `nvidia`
- [ ] `examples/matrix_swarm/.env.example` lists all 7 required env vars with comments
- [ ] No Python code or implementation — pure data files

---

## Test Specification

```python
# examples/matrix_swarm/tests/test_swarm_sample.py (subset)
import yaml
from pathlib import Path

SAMPLE_DIR = Path(__file__).parent.parent


def test_agents_yaml_loads():
    """agents.yaml parses and has 4 agents."""
    data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
    assert "agents" in data
    assert len(data["agents"]) == 4


def test_agents_have_required_fields():
    """Each agent has name, chatbot_id, llm, system_prompt."""
    data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
    for agent_id, agent in data["agents"].items():
        assert "name" in agent, f"{agent_id} missing name"
        assert "llm" in agent, f"{agent_id} missing llm"
        assert "system_prompt" in agent, f"{agent_id} missing system_prompt"
        assert len(agent["system_prompt"].strip().split(".")) >= 3, (
            f"{agent_id} system_prompt too short"
        )


def test_agents_use_different_providers():
    """Each agent uses a different LLM provider."""
    data = yaml.safe_load((SAMPLE_DIR / "agents.yaml").read_text())
    providers = [a["llm"].split(":")[0] for a in data["agents"].values()]
    assert set(providers) == {"openai", "anthropic", "google", "nvidia"}


def test_env_example_has_all_keys():
    """.env.example lists all 7 required env vars."""
    content = (SAMPLE_DIR / ".env.example").read_text()
    for key in [
        "MATRIX_AS_TOKEN", "MATRIX_HS_TOKEN", "MATRIX_GENERAL_ROOM_ID",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "NVIDIA_API_KEY",
    ]:
        assert key in content, f"Missing {key} in .env.example"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies (first task)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm SUPPORTED_CLIENTS in `factory.py` still includes all 4 providers
   - Confirm chatbot_id field is at `abstract.py:353`
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/matrix-swarm-sample.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2488-agent-defs-and-env-template.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
