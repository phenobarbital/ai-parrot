---
type: Wiki Entity
title: A2AClient
id: class:parrot.a2a.client.A2AClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for communicating with remote A2A agents.
---

# A2AClient

Defined in [`parrot.a2a.client`](../summaries/mod:parrot.a2a.client.md).

```python
class A2AClient
```

Client for communicating with remote A2A agents.

Example:
    async with A2AClient("https://remote-agent:8080") as client:
        # Discover agent
        card = await client.discover()
        print(f"Connected to: {card.name}")

        # Send message
        task = await client.send_message("Hello!")
        print(task.artifacts[0].parts[0].text)

        # Stream response
        async for chunk in client.stream_message("Explain quantum computing"):
            print(chunk, end="", flush=True)

## Methods

- `async def connect(self, session: Optional[aiohttp.ClientSession]=None) -> None` — Establish connection and discover remote agent.
- `async def disconnect(self) -> None` — Close the connection.
- `def agent_card(self) -> Optional[AgentCard]` — Get the cached agent card.
- `def is_connected(self) -> bool`
- `async def discover(self) -> AgentCard` — Fetch the remote agent's card.
- `def get_skills(self) -> List[AgentSkill]` — Get available skills from the remote agent.
- `def get_skill(self, skill_id: str) -> Optional[AgentSkill]` — Get a specific skill by ID.
- `async def send_message(self, content: str, *, context_id: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> Task` — Send a message to the remote agent and wait for response.
- `async def stream_message(self, content: str, *, context_id: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> AsyncIterator[str]` — Send a message and stream the response.
- `async def invoke_skill(self, skill_id: str, params: Optional[Dict[str, Any]]=None, *, context_id: Optional[str]=None) -> Any` — Invoke a specific skill on the remote agent.
- `async def get_task(self, task_id: str) -> Task` — Get a task by ID.
- `async def list_tasks(self, context_id: Optional[str]=None, status: Optional[str]=None, page_size: int=50) -> List[Task]` — List tasks with optional filtering.
- `async def cancel_task(self, task_id: str) -> Task` — Cancel a running task.
- `async def create_push_config(self, task_id: str, url: str, *, config_id: str='', authentication: Optional[Dict[str, Any]]=None, metadata: Optional[Dict[str, Any]]=None) -> TaskPushNotificationConfig` — Register a push-notification webhook config for a task.
- `async def get_push_config(self, task_id: str, config_id: str) -> TaskPushNotificationConfig` — Fetch a single push-notification config.
- `async def list_push_configs(self, task_id: str) -> List[TaskPushNotificationConfig]` — List all push-notification configs registered for a task.
- `async def delete_push_config(self, task_id: str, config_id: str) -> bool` — Delete a push-notification config; returns True on success.
- `async def rpc_call(self, method: str, params: Optional[Dict[str, Any]]=None) -> Any` — Make a JSON-RPC call to the remote agent.
