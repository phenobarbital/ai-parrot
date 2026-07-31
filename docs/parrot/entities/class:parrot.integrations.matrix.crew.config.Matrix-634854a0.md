---
type: Wiki Entity
title: MatrixCrewConfig
id: class:parrot.integrations.matrix.crew.config.MatrixCrewConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Root configuration for a Matrix multi-agent crew.
---

# MatrixCrewConfig

Defined in [`parrot.integrations.matrix.crew.config`](../summaries/mod:parrot.integrations.matrix.crew.config.md).

```python
class MatrixCrewConfig(BaseModel)
```

Root configuration for a Matrix multi-agent crew.

Attributes:
    homeserver_url: Matrix homeserver URL.
    server_name: Server domain name (e.g. "example.com").
    as_token: Application Service token.
    hs_token: Homeserver token.
    bot_mxid: Coordinator bot MXID.
    general_room_id: Shared room for all agents.
    agents: Mapping of agent_name to MatrixCrewAgentEntry.
    appservice_port: AS HTTP listener port.
    pinned_registry: Whether to pin the status board in the general room.
    typing_indicator: Whether to show typing while processing.
    streaming: Whether to use edit-based streaming.
    unaddressed_agent: Default agent for unmentioned messages.
    max_message_length: Chunk responses beyond this length.
    collaborative: Optional collaborative session configuration.

## Methods

- `def validate_summarizer_agent(self) -> 'MatrixCrewConfig'` — Ensure summarizer_agent references a known agent in the agents dict.
- `def from_yaml(cls, path: str) -> 'MatrixCrewConfig'` — Load configuration from a YAML file with ``${ENV_VAR}`` substitution.
