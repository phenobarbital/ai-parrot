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
from types import ModuleType
import importlib
import inspect
from dataclasses import dataclass, field
import yaml
import hashlib
from navconfig.logging import logging
from navconfig import BASE_DIR
from ..bots.abstract import AbstractBot


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
    _instance: Optional[AbstractBot] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self):
        """Validate bot metadata after creation."""
        if not issubclass(self.factory, AbstractBot):
            raise ValueError(
                f"Bot {self.name} must inherit from AbstractBot"
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
            # Create new instance
            instance = self.factory(name=self.name, **merged_kwargs)
            if not isinstance(instance, AbstractBot):
                raise ValueError(
                    f"Factory for {self.name} returned {type(instance)!r}, expected AbstractBot."
                )
            # Configure instance if needed:
            if not self.at_startup:
                await instance.configure()
            # Store instance if singleton
            if self.singleton:
                self._instance = instance

            return instance

@dataclass
class BotConfig:
    """Configuration for the bot in config-based discovery."""
    name: str
    class_name: str
    module: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    tags: Optional[Set[str]] = field(default_factory=set)
    singleton: bool = False
    at_startup: bool = False
    startup_config: Dict[str, Any] = field(default_factory=dict)
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
        self.logger.notice(
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
        **kwargs: Any
    ) -> None:
        """
        Register a bot class with the registry.

        This is the core registration method that both decorator and config-based
        registration ultimately call.

        Args:
            name: Unique name for the bot
            factory: Bot class (subclass of AbstractBot)
            singleton: Whether to enforce singleton instance
            tags: Optional tags for categorization
            priority: Registration priority (higher = earlier)
            dependencies: List of required dependencies
            replace: Whether to replace an existing registration
            startup_config: Configuration to use during startup instantiation
            **kwargs: Additional metadata
        """
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
            for agent_data in config_data.get('agents', []):
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
        for metadata in startup_agents:  # También cambié "meta" a "metadata" para claridad
            try:
                instance = await metadata.get_instance(**kwargs)
                if callable(getattr(instance, 'configure', None)):
                    await instance.configure(app)
                results[metadata.name] = {  # Usa metadata.name aquí
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
