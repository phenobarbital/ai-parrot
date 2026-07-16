---
type: Wiki Entity
title: MatrixAppService
id: class:parrot.integrations.matrix.appservice.MatrixAppService
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matrix Application Service for AI-Parrot.
---

# MatrixAppService

Defined in [`parrot.integrations.matrix.appservice`](../summaries/mod:parrot.integrations.matrix.appservice.md).

```python
class MatrixAppService
```

Matrix Application Service for AI-Parrot.

Provides each registered agent with a virtual MXID and receives
events from the homeserver via HTTP push (no polling).

Usage::

    config = MatrixAppServiceConfig(
        as_token="...",
        hs_token="...",
        homeserver="http://localhost:8008",
        server_name="parrot.local",
        agent_mxid_map={"FinanceAgent": "parrot-finance"},
    )
    appservice = MatrixAppService(config)
    appservice.set_event_callback(my_handler)
    await appservice.start()

    # Each agent gets its own Matrix presence
    await appservice.register_agent("FinanceAgent", "Finance Agent")

    # Send a message as a specific agent
    await appservice.send_as_agent(
        "FinanceAgent", "!room:server", "Revenue is $1M"
    )

## Methods

- `async def start(self) -> None` — Start the Application Service HTTP server.
- `async def stop(self) -> None` — Stop the Application Service HTTP server.
- `def running(self) -> bool` — Whether the AS is currently running.
- `def bot_intent(self) -> IntentAPI` — Get the IntentAPI for the bot user.
- `async def register_agent(self, agent_name: str, displayname: Optional[str]=None) -> str` — Register an agent as a virtual Matrix user.
- `async def unregister_agent(self, agent_name: str) -> None` — Remove a virtual agent (leaves rooms, clears state).
- `async def ensure_agent_in_room(self, agent_name: str, room_id: str) -> None` — Join a virtual agent to a room.
- `def list_agents(self) -> Dict[str, str]` — Return mapping of registered agent_name → mxid.
- `async def send_as_agent(self, agent_name: str, room_id: str, message: str) -> str` — Send a message to a room as a specific agent.
- `async def send_formatted_as_agent(self, agent_name: str, room_id: str, body: str, formatted_body: str) -> str` — Send a formatted HTML message as a specific virtual agent.
- `async def send_as_bot(self, room_id: str, message: str) -> str` — Send a message as the bot user.
- `async def send_custom_event_as_agent(self, agent_name: str, room_id: str, event_type: str, content: dict) -> Optional[str]` — Send a custom Matrix event as a specific virtual agent.
- `async def send_reply_as_agent(self, agent_name: str, room_id: str, message: str, reply_to_event_id: str) -> str` — Send a reply-to message as a specific virtual agent.
- `async def send_reply_as_bot(self, room_id: str, message: str, reply_to_event_id: str) -> str` — Send a reply-to message as the bot user.
- `def set_event_callback(self, callback: EventCallback) -> None` — Set the callback for incoming room messages.
- `def set_custom_event_callback(self, callback: Callable) -> None` — Set the callback for incoming custom ``m.parrot.*`` events.
