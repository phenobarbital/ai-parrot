"""Agent lifecycle adapter; stores retain ownership of persistence and dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryContext

from .factory import create_memory_manager
from .models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope

if TYPE_CHECKING:
    from parrot.memory.dream.service import BrainService


class AgentMemoryMixin:
    """Integrate independently enabled persistent-memory capabilities with a host agent."""

    enable_episodic_memory: bool = False
    enable_user_memory: bool = False
    enable_brain: bool = False
    agent_memory_config: AgentMemoryConfig | dict[str, Any] | None = None
    brain_service: BrainService | None = None

    _memory_manager: UnifiedMemoryManager | None = None
    _resolved_agent_memory_config: AgentMemoryConfig | None = None
    _brain_started: bool = False
    _memory_tool_names: tuple[str, ...] = ()

    async def configure(self, app: Any = None) -> None:
        """Await host setup, respect configure skips, and initialize owned resources once.

        Args:
            app: Optional host application passed through the cooperative MRO.
        """
        await super().configure(app)
        if getattr(self, "configure_skipped", False):
            return

        config = self._resolve_agent_memory_config()
        manager = self._memory_manager
        if manager is not None and self._resolved_agent_memory_config != config:
            await self._release_memory_resources(manager)
            manager = None

        if manager is None:
            namespace = MemoryNamespace(
                tenant_id=str(getattr(self, "tenant_id", None) or "default"),
                agent_id=str(getattr(self, "name", None) or self.__class__.__name__),
            )
            manager = await create_memory_manager(config, namespace=namespace)

        try:
            await manager.configure()
            await self._configure_brain(config, manager)
            self._register_memory_tools(manager)
        except BaseException:
            try:
                await self._release_memory_resources(manager)
            except BaseException as cleanup_error:
                logger = getattr(self, "logger", None)
                if logger is not None:
                    logger.warning("memory rollback failed: %s", type(cleanup_error).__name__)
            raise

        self._memory_manager = manager
        self._resolved_agent_memory_config = config

    async def prepare_memory(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext:
        """Return one scoped supplementary block without loading conversation history.

        Args:
            query: Current user query.
            scope: Trusted request-local memory scope.

        Returns:
            The assembled supplementary memory context, or an empty context when the
            facade has no configured manager.
        """
        manager = self._memory_manager
        if manager is None:
            budget = (
                self._resolved_agent_memory_config.max_context_tokens
                if self._resolved_agent_memory_config is not None
                else AgentMemoryConfig().max_context_tokens
            )
            return MemoryContext(tokens_budget=budget)
        return await manager.prepare_context(query, scope=scope)

    async def complete_memory(self, event: MemoryEvent) -> None:
        """Route exactly one completed invocation event to its owning store.

        Args:
            event: Validated completed invocation event.
        """
        manager = self._memory_manager
        if manager is not None:
            self._bind_extraction_client(manager)
            await manager.record_event(event)

    async def cleanup(self) -> None:
        """Stop the brain service and drain owned writes before host resource cleanup."""
        first_error: BaseException | None = None
        brain = self.brain_service

        if brain is not None and self._brain_started:
            try:
                await brain.stop()
            except BaseException as exc:
                first_error = exc
            else:
                self._brain_started = False

        manager = self._memory_manager
        if manager is not None:
            try:
                await manager.cleanup()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
            else:
                self._memory_manager = None
                self._resolved_agent_memory_config = None
                self._unregister_memory_tools()

        try:
            await super().cleanup()
        except BaseException as exc:
            if first_error is None:
                first_error = exc

        if first_error is not None:
            raise first_error

    def _register_memory_tools(self, manager: UnifiedMemoryManager) -> None:
        """Register the agent-facing episodic tools once, only when this host has a tool manager and an episodic store."""
        tool_manager = getattr(self, "tool_manager", None)
        if self._memory_tool_names or tool_manager is None or getattr(manager, "episodic", None) is None:
            return
        from parrot.memory.episodic.tools import EpisodicMemoryToolkit

        toolkit = EpisodicMemoryToolkit(store=manager.episodic, namespace=manager.namespace)
        names: list[str] = []
        for tool in toolkit.get_tools():
            tool_manager.register_tool(tool)
            names.append(tool.name)
        self._memory_tool_names = tuple(names)

    def _unregister_memory_tools(self) -> None:
        """Remove the tools this mixin registered so a reconfigured or closed store is never left bound to them."""
        tool_manager = getattr(self, "tool_manager", None)
        if tool_manager is not None:
            for name in self._memory_tool_names:
                tool_manager.unregister_tool(name)
        self._memory_tool_names = ()

    def _bind_extraction_client(self, manager: UnifiedMemoryManager) -> None:
        """Give user-knowledge extraction the host's current LLM client (spec step 5: AbstractClient)."""
        config = getattr(manager, "config", None)
        if not getattr(config, "enable_user_memory", False):
            return
        get_client = getattr(self, "get_client", None)
        if not callable(get_client):
            return
        try:
            client = get_client()
        except Exception as exc:  # noqa: BLE001 - extraction is optional and must not fail the completed response
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("memory extraction client unavailable: %s", type(exc).__name__)
            return
        if client is not None:
            manager.extraction_client = client

    def _resolve_agent_memory_config(self) -> AgentMemoryConfig:
        """Resolve defaults, subclass policy, explicit config, then instance overrides."""
        values: dict[str, Any] = {}
        field_names = AgentMemoryConfig.model_fields

        for owner in reversed(type(self).__mro__):
            if owner in {AgentMemoryMixin, object}:
                continue
            for name in field_names:
                if name in owner.__dict__:
                    values[name] = owner.__dict__[name]

        explicit = self.agent_memory_config
        if explicit is not None:
            if isinstance(explicit, AgentMemoryConfig):
                values.update(explicit.model_dump(include=explicit.model_fields_set))
            elif isinstance(explicit, dict):
                values.update(explicit)
            else:
                raise ValueError(
                    "invalid_configuration: agent_memory_config must be AgentMemoryConfig, a mapping, or None"
                )

        for name in field_names:
            if name in self.__dict__:
                values[name] = self.__dict__[name]

        return AgentMemoryConfig(**values)

    async def _configure_brain(self, config: AgentMemoryConfig, manager: UnifiedMemoryManager) -> None:
        """Attach and start the injected or lazily available sibling brain service."""
        if not config.enable_brain:
            return

        service = self.brain_service
        if service is None:
            try:
                from parrot.memory.dream.service import BrainService
            except ImportError as exc:
                raise ValueError("invalid_configuration: brain service is unavailable") from exc

            if manager.episodic is None:
                raise ValueError("invalid_configuration: brain service requires episodic memory")
            service = BrainService(
                agent_id=str(getattr(self, "name", None) or self.__class__.__name__),
                episodic_store=manager.episodic,
            )
            self.brain_service = service

        required_methods = ("start", "stop", "search", "forget_derived")
        if any(not callable(getattr(service, method, None)) for method in required_methods):
            raise ValueError("invalid_configuration: brain service does not satisfy the public contract")

        manager.brain_service = service
        if not self._brain_started:
            try:
                await service.start()
            except BaseException:
                try:
                    await service.stop()
                except BaseException as cleanup_error:
                    logger = getattr(self, "logger", None)
                    if logger is not None:
                        logger.warning("brain startup rollback failed: %s", type(cleanup_error).__name__)
                raise
            self._brain_started = True

    async def _release_memory_resources(self, manager: UnifiedMemoryManager) -> None:
        """Unwind partially initialized resources without hiding cancellation."""
        self._unregister_memory_tools()
        first_error: BaseException | None = None
        brain = self.brain_service
        if brain is not None and self._brain_started:
            try:
                await brain.stop()
            except BaseException as exc:
                first_error = exc
            else:
                self._brain_started = False

        try:
            await manager.cleanup()
        except BaseException as exc:
            if first_error is None:
                first_error = exc

        if self._memory_manager is manager:
            self._memory_manager = None
            self._resolved_agent_memory_config = None
        if first_error is not None:
            raise first_error
