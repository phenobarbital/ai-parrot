# TASK-301 — Matrix Crew Transport Orchestrator

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: high
**Effort**: L
**Depends on**: TASK-296, TASK-297, TASK-298, TASK-299, TASK-300
**Parallel**: false
**Parallelism notes**: Top-level orchestrator importing all crew modules. Also updates __init__.py exports and IntegrationManager.

---

## Objective

Create `MatrixCrewTransport` — the top-level orchestrator that manages the full lifecycle of a Matrix multi-agent crew. Also update `parrot/integrations/matrix/crew/__init__.py` with all exports and extend `parrot/integrations/manager.py` to support `matrix_crew` configuration.

## Files to Create/Modify

- `parrot/integrations/matrix/crew/transport.py` — new file
- `parrot/integrations/matrix/crew/__init__.py` — update with all exports
- `parrot/integrations/matrix/__init__.py` — add crew subpackage exports
- `parrot/integrations/manager.py` — add matrix_crew startup support

## Implementation Details

### MatrixCrewTransport

```python
class MatrixCrewTransport:
    def __init__(self, config: MatrixCrewConfig) -> None:
        self._config = config
        self._appservice: MatrixAppService | None = None
        self._coordinator: MatrixCoordinator | None = None
        self._registry = MatrixCrewRegistry()
        self._wrappers: dict[str, MatrixCrewAgentWrapper] = {}
        self._room_to_agent: dict[str, str] = {}  # dedicated room → agent name
        self.logger = logging.getLogger(__name__)
```

### from_yaml(path: str) -> MatrixCrewTransport

Class method:
1. Call `MatrixCrewConfig.from_yaml(path)`.
2. Return `cls(config)`.

### start()

Initialization sequence:
1. **Create MatrixAppService** from config (homeserver_url, as_token, hs_token, server_name, appservice_port).
2. **Register virtual users**: For each agent in config, register the MXID via AppService.
3. **Build room-to-agent map**: Map each agent's `dedicated_room_id` → agent_name.
4. **Create MatrixCrewAgentWrapper** for each agent.
5. **Register agents in registry**: Create `MatrixAgentCard` for each, call `registry.register()`.
6. **Join agents to rooms**: Join each agent to `general_room_id` + their `dedicated_room_id`.
7. **Create and start coordinator**: `MatrixCoordinator(client, registry, general_room_id)`.
8. **Register event callback**: `appservice.on_room_message(self.on_room_message)`.
9. **Start AppService HTTP listener**.

### stop()

Graceful shutdown:
1. Stop coordinator.
2. Unregister agents from registry.
3. Stop AppService.

### on_room_message(room_id, sender, body, event_id)

Message routing logic:
1. **Ignore self**: Skip messages from any agent's virtual MXID or the coordinator.
2. **Dedicated room routing**: If `room_id` in `_room_to_agent`, route to that agent's wrapper.
3. **Mention routing**: Call `parse_mention(body, config.server_name)`. If a localpart matches an agent, route to that wrapper.
4. **Default agent**: If `config.unaddressed_agent` is set, route to that wrapper.
5. **Otherwise**: Ignore the message.

### Context Manager

```python
async def __aenter__(self) -> "MatrixCrewTransport":
    await self.start()
    return self

async def __aexit__(self, *exc) -> None:
    await self.stop()
```

### IntegrationManager Update

In `parrot/integrations/manager.py`, add support for `matrix_crew` config key:
```python
if "matrix_crew" in config:
    from parrot.integrations.matrix.crew import MatrixCrewTransport
    transport = MatrixCrewTransport.from_yaml(config["matrix_crew"])
    await transport.start()
    self.matrix_crew = transport
```

### crew/__init__.py Exports

```python
from .config import MatrixCrewConfig, MatrixCrewAgentEntry
from .registry import MatrixCrewRegistry, MatrixAgentCard
from .coordinator import MatrixCoordinator
from .crew_wrapper import MatrixCrewAgentWrapper
from .transport import MatrixCrewTransport
from .mention import parse_mention, format_reply, build_pill
```

## Acceptance Criteria

- [ ] `MatrixCrewTransport.start()` initializes AppService, registers agents, starts coordinator.
- [ ] `on_room_message()` routes by dedicated room, @mention, or default agent.
- [ ] `stop()` gracefully shuts down all components.
- [ ] `from_yaml()` loads config and creates transport.
- [ ] Context manager (`async with`) works for lifecycle.
- [ ] `crew/__init__.py` exports all public classes and functions.
- [ ] `parrot/integrations/matrix/__init__.py` updated with crew exports.
- [ ] `parrot/integrations/manager.py` supports `matrix_crew` config section.
