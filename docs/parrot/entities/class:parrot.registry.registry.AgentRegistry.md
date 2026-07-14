---
type: Wiki Entity
title: AgentRegistry
id: class:parrot.registry.registry.AgentRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Central registry for managing Bo/Agent discovery and registration.
---

# AgentRegistry

Defined in [`parrot.registry.registry`](../summaries/mod:parrot.registry.registry.md).

```python
class AgentRegistry
```

Central registry for managing Bo/Agent discovery and registration.

This class maintains a registry of all discovered agents and provides
methods for discovering, validating, and instantiating them.

- register(): programmatic registration
- register_agent decorator: declarative registration on class definition

We can use several strategies for discovery:
- decorators to mark classes for auto-registration.
- Configuration-Based Discovery, use a YAML config to define agents.

Decorator Usage:
    @register_agent(name="MySpecialAgent", priority=10)
    class MyAgent(AbstractBot):
        pass

# Programmatic registration
    agent_registry.register("CustomAgent", CustomAgentClass)

Configuration agents.yaml:
agents:
  - name: "ReportGenerator"
    class_name: "ReportGeneratorAgent"
    module: "agents.reporting"
    enabled: true
    config:
      templates_dir: "./templates"
  - name: "DataAnalyzer"
    class_name: "DataAnalyzerAgent"
    module: "agents.analysis"
    enabled: true

# Get instances
    agent = await agent_registry.get_instance("MyAgent")

## Methods

- `def evaluator(self) -> Any` — Return the PBAC evaluator, or None if not configured.
- `def setup(self, app: Any) -> None` — Store aiohttp Application reference for PDP policy registration.
- `def register_db_bot_policies(self, name: str, permissions: 'dict | list | None') -> int` — Register policies for a DB-loaded bot into the shared ``PolicyEvaluator``.
- `def get_bot_instance(self, name: str) -> Optional[AbstractBot]` — Get a cached bot instance by name (sync, returns None if not yet instantiated).
- `def get_metadata(self, name: str) -> Optional[BotMetadata]`
- `def register(self, name: str, factory: Type[AbstractBot], *, singleton: bool=False, tags: Optional[Iterable[str]]=None, priority: int=0, dependencies: Optional[List[str]]=None, replace: bool=False, at_startup: bool=False, startup_config: Optional[Dict[str, Any]]=None, bot_config: Optional['BotConfig']=None, **kwargs: Any) -> None` — Register a bot class with the registry.
- `def register_instance(self, name: str, instance: AbstractBot, *, tags: Optional[Iterable[str]]=None, priority: int=0, replace: bool=False) -> None` — Register a pre-built agent instance.
- `def has(self, name: str) -> bool`
- `def get_metadata(self, name: str) -> Optional[BotMetadata]` — Return the :class:`BotMetadata` for ``name`` or ``None`` if absent.
- `async def get_instance(self, name: str, request: Optional[web.Request]=None, **kwargs) -> Optional[AbstractBot]` — Get an instance of a registered bot.
- `def load_config(self) -> List[BotConfig]` — Load bot configuration from YAML file.
- `def discover_config_agents(self) -> List[BotMetadata]` — Register agents from configuration file.
- `def create_agent_factory(self, config: BotConfig) -> AgentFactory` — Create a factory function that instantiates an agent from BotConfig.
- `def load_agent_definitions(self, definitions_dir: Optional[Path]=None) -> int` — Scan directory for YAML agent definitions and register them.
- `def create_agent_definition(self, config: BotConfig, category: str='general') -> Path` — Save a BotConfig as a YAML definition file.
- `def delete_factory_agent(self, name: str) -> tuple[bool, str]` — Delete a factory-created agent: remove its YAML file and unregister.
- `async def load_modules(self) -> int` — Dynamically import all Python modules from every discovery directory.
- `def register_bot_decorator(self, *, name: Optional[str]=None, priority: int=0, dependencies: Optional[List[str]]=None, singleton: bool=False, at_startup: bool=False, startup_config: Optional[Dict[str, Any]]=None, tags: Optional[Iterable[str]]=None, **kwargs)` — Decorator to register an AbstractBot subclass.
- `def list_bots_by_priority(self) -> List[BotMetadata]` — Get all registered bots sorted by priority (highest first).
- `def get_bots_by_tag(self, tag: str) -> List[BotMetadata]` — Get all bots that have a specific tag.
- `def clear_registry(self) -> None` — Clear all registered bots. Useful for testing.
- `def get_registration_info(self) -> Dict[str, Any]` — Get detailed information about the registry state.
- `async def instantiate_startup_agents(self, app: Optional[Any]=None, **kwargs: Any) -> Dict[str, Any]` — Create instances for agents marked at_startup=True (implies singleton).
