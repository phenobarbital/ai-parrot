---
type: Wiki Overview
title: 'TASK-1301: Example and Documentation'
id: doc:sdd-tasks-completed-task-1301-example-and-documentation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The collaborative session feature is implemented but needs a working example
  and
relates_to:
- concept: mod:parrot.integrations.matrix.crew
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.config
  rel: mentions
---

# TASK-1301: Example and Documentation

**Feature**: FEAT-195 — Matrix Collaborative Multi-Agent Crew
**Spec**: `sdd/specs/matrix-collaborative-crew.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1299
**Assigned-to**: unassigned

---

## Context

The collaborative session feature is implemented but needs a working example and
updated configuration to demonstrate it. This task updates the existing Matrix crew
example to include collaborative mode with `!investigate`, and adds a second YAML
config file showing collaborative settings.

Implements Spec Module 7.

---

## Scope

- Update `examples/matrix_crew/matrix_crew_example.py` to mention collaborative mode
  in setup/usage comments.
- Create `examples/matrix_crew/collaborative_crew.yaml` — example YAML config with
  `collaborative:` section showing all options.
- Create `examples/matrix_crew/collaborative_example.py` — standalone example demonstrating
  collaborative session setup, or extend the existing example with a flag.
- Ensure the example shows:
  - Agent configuration with a dedicated summarizer.
  - `!investigate` trigger usage.
  - YAML config with `collaborative:` section.

**NOT in scope**: Implementation changes, new features, tests for the example.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/matrix_crew/collaborative_crew.yaml` | CREATE | Example YAML with collaborative config |
| `examples/matrix_crew/collaborative_example.py` | CREATE | Working example of collaborative crew |
| `examples/matrix_crew/matrix_crew_example.py` | MODIFY | Add mention of collaborative mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew import MatrixCrewTransport  # crew/__init__.py
from parrot.integrations.matrix.crew import MatrixCrewConfig  # crew/__init__.py
from parrot.integrations.matrix.crew.config import CollaborativeConfig  # TASK-1296
```

### Existing Signatures to Use
```python
# examples/matrix_crew/matrix_crew_example.py (existing example)
# Loads config from YAML, creates MatrixCrewTransport, registers agents, runs.
# Pattern:
#   config = MatrixCrewConfig.from_yaml("path/to/config.yaml")
#   transport = MatrixCrewTransport(config=config)
#   await transport.start()

# parrot/integrations/matrix/crew/config.py:140
@classmethod
def from_yaml(cls, path: str) -> "MatrixCrewConfig":
```

### Does NOT Exist
- ~~`examples/matrix_crew/collaborative_crew.yaml`~~ — this is what we're creating
- ~~`examples/matrix_crew/collaborative_example.py`~~ — this is what we're creating

---

## Implementation Notes

### Pattern to Follow

**collaborative_crew.yaml:**
```yaml
homeserver_url: "http://localhost:8008"
server_name: "example.local"
as_token: "${MATRIX_AS_TOKEN}"
hs_token: "${MATRIX_HS_TOKEN}"
bot_mxid: "@parrot-bot:example.local"
general_room_id: "!general:example.local"
appservice_port: 8449

agents:
  analyst:
    chatbot_id: "financial-analyst"
    display_name: "Financial Analyst"
    mxid_localpart: "analyst"
    skills: ["market-analysis", "financial-data"]
  researcher:
    chatbot_id: "web-researcher"
    display_name: "Web Researcher"
    mxid_localpart: "researcher"
    skills: ["web-search", "summarization"]
  summarizer:
    chatbot_id: "synthesis-agent"
    display_name: "Synthesis Agent"
    mxid_localpart: "summarizer"
    skills: ["synthesis", "scoring"]

collaborative:
  command_prefix: "!investigate"
  max_rounds: 2
  agent_timeout: 120.0
  session_timeout: 600.0
  summarizer_agent: "summarizer"
  session_verbosity: "full"
  include_chat_context: true
```

**collaborative_example.py** should follow the same structure as
`matrix_crew_example.py` (which is ~221 lines) but include comments
explaining the collaborative flow.

### Key Constraints
- Example YAML must include `${ENV_VAR}` patterns for secrets (as_token, hs_token).
- Example must be functional — if someone fills in the env vars and runs it,
  `!investigate` should work.
- Keep it concise — this is a reference example, not a tutorial.

### References in Codebase
- `examples/matrix_crew/matrix_crew_example.py` — existing example pattern to follow
- `examples/matrix_crew/crew_config.yaml` — existing YAML config pattern

---

## Acceptance Criteria

- [ ] `collaborative_crew.yaml` created with all `collaborative:` fields
- [ ] `collaborative_example.py` created and runnable (with correct env vars)
- [ ] Existing `matrix_crew_example.py` updated with collaborative mode mention
- [ ] Example YAML uses `${ENV_VAR}` patterns for secrets
- [ ] Summarizer agent configured in the example
- [ ] Comments explain the `!investigate` trigger and session flow
- [ ] No linting errors: `ruff check examples/matrix_crew/`

---

## Test Specification

No automated tests for this task — it is an example/documentation update.
Manual verification: review the YAML config loads correctly by instantiating
`MatrixCrewConfig.from_yaml()` with the example config.

```python
# Quick manual check (not an automated test):
from parrot.integrations.matrix.crew.config import MatrixCrewConfig

config = MatrixCrewConfig.from_yaml("examples/matrix_crew/collaborative_crew.yaml")
assert config.collaborative is not None
assert config.collaborative.summarizer_agent == "summarizer"
assert config.collaborative.max_rounds == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1299 is in `tasks/completed/`
3. **Read the existing example** at `examples/matrix_crew/matrix_crew_example.py`
4. **Update status** in `sdd/tasks/index/matrix-collaborative-crew.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1301-example-and-documentation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

### Completion Note

Created `examples/matrix_crew/collaborative_crew.yaml` — full YAML config with
`collaborative:` section, all fields documented with comments, uses `${ENV_VAR}` for secrets.

Created `examples/matrix_crew/collaborative_example.py` — standalone example following the
same pattern as `matrix_crew_example.py`, with expanded docstring explaining the collaborative
flow, `_setup_bots()` with commented-out real agent examples, and config validation at startup.
File force-added with `git add -f` due to `examples/**/*.py` .gitignore rule.

Modified `examples/matrix_crew/matrix_crew_example.py` — added "Collaborative investigation mode"
section to the module docstring with usage snippet and reference to the collaborative example files.

YAML validated: `MatrixCrewConfig.from_yaml("collaborative_crew.yaml")` loads correctly, all
`collaborative:` fields match spec. Lint clean.
