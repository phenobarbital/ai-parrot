# TASK-303 — Matrix Crew Example Script and Documentation

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: medium
**Effort**: L
**Depends on**: TASK-301
**Parallel**: false
**Parallelism notes**: Depends on the full crew transport being complete. Can run in parallel with TASK-302 (tests) but shares no files.

---

## Objective

Create a comprehensive example script demonstrating a Matrix multi-agent crew with 3 agents, each in its own room and all sharing a general room. Include an extensive documentation guide covering setup, configuration, architecture, and production deployment.

## Files to Create/Modify

- `examples/matrix_crew/matrix_crew_example.py` — comprehensive example script
- `examples/matrix_crew/matrix_crew.yaml` — example YAML configuration
- `examples/matrix_crew/MATRIX_CREW_GUIDE.md` — extensive documentation guide

## Implementation Details

### matrix_crew_example.py

A runnable Python script that:

1. **Parses CLI args** (`--config` for YAML path, `--log-level`).
2. **Loads crew config** from YAML using `MatrixCrewConfig.from_yaml()`.
3. **Initializes BotManager** with 3 pre-defined agents:
   - **Financial Analyst** (`chatbot_id: "finance-analyst"`) — uses OpenAI/Anthropic, has finance tools.
   - **Research Assistant** (`chatbot_id: "web-researcher"`) — uses web search tools.
   - **General Assistant** (`chatbot_id: "general-bot"`) — general-purpose Q&A.
4. **Creates MatrixCrewTransport** from config.
5. **Starts the crew** using async context manager.
6. **Runs until SIGINT/SIGTERM** with graceful shutdown.

Include comprehensive docstring at the top explaining:
- What the script does.
- Prerequisites (Synapse/Dendrite, AS registration).
- How to run it.
- Expected behavior in each room.

```python
"""
Matrix Multi-Agent Crew Example
================================
Launches a crew of 3 agents on a Matrix homeserver:

1. Financial Analyst  — @analyst    — dedicated room + general room
2. Research Assistant  — @researcher — dedicated room + general room
3. General Assistant   — @assistant  — general room only (default handler)

Architecture:
  - Each agent uses a virtual MXID via the Matrix Application Service protocol
  - The coordinator bot maintains a pinned status board in the general room
  - Messages are routed by @mention in the general room
  - Messages in dedicated rooms go directly to that agent

Prerequisites:
  1. A Matrix homeserver (Synapse or Dendrite)
  2. Application Service registration (use registration.py to generate)
  3. Rooms created for general + each agent
  4. Environment variables set (see matrix_crew.yaml)

Usage:
    export MATRIX_HOMESERVER_URL=https://matrix.example.com
    export MATRIX_SERVER_NAME=example.com
    export MATRIX_AS_TOKEN=<your-as-token>
    export MATRIX_HS_TOKEN=<your-hs-token>
    python matrix_crew_example.py --config matrix_crew.yaml
"""
```

### matrix_crew.yaml

Example YAML config (same as spec section 3.1) with:
- Env var placeholders for secrets.
- 3 agents with different skills and dedicated rooms.
- Sensible defaults (streaming on, typing on, pinned registry on).

### MATRIX_CREW_GUIDE.md

Extensive documentation covering:

#### 1. Overview
- What is a Matrix multi-agent crew.
- Architecture diagram (from spec).
- Comparison with Telegram crew.

#### 2. Prerequisites
- Matrix homeserver setup (Synapse recommended).
- Creating rooms (general + per-agent).
- Generating Application Service registration (using `parrot/integrations/matrix/registration.py`).
- Registering the AS with the homeserver.

#### 3. Configuration Reference
- Full YAML config reference with all fields documented.
- Per-agent entry fields.
- Environment variable substitution.
- Example configs for different scenarios (minimal, full, large crew).

#### 4. Architecture Deep Dive
- Room topology diagram.
- Message flow for shared room (with @mention).
- Message flow for dedicated room.
- Status board lifecycle.
- Component interaction diagram.

#### 5. Agent Setup
- Defining agents in BotManager.
- Configuring skills and tags.
- Setting up dedicated rooms.
- Avatar and display name configuration.

#### 6. Running the Crew
- Starting the example script.
- Verifying agents are online (status board).
- Testing @mention routing.
- Testing dedicated room conversations.
- Monitoring logs.

#### 7. Advanced Usage
- Adding new agents to a running crew.
- Custom routing (tags, regex patterns).
- Inter-agent communication via A2A transport.
- Integrating with AgentCrew for complex workflows.
- File handling and document processing.

#### 8. Production Deployment
- Reverse proxy setup (nginx).
- TLS configuration.
- Monitoring and alerting.
- Scaling considerations.
- Backup and recovery.

#### 9. Troubleshooting
- Common errors and solutions.
- Debug logging.
- Homeserver connectivity issues.
- Agent registration failures.

## Acceptance Criteria

- [ ] `matrix_crew_example.py` is a complete, runnable script with comprehensive docstring.
- [ ] `matrix_crew.yaml` is a valid, well-commented YAML config.
- [ ] `MATRIX_CREW_GUIDE.md` is extensive (1500+ lines) covering all 9 sections.
- [ ] Example demonstrates 3 agents with per-agent rooms + shared general room.
- [ ] Documentation includes architecture diagrams, message flow, and production guidance.
- [ ] All code in the example follows AI-Parrot conventions (async, type hints, logging).
