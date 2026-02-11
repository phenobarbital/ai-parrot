# agents/registry.py
"""
Agent Auto-Registration System for AI-Parrot.

This module provides multiple approaches for automatically discovering
and registering agents from the agents/ directory.
"""
from __future__ import annotations
import sys
import asyncio
from typing import Dict, Iterable, List, Type, Set, Union, Optional, Any, Protocol
from pathlib import Path
import hashlib
from types import ModuleType
import importlib
import inspect
from dataclasses import dataclass, field
import yaml
try:
    from parrot import yaml_rs
    yaml = yaml_rs
except ImportError:
    pass
from navconfig.logging import logging
from navconfig import BASE_DIR
from pydantic import BaseModel, Field
from ..bots.abstract import AbstractBot
from ..mcp import MCPServerConfig
from ..stores.models import StoreConfig
from ..models.basic import ModelConfig, ToolConfig
from ..conf import AGENTS_DIR


class AgentFactory(Protocol):
    """Protocol for agent factory callable."""
    def __call__(self, **kwargs: Any) -> AbstractBot: ...


@dataclass(slots=True)
class BotMetadata:
    """
    Metadata about a discovered Bot or Agent.

    This class holds information about agents found during discovery,
    making it easier to manage and validate them before registration.
    """
    name: str
    factory: Union[Type[AbstractBot], AgentFactory]
    module_path: str
    file_path: Path
    singleton: bool = False
    tags: Optional[Set[str]] = field(default_factory=set)
    priority: int = 0
    at_startup: bool = False
    dependencies: List[str] = field(default_factory=list)
    startup_config: Dict[str, Any] = field(default_factory=dict)  # Config for startup instantiation
    bot_config: Optional[Any] = None  # Optional[BotConfig] – declarative agent configuration
    _instance: Optional[AbstractBot] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self):
        """Validate bot metadata after creation."""
        # Check if factory is a class (subclass of AbstractBot) or a callable (AgentFactory)
        is_class = inspect.isclass(self.factory) and issubclass(self.factory, AbstractBot)
        is_factory = callable(self.factory)

        if not (is_class or is_factory):
            raise ValueError(
                f"Bot {self.name} factory must be AbstractBot subclass or callable"
            )
        # If at_startup=True, automatically make it singleton
        if self.at_startup:
            self.singleton = True

    async def get_instance(self, *args, **kwargs) -> AbstractBot:
        """
        Get or create an instance of the bot.

        This implements lazy instantiation - instances are only created when needed.
        For singleton bots, the same instance is returned on subsequent calls.
        """
        # Singleton path
        if self.singleton and self._instance is not None:
            return self._instance

        async with self._lock:
            # Double-check pattern for singletons
            if self.singleton and self._instance is not None:
                return self._instance

            # Merge startup config with runtime kwargs
            merged_kwargs = {**self.startup_config, **kwargs}

            # Prevent duplicate argument error for 'name'
            if 'name' in merged_kwargs:
                merged_kwargs.pop('name')

            # --- Logic for handling new BotConfig attributes ---
            # 1. Tools handling
            # Extract lists
            tools_list = merged_kwargs.get('tools', [])
            toolkits_list = merged_kwargs.get('toolkits', [])
            mcp_servers_config = merged_kwargs.pop('mcp_servers', [])

            # If toolkits are present, we might want to pass them explicitly if the bot supports it
            # or merge them into 'tools' depending on how the Bot factory expects them.
            # Standard AbstractBot takes 'tools' list.
            if toolkits_list:
                # Append toolkits to tools if not already there?
                # Or pass as 'toolkits' kwarg if supported.
                # Let's pass as config to be safe if the Bot handles it,
                # otherwise extend tools if they are just strings.
                if 'toolkits' not in merged_kwargs:
                     merged_kwargs['toolkits'] = toolkits_list

            # 2. Model handling
            model_conf = merged_kwargs.get('model')
            if isinstance(model_conf, dict):
                client = model_conf.get('client', 'openai')
                model_name = model_conf.get('model', 'gpt-4')
                # Format: "client:model" - AbstractBot uses 'llm' for client usually.
                if 'llm' not in merged_kwargs:
                    merged_kwargs['llm'] = f"{client}:{model_name}"
                # Update model reference
                merged_kwargs['model'] = model_name

            # 3. System Prompt - already in merged_kwargs

            # 4. Vector Store
            vector_store_conf = merged_kwargs.pop('vector_store', None)

            # Create new instance
            try:
                if inspect.iscoroutinefunction(self.factory):
                    instance = await self.factory(name=self.name, **merged_kwargs)
                else:
                    instance = self.factory(name=self.name, **merged_kwargs)
                    if inspect.iscoroutine(instance):
                        instance = await instance
            except Exception as e:
                raise ValueError(f"Error creating instance for {self.name}: {e}")

            if not isinstance(instance, AbstractBot):
                raise ValueError(
                    f"Factory for {self.name} returned {type(instance)!r}, expected AbstractBot."
                )

            # --- Post-Instantiation Configuration ---

            # 5. MCP Servers
            if mcp_servers_config:
                server_configs = []
                for srv in mcp_servers_config:
                     try:
                         server_configs.append(MCPServerConfig(**srv))
                     except Exception as e:
                         logging.error(f"Invalid MCP config for {self.name}: {e}")

                if server_configs and hasattr(instance, 'setup_mcp_servers'):
                    await instance.setup_mcp_servers(server_configs)

            # 6. Vector Store
            if vector_store_conf:
                 try:
                     store_config = StoreConfig(**vector_store_conf)
                     if hasattr(instance, '_apply_store_config'):
                         instance._apply_store_config(store_config)
                         instance._use_vector = True
                 except Exception as e:
                     logging.error(f"Invalid Store config for {self.name}: {e}")

            # Configure instance if needed:
            if not self.at_startup:
                await instance.configure()
            # Store instance if singleton
            if self.singleton:
                self._instance = instance

            return instance

class BotConfig(BaseModel):
    """Configuration for the bot in config-based discovery."""
    name: str
    class_name: str
    module: str
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)
    # New attributes
    tools: Optional[ToolConfig] = Field(default=None)
    toolkits: List[str] = Field(default_factory=list)
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list)
    model: Optional[ModelConfig] = Field(default=None)
    system_prompt: Optional[Union[str, Dict[str, Any]]] = Field(default=None)
    vector_store: Optional[StoreConfig] = Field(default=None)

    tags: Optional[Set[str]] = Field(default_factory=set)
    singleton: bool = False
    at_startup: bool = False
    startup_config: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


class AgentRegistry:
    """
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
    """

    def __init__(
        self,
        agents_dir: Optional[Path] = None,
        *,
        extra_agent_dirs: Optional[Iterable[Path]] = None,
    ):
        self.logger = logging.getLogger('Parrot.AgentRegistry')
        # DEBUG: Check available methods
        # print(f"DEBUG: AgentRegistry methods: {[m for m in dir(self) if not m.startswith('__')]}")
        self.agents_dir = agents_dir or BASE_DIR / "agents"
        self._registered_agents: Dict[str, BotMetadata] = {}
        self._config_file: Optional[Path] = None
        self._discovery_paths: List[Path] = []

        # Ensure primary discovery directory exists
        primary_dir = self._prepare_discovery_dir(self.agents_dir)
        self._discovery_paths.append(primary_dir)

        self._extra_agent_dirs: List[Path] = []
        if extra_agent_dirs:
            for directory in extra_agent_dirs:
                prepared_dir = self._prepare_discovery_dir(directory)
                self._extra_agent_dirs.append(prepared_dir)
                self._discovery_paths.append(prepared_dir)
        # Create config file if it doesn't exist
        self._config_file: Optional[Path] = self.agents_dir / "agents.yaml"
        if not self._config_file.exists():
            self._config_file.write_text(
                "# Auto-generated agents configuration\nagents: []\n"
            )
        self.logger.info(
            f"AgentRegistry initialized with agents_dir={self.agents_dir}, config_file={self._config_file}"
        )

    def _prepare_discovery_dir(self, directory: Path) -> Path:
        """Ensure a discovery directory exists and is importable."""
        resolved = Path(directory).resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        init_file = resolved / "__init__.py"
        if not init_file.exists():
            init_file.write_text("# Auto-generated agents module")
        if str(resolved) not in sys.path:
            sys.path.append(str(resolved))
        return resolved

    def get_bot_instance(self, name: str) -> Optional[AbstractBot]:
        """Get an instantiated bot by name."""
        return self._registered_agents.get(name)

    def get_metadata(self, name: str) -> Optional[BotMetadata]:
        return self._registered_agents.get(name)

    def register(
        self,
        name: str,
        factory: Type[AbstractBot],
        *,
        singleton: bool = False,
        tags: Optional[Iterable[str]] = None,
        priority: int = 0,
        dependencies: Optional[List[str]] = None,
        replace: bool = False,
        at_startup: bool = False,
        startup_config: Optional[Dict[str, Any]] = None,
        bot_config: Optional["BotConfig"] = None,
        **kwargs: Any
    ) -> None:
        """Register a bot class with the registry."""
        if name in self._registered_agents and not replace:
            self.logger.warning(
                f"Bot {name} already registered, use replace=True to overwrite"
            )
            return

        if not issubclass(factory, AbstractBot):
            raise ValueError(
                f"Bot {name} must inherit from AbstractBot"
            )

        # Get module information
        module = inspect.getmodule(factory)
        module_path = module.__name__ if module else "unknown"
        file_path = Path(module.__file__) if module and module.__file__ else Path("unknown")

        if not startup_config:
            startup_config = {}
        merged_kwargs = {**startup_config, **kwargs}

        metadata = BotMetadata(
            name=name,
            factory=factory,
            module_path=module_path,
            file_path=file_path,
            singleton=singleton,
            at_startup=at_startup,
            startup_config=merged_kwargs or {},
            tags=set(tags or []),
            priority=priority,
            dependencies=dependencies or [],
            bot_config=bot_config,
        )

        self._registered_agents[name] = metadata
        self.logger.info(
            f"Registered bot: {name}"
        )

    def has(self, name: str) -> bool:
        return name in self._registered_agents

    async def get_instance(self, name: str, **kwargs) -> Optional[AbstractBot]:
        """
        Get an instance of a registered bot.

        This method handles lazy instantiation - bots are only created when needed.

        Args:
            name: Name of the bot to instantiate
            **kwargs: Additional arguments to pass to the bot constructor

        Returns:
            Bot instance or None if not found
        """
        if name not in self._registered_agents:
            self.logger.warning(f"Bot {name} not found in registry")
            return None

        metadata = self._registered_agents[name]
        try:
            instance = await metadata.get_instance(**kwargs)
            self.logger.debug(f"Retrieved instance for bot: {name}")
            return instance
        except Exception as e:
            self.logger.error(f"Failed to instantiate bot {name}: {str(e)}")
            return None

    def load_config(self) -> List[BotConfig]:
        """Load bot configuration from YAML file."""
        if not self._config_file or not self._config_file.exists():
            self.logger.debug(
                "No config file found, skipping config-based discovery"
            )
            return []

        try:
            with open(self._config_file, 'r') as f:
                config_data = yaml.safe_load(f)

            configs = []
            agents_list = config_data.get('agents', [])
            self.logger.debug(f"Loading {len(agents_list)} agents from config: {agents_list}")
            for agent_data in agents_list:
                try:
                    config = BotConfig(**agent_data)
                    if config.enabled:
                        configs.append(config)
                except Exception as e:
                    self.logger.error(
                        f"Invalid config entry: {agent_data}, error: {e}"
                    )
                    continue

            return configs

        except ImportError:
            self.logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return []
        except Exception as e:
            self.logger.error(f"Failed to load config: {str(e)}")
            return []

    def discover_config_agents(self) -> List[BotMetadata]:
        """
        Register agents from configuration file.

        This method loads the config file and registers all enabled agents.

        Returns:
            Number of agents successfully registered from config
        """
        configs = self.load_config()
        registered_count = 0

        for config in configs:
            if not config.enabled:
                continue

            try:
                # Import the module
                module = importlib.import_module(config.module)

                # Get the class
                agent_class = getattr(module, config.class_name)

                # Validate it's an AbstractBot subclass
                if not issubclass(agent_class, AbstractBot):
                    self.logger.error(
                        f"{config.class_name} is not an AbstractBot subclass"
                    )
                    continue

                # Register using core register method
                self.register(
                    name=config.name,
                    factory=agent_class,
                    singleton=config.singleton,
                    tags=config.tags,
                    priority=config.priority,
                    at_startup=config.at_startup,
                    startup_config=config.config,
                    bot_config=config,
                    replace=True
                )

                registered_count += 1
                self.logger.info(
                    f"Registered bot from config: {config.name}"
                )

            except Exception as e:
                self.logger.error(
                    f"Failed to load bot {config.name}: {str(e)}"
                )
                continue

        return registered_count

    def create_agent_factory(self, config: BotConfig) -> AgentFactory:
        """
        Create a factory function that instantiates an agent from BotConfig.
        Handles the translation from declarative config to AbstractBot arguments.
        """
        # Import module and class dynamically
        try:
            module = importlib.import_module(config.module)
            agent_class = getattr(module, config.class_name)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Could not load agent class {config.class_name} from {config.module}: {e}")

        async def factory(**kwargs) -> AbstractBot:
             # Merge startup_config with kwargs
            merged_args = {**config.startup_config, **kwargs}
            merged_args['name'] = config.name

            # 1. Handle System Prompt
            if config.system_prompt:
                # If it's a dict, we might need to process it, but AbstractBot expects str usually
                # or a template. If it's a dict, maybe we extract 'template'?
                # For now, assuming string or let AbstractBot handle it if it supports dict
                if isinstance(config.system_prompt, str):
                    merged_args['system_prompt'] = config.system_prompt
                elif isinstance(config.system_prompt, dict):
                     merged_args['system_prompt'] = config.system_prompt.get('template', '')
                     # Pass other keys as prompt vars?
                     merged_args.update(config.system_prompt)

            # 2. Handle ModelConfig
            if config.model:
                # Convert ModelConfig to llm args
                # "provider:model" format or objects
                merged_args['llm'] = f"{config.model.provider}:{config.model.model}"
                # We can also pass other params via kwargs or model_config
                # AbstractBot uses 'llm_kwargs' or direct args
                merged_args['temperature'] = config.model.temperature
                merged_args['max_tokens'] = config.model.max_tokens

            # 3. Handle Tools
            # AbstractBot expects 'tools' list in init
            tools_list = []
            if config.tools:
                 # Add direct tools (list of dicts or strings)
                 if config.tools.tools:
                     for tool_def in config.tools.tools:
                         if isinstance(tool_def, str):
                             tools_list.append(tool_def)
                         elif isinstance(tool_def, dict) and 'name' in tool_def:
                             tools_list.append(tool_def['name'])
                             # TODO: Handle detailed tool config if needed

            merged_args['tools'] = tools_list

            # 4. Handle Vector Store
            if config.vector_store:
                # Pass as vector_store_config or similar
                merged_args['vector_store_config'] = config.vector_store.dict() # Convert to dict

            # Instantiate
            bot = agent_class(**merged_args)

            # Post-init configuration

            # Handle MCP Servers from ToolConfig
            if config.tools and config.tools.mcp_servers:
                for mcp_conf in config.tools.mcp_servers:
                    try:
                        # Convert dict to MCPServerConfig
                        mcp_obj = MCPServerConfig(**mcp_conf)
                        await bot.add_mcp_server(mcp_obj)
                    except Exception as e:
                        self.logger.error(f"Failed to add MCP server to {config.name}: {e}")

            # Handle Toolkits
            if config.tools and config.tools.toolkits:
                # If the bot has a tool_manager, we can use it to load toolkits
                if hasattr(bot, 'tool_manager'):
                    for toolkit_name in config.tools.toolkits:
                        try:
                            # This assumes tool_manager has a way to load toolkits or we need to resolve them here
                            pass
                        except Exception as e:
                            self.logger.error(
                                f"Failed to load toolkit {toolkit_name} for {config.name}: {e}"
                            )

            return bot

        return factory

    def load_agent_definitions(self, definitions_dir: Optional[Path] = None) -> int:
        """
        Scan directory for YAML agent definitions and register them.
        """
        if not definitions_dir:
            definitions_dir = AGENTS_DIR.joinpath('agents')

        if not definitions_dir.exists():
            self.logger.debug(f"Agent definitions directory {definitions_dir} does not exist.")
            return 0

        count = 0
        for yaml_file in definitions_dir.rglob("*.yaml"):
            print(f"DEBUG: Found YAML file: {yaml_file}")
            try:
                # Load YAML
                content = yaml.safe_load(yaml_file.read_text())
                if not content:
                    continue

                # Check if it has 'agent' Section
                agent_def = content.get('agent')
                if not agent_def:
                    continue

                self.logger.debug(f"Loading agent definition from {yaml_file}: {agent_def}")

                # Construct BotConfig
                # We need to map YAML structure to BotConfig fields
                # YAML:
                # agent: {name, class_name, ...}
                # model: {provider, model, ...}
                # tools: { ... }

                bot_config_data = agent_def.copy()

                # Map 'model' section
                if 'model' in content:
                    bot_config_data['model'] = ModelConfig(**content['model'])

                # Map 'tools' section to ToolConfig
                if 'tools' in content:
                    bot_config_data['tools'] = ToolConfig(**content['tools'])

                # Map 'system_prompt'
                if 'system_prompt' in content:
                    bot_config_data['system_prompt'] = content['system_prompt']

                # Create BotConfig
                config = BotConfig(**bot_config_data)

                if not config.enabled:
                    continue

                # Create Factory
                factory = self.create_agent_factory(config)

                # Register
                self._registered_agents[config.name] = BotMetadata(
                    name=config.name,
                    factory=factory,
                    module_path=config.module,
                    file_path=yaml_file,
                    singleton=config.singleton,
                    at_startup=config.at_startup,
                    startup_config=config.config,
                    tags=config.tags,
                    priority=config.priority,
                    bot_config=config,
                )

                count += 1
                self.logger.info(
                    f"Loaded agent definition from {yaml_file}: {config.name}"
                )

            except Exception as e:
                self.logger.error(
                    f"Failed to load agent definition from {yaml_file}: {e}"
                )

        return count

    def create_agent_definition(self, config: BotConfig, category: str = "general") -> Path:
        """
        Save a BotConfig as a YAML definition file.
        """
        base_dir = AGENTS_DIR.joinpath('agents', category)
        base_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{config.name.lower()}.yaml"
        file_path = base_dir / filename

        # Construct YAML structure
        data = {
            "agent": {
                "name": config.name,
                "class_name": config.class_name,
                "module": config.module,
                "description": config.config.get('description', ''),
                "enabled": config.enabled,
                "version": "1.0.0"
            }
        }

        if config.model:
            data["model"] = config.model.dict()

        if config.tools:
             data["tools"] = config.tools.dict(exclude_none=True)

        if config.system_prompt:
             data["system_prompt"] = config.system_prompt

        with open(file_path, 'w') as f:
            yaml.dump(data, f)

        return file_path

    def _import_module_from_path(
        self,
        path: Path,
        *,
        base_dir: Optional[Path] = None,
        package_hint: str = "parrot.dynamic_agents",
    ) -> ModuleType:
        """
        Import a Python module from an arbitrary filesystem path.
        Ensures decorators run at import time.
        """
        base = (base_dir or self.agents_dir).resolve()
        resolved_path = path.resolve()
        try:
            rel = resolved_path.relative_to(base)
        except ValueError:
            rel = Path(resolved_path.name)
        rel_path = rel if isinstance(rel, Path) else Path(rel)
        module_suffix = ".".join(rel_path.with_suffix('').parts)
        if module_suffix:
            mod_name = f"{package_hint}.{module_suffix}"
        else:
            mod_name = package_hint

        spec = importlib.util.spec_from_file_location(mod_name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(
                f"Could not load spec for {path}"
            )

        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        self.logger.debug(
            f"Imported agent module: {mod_name} from {path}"
        )
        return module

    def _namespace_for_directory(self, directory: Path) -> str:
        digest = hashlib.md5(str(directory.resolve()).encode('utf-8')).hexdigest()
        return f"parrot.dynamic_agents.dir_{digest}"

    def _load_modules_from_directory(self, directory: Path) -> int:
        if not directory.exists() or not directory.is_dir():
            self.logger.debug(
                f"Agents directory {directory} does not exist, skipping"
            )
            return 0

        package_hint = self._namespace_for_directory(directory)
        module_files = list(directory.glob("*.py"))
        imported_count = 0

        for file_path in module_files:
            if file_path.name == "__init__.py":
                continue  # Skip __init__.py

            try:
                self._import_module_from_path(
                    file_path,
                    base_dir=directory,
                    package_hint=package_hint
                )
                imported_count += 1
            except Exception as e:
                self.logger.error(f"Failed to import {file_path}: {e}")
        return imported_count

    async def load_modules(self) -> int:
        """
        Dynamically import all Python modules from every discovery directory.

        This triggers any decorators in those modules to register agents.
        """
        total_imported = 0
        for directory in self._discovery_paths:
            total_imported += self._load_modules_from_directory(directory)

        self.logger.info(
            f"Discovered (decorator) agent modules: {total_imported} across {len(self._discovery_paths)} directories"
        )
        return total_imported

    def register_bot_decorator(
        self,
        *,
        name: Optional[str] = None,
        priority: int = 0,
        dependencies: Optional[List[str]] = None,
        singleton: bool = False,
        at_startup: bool = False,
        startup_config: Optional[Dict[str, Any]] = None,
        tags: Optional[Iterable[str]] = None,
        **kwargs
    ):
        """
        Decorator to register an AbstractBot subclass.

        This decorator immediately calls self.register() to register the agent,
        rather than storing it separately for later processing.

        Args:
            name: Agent name (defaults to class name)
            priority: Registration priority (higher = earlier)
            dependencies: List of required dependencies
            singleton: Whether to enforce singleton instance
            tags: Optional tags for categorization
            **kwargs: Additional registration parameters

        Usage:
            @register_agent(name="CriticalAgent", at_startup=True, startup_config={"db_pool_size": 10})
            class MyBot(AbstractBot):
                pass
        """
        def _decorator(cls: Type[AbstractBot]) -> Type[AbstractBot]:
            if not inspect.isclass(cls):
                raise TypeError("@register_agent can only be used on classes.")

            if not issubclass(cls, AbstractBot):
                raise TypeError("@register_agent can only be used on AbstractBot subclasses.")

            # Determine agent name
            bot_name = (name or cls.__name__).strip()

            _system_prompt = None
            _sp_raw = cls.__dict__.get('system_prompt')
            if isinstance(_sp_raw, (str, dict)):
                _system_prompt = _sp_raw

            _model_config = None
            _model_raw = cls.__dict__.get('model')
            if isinstance(_model_raw, str):
                _max_tokens = cls.__dict__.get('max_tokens', 8192)
                _temperature = cls.__dict__.get('temperature', 0.1)
                _model_config = ModelConfig(
                    provider='google',
                    model=_model_raw,
                    temperature=_temperature if isinstance(_temperature, (int, float)) else 0.1,
                    max_tokens=_max_tokens if isinstance(_max_tokens, int) else 8192,
                )

            _description = (cls.__doc__ or '').strip() or None

            _bot_config = BotConfig(
                name=bot_name,
                class_name=cls.__name__,
                module=cls.__module__,
                enabled=True,
                config=startup_config or {},
                model=_model_config,
                system_prompt=_system_prompt,
                singleton=singleton,
                at_startup=at_startup,
                startup_config=startup_config or {},
                tags=set(tags or []),
                priority=priority,
            )

            # Register immediately using the core register method
            self.register(
                name=bot_name,
                factory=cls,
                singleton=singleton,
                at_startup=at_startup,
                startup_config=startup_config,
                tags=tags,
                priority=priority,
                dependencies=dependencies,
                bot_config=_bot_config,
                **kwargs
            )

            # Mark the class with metadata for introspection
            cls._parrot_agent_metadata = self._registered_agents[bot_name]

            return cls

        return _decorator

    def list_bots_by_priority(self) -> List[BotMetadata]:
        """Get all registered bots sorted by priority (highest first)."""
        return sorted(
            self._registered_agents.values(),
            key=lambda x: x.priority,
            reverse=True
        )

    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:
        """Get all bots that have a specific tag."""
        return [
            metadata for metadata in self._registered_agents.values()
            if tag in metadata.tags
        ]

    def clear_registry(self) -> None:
        """Clear all registered bots. Useful for testing."""
        self._registered_agents.clear()
        self.logger.info("Registry cleared")

    def get_registration_info(self) -> Dict[str, Any]:
        """Get detailed information about the registry state."""
        return {
            "total_registered": len(self._registered_agents),
            "by_priority": {
                metadata.name: metadata.priority
                for metadata in self._registered_agents.values()
            },
            "by_tags": {
                tag: [name for name, metadata in self._registered_agents.items() if tag in metadata.tags]
                for tag in set().union(*(metadata.tags for metadata in self._registered_agents.values()))
            },
            "singletons": [
                name for name, metadata in self._registered_agents.items()
                if metadata.singleton
            ]
        }

    async def instantiate_startup_agents(self, app: Optional[Any] = None, **kwargs: Any) -> Dict[str, Any]:
        """
        Create instances for agents marked at_startup=True (implies singleton).
        """
        results = {}
        startup_agents = [bot for bot in self.list_bots_by_priority() if bot.at_startup]

        startup_agents.sort(
            key=lambda meta: meta.priority,
            reverse=True
        )
        for metadata in startup_agents:
            try:
                instance = await metadata.get_instance(**kwargs)
                if callable(getattr(instance, 'configure', None)):
                    await instance.configure(app)
                results[metadata.name] = {
                    "status": "success",
                    "instance": instance,
                    "instance_id": id(instance),
                    "priority": metadata.priority
                }
            except Exception as e:
                self.logger.error(
                    f"Failed startup instantiate {metadata.name}: {e}"
                )
                results[metadata.name] = {
                    "status": "error",
                    "error": str(e)
                }
        return results
