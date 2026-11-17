"""Agent lifecycle adapter; stores retain ownership of persistence and dynamics."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryContext

from .factory import create_memory_manager
from .models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope

if TYPE_CHECKING:
    from parrot.memory.dream.service import BrainService
    from parrot.memory.user.store import EvidenceTenantResolver


class AgentMemoryMixin:
    """Integrate independently enabled persistent-memory capabilities with a host agent."""

    enable_episodic_memory: bool = False
    enable_user_memory: bool = False
    enable_brain: bool = False
    agent_memory_config: AgentMemoryConfig | dict[str, Any] | None = None
    brain_service: BrainService | None = None

    memory_extraction_client_factory: Callable[[], Any] | None = None
    memory_evidence_tenant_resolver: EvidenceTenantResolver | None = None

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
            factory_options: dict[str, Any] = {}
            if self.memory_evidence_tenant_resolver is not None:
                factory_options["evidence_tenant_resolver"] = self.memory_evidence_tenant_resolver
            manager = await create_memory_manager(config, namespace=namespace, **factory_options)

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
        self._bind_skill_registry(manager)
        return await manager.prepare_context(query, scope=scope)

    async def complete_memory(self, event: MemoryEvent) -> None:
        """Route exactly one completed invocation event to its owning store.

        Args:
            event: Validated completed invocation event.
        """
        manager = self._memory_manager
        if manager is None:
            return
        self._bind_extraction_client(manager)
        self._bind_skill_registry(manager)
        if event.kind == "response" and (
            getattr(manager, "extraction_client_factory", None) is not None
            or getattr(manager, "extraction_client", None) is not None
        ):
            # User extraction is a full provider round trip; it must not delay the answer. The task is
            # owned here and drained by cleanup()/_release_memory_resources().
            task = asyncio.ensure_future(self._record_in_background(manager, event))
            tasks = self.__dict__.setdefault("_memory_write_tasks", set())
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return
        await manager.record_event(event)

    async def _record_in_background(self, manager: UnifiedMemoryManager, event: MemoryEvent) -> None:
        """Record one completed event, logging (never raising) a failure of the detached write."""
        try:
            await manager.record_event(event)
        except Exception as exc:  # noqa: BLE001 - a detached write has no caller to report to
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("background memory write failed: %s", type(exc).__name__)

    async def _drain_memory_writes(self) -> None:
        """Wait for every owned background write; a cancelled caller still lets them finish."""
        tasks = self.__dict__.get("_memory_write_tasks")
        if not tasks:
            return
        pending = asyncio.ensure_future(asyncio.gather(*list(tasks), return_exceptions=True))
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            await asyncio.shield(pending)
            raise

    def _bind_skill_registry(self, manager: UnifiedMemoryManager) -> None:
        """Give skill recall the host's skill registry when relevant skills are enabled."""
        config = getattr(manager, "config", None)
        if not getattr(config, "enable_skills", False) or getattr(manager, "skills", None) is not None:
            return
        registry = getattr(self, "_skill_registry", None)
        if registry is not None:
            manager.skills = registry

    async def cleanup(self) -> None:
        """Stop the brain service and drain owned writes before host resource cleanup."""
        first_error: BaseException | None = None
        try:
            await self._drain_memory_writes()
        except BaseException as exc:
            first_error = exc
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
        """Bind construction once; extraction never borrows the response client's session."""
        config = getattr(manager, "config", None)
        if not getattr(config, "enable_user_memory", False):
            return
        if getattr(manager, "extraction_client_factory", None) is not None:
            return
        factory = self.memory_extraction_client_factory
        llm_config = getattr(self, "_llm_config", None)
        if factory is None and llm_config is not None and llm_config.client_instance is None:
            client_class = llm_config.client_class
            if client_class is not None:
                options = dict(llm_config.extra)
                options.update(model=llm_config.model, temperature=0.0, max_tokens=1024)
                options.pop("tool_manager", None)
                redaction = getattr(self, "enable_redaction", False)

                def factory() -> Any:
                    """Construct an independent client from the resolved host configuration."""
                    client = client_class(**options)
                    client.enable_redaction = redaction
                    return client

        if factory is None:
            # Custom live instances cannot safely be copied or reconstructed without their owner's factory.
            if not getattr(manager, "extraction_client", None) and not self.__dict__.get("_extraction_warning"):
                logger = getattr(self, "logger", None)
                if logger is not None:
                    logger.warning("user memory extraction requires memory_extraction_client_factory for a live client")
                self._extraction_warning = True
            return
        primary_client = getattr(self, "_llm", None)

        def owned_client() -> Any:
            """Reject factories that return the live response client before entering it."""
            client = factory()
            if client is None or client is primary_client:
                raise ValueError("memory extraction requires an independent client")
            return client

        manager.extraction_client_factory = owned_client

    def _resolve_agent_memory_config(self) -> AgentMemoryConfig:
        """Resolve defaults, subclass policy, explicit config, then instance overrides."""
        values: dict[str, Any] = {}
        field_names = AgentMemoryConfig.model_fields

        attribute_names = {"enable_episodic_memory", "enable_user_memory", "enable_brain"}
        for owner in reversed(type(self).__mro__):
            if owner is AgentMemoryMixin or not issubclass(owner, AgentMemoryMixin):
                continue
            for name in field_names:
                if name in owner.__dict__:
                    value = owner.__dict__[name]
                    if callable(value) or hasattr(value, "__get__"):
                        continue
                    attribute_names.add(name)
                    values[name] = value

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

        for name in attribute_names:
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
        try:
            await self._drain_memory_writes()
        except BaseException as exc:
            first_error = exc
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
