"""RoostEndpoint — one per agent instance (FEAT-747 M11)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, Optional, Sequence

from . import squawk_bridge
from .audit import RoostAuditLedger
from .blackboard import Blackboard
from .carriers.base import Carrier, Undeliverable
from .directory import RoostAgentConfig
from .gating import Dispatch, DispatchDecision, GatingDispatcher, Handler
from .grant import GrantPolicy
from .messages import AgentAddress, FailureInfo, RoostMessage
from .performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from .protocols import ConversationBudget, ProtocolEngine, TerminalState
from .scoring import Award, BidScorer

if TYPE_CHECKING:
    from parrot.registry import AgentRegistry
    from parrot.tools.manager import ToolManager
    from parrot.tools.working_memory.tool import WorkingMemoryToolkit

WakeCallback = Callable[[RoostMessage, Dispatch], Awaitable[Optional[RoostMessage]]]


class RoostFailure(Exception):
    """A request completed with a typed Roost failure."""

    def __init__(self, failure: FailureInfo) -> None:
        super().__init__(f"{failure.code.value}: {failure.detail}")
        self.failure = failure


class RoostEndpoint:
    """Compose Roost transport, deterministic dispatch, and local agent integrations."""

    def __init__(
        self,
        *,
        agent_name: str,
        config: Optional[RoostAgentConfig],
        engine: ProtocolEngine,
        dispatcher: GatingDispatcher,
        carriers: Mapping[CarrierKind, Carrier],
        tool_manager: "ToolManager",
        blackboard: Optional[Blackboard] = None,
        ledger: Optional[RoostAuditLedger] = None,
        working_memory: Optional["WorkingMemoryToolkit"] = None,
        wake: Optional[WakeCallback] = None,
        registry: Optional["AgentRegistry"] = None,
        grant: Optional[GrantPolicy] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.agent_name, self.config, self.engine, self.dispatcher = agent_name, config, engine, dispatcher
        self.carriers, self.tool_manager, self.blackboard = dict(carriers), tool_manager, blackboard
        self.ledger = ledger or RoostAuditLedger()
        self.working_memory, self.wake, self.registry = working_memory, wake, registry
        self.grant = grant or GrantPolicy()
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._subs: list[tuple[Carrier, str]] = []
        self._metrics = {"messages_in": 0, "messages_out": 0, "wakes": 0, "not_understood": 0, "stored": 0}

    def address(self) -> AgentAddress:
        """Return this endpoint's configured transport address."""
        carrier = self.config.carrier if self.config else CarrierKind.IN_PROCESS
        return AgentAddress(name=self.agent_name, carrier=carrier)

    async def start(self) -> None:
        """Subscribe this endpoint's address (and capabilities) on every carrier."""
        if self._subs:
            return
        capabilities = self.config.capabilities if self.config is not None else ()
        for carrier in self.carriers.values():
            subscription_id = await carrier.subscribe(self.address(), self._on_message, capabilities=capabilities)
            self._subs.append((carrier, subscription_id))

    async def stop(self) -> None:
        """Unsubscribe and fail outstanding request waiters as cancelled."""
        for carrier, subscription_id in self._subs:
            await carrier.unsubscribe(subscription_id)
        self._subs.clear()
        failure = RoostFailure(FailureInfo(code=FailureCode.CANCELLED, detail="endpoint stopped"))
        for future in self._pending.values():
            if not future.done():
                future.set_exception(failure)
        self._pending.clear()

    async def _on_message(self, msg: RoostMessage) -> None:
        """Audit, dispatch, and execute an inbound Roost message."""
        self._metrics["messages_in"] += 1
        await self.ledger.record(msg, direction="served", self_name=self.agent_name)
        dispatch = self.dispatcher.dispatch(msg)
        for emitted in dispatch.emit:
            await self._send_reply(emitted)

        if dispatch.decision is DispatchDecision.IGNORE:
            return
        if dispatch.decision is DispatchDecision.NOT_UNDERSTOOD:
            self._metrics["not_understood"] += 1
            return
        if dispatch.decision is DispatchDecision.CLOSED:
            await self._resolve_pending(msg)
            return
        if dispatch.decision is DispatchDecision.RUN_TOOL:
            await self._run_tool(msg)
            return
        if dispatch.decision is DispatchDecision.STORE:
            if dispatch.handler is not None:
                await dispatch.handler(msg)
            await self._store(msg)
            await self._resolve_pending(msg)
            return
        if dispatch.decision is DispatchDecision.WAKE_LLM:
            self._metrics["wakes"] += 1
            if self.wake is not None:
                response = await self.wake(msg, dispatch)
                if response is not None:
                    await self._send_reply(response)
                    self.engine.charge(msg.conversation_id, int(getattr(response, "tokens", 0)))
            await self._resolve_pending(msg)
            return
        if dispatch.decision is DispatchDecision.BID_FROM_CONTRACT:
            bid = self.config.bid if self.config is not None else None
            if bid is not None:
                await self._send_reply(msg.reply(Performative.PROPOSE, content=bid))
            return
        if dispatch.decision is DispatchDecision.REPLAN:
            await self._resolve_pending(msg)

    async def _run_tool(self, msg: RoostMessage) -> None:
        """Run a deterministic serving tool through the manager's policy guard."""
        content = msg.content if isinstance(msg.content, dict) else {}
        tool_name = content.get("tool") or (msg.capability_filter or "").replace(".", "_")
        try:
            result = await self.tool_manager.execute_tool(
                tool_name,
                content,
                permission_context=squawk_bridge.resolve_authority(msg),
            )
        except Exception as exc:  # noqa: BLE001 — any tool error must become a typed failure, never a silent hang
            self.logger.warning("Roost tool %r failed for conversation %s: %s", tool_name, msg.conversation_id, exc)
            code = FailureCode.POLICY if isinstance(exc, PermissionError) else FailureCode.INTERNAL
            await self._send_reply(
                msg.reply(Performative.FAILURE, failure=FailureInfo(code=code, detail=f"{type(exc).__name__}: {exc}"))
            )
            return
        if msg.performative is Performative.REQUEST:
            await self._send_reply(msg.reply(Performative.AGREE))
        await self._send_reply(msg.reply(Performative.INFORM, content=result))

    async def _store(self, msg: RoostMessage) -> None:
        """Store inbound content in working memory without serializing native objects."""
        if self.working_memory is None:
            return
        await self.working_memory.store_result(
            key=f"roost:{msg.conversation_id}:{msg.message_id}",
            data=msg.content,
            data_type="auto",
            metadata={"performative": msg.performative.value, "sender": msg.sender.name},
        )
        self._metrics["stored"] += 1

    async def _resolve_pending(self, msg: RoostMessage) -> None:
        """Complete the request waiter after a terminal inbound outcome."""
        future = self._pending.get(msg.conversation_id)
        if future is None or future.done():
            return
        if msg.performative is Performative.INFORM:
            future.set_result(msg.content)
            if self.blackboard is not None:
                self.blackboard.policy.record_request_closed(self.agent_name)
        elif msg.performative in (Performative.REFUSE, Performative.FAILURE):
            failure = msg.failure or FailureInfo(code=FailureCode.POLICY, detail="request refused")
            future.set_exception(RoostFailure(failure))

    async def _send_reply(self, msg: RoostMessage) -> RoostMessage:
        """Send a preconstructed reply while retaining its protocol metadata."""
        await self._deliver_outbound(msg)
        return msg

    async def _deliver_outbound(self, msg: RoostMessage) -> None:
        """Audit and route an already-constructed outbound message."""
        await self.ledger.record(msg, direction="received", self_name=self.agent_name)
        self._metrics["messages_out"] += 1
        if msg.capability_filter is not None:
            if not self.carriers:
                raise Undeliverable("no configured carriers")
            for carrier in self.carriers.values():
                await carrier.send(msg)
            return

        by_carrier: dict[CarrierKind, list[AgentAddress]] = {}
        for receiver in msg.receivers:
            by_carrier.setdefault(receiver.carrier, []).append(receiver)
        if not by_carrier:
            raise Undeliverable("message has no receivers")
        for carrier_kind, carrier_receivers in by_carrier.items():
            carrier = self.carriers.get(carrier_kind)
            if carrier is None:
                raise Undeliverable(f"no carrier configured for {carrier_kind.value}")
            await carrier.send(msg.model_copy(update={"receivers": carrier_receivers}))

    async def send(
        self,
        performative: Performative,
        *,
        receivers: Sequence[AgentAddress] = (),
        capability_filter: Optional[str] = None,
        content: Any = None,
        protocol: Optional[InteractionProtocol] = None,
        conversation_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        body: Optional[str] = None,
        envelope: Any = None,
    ) -> RoostMessage:
        """Build, audit, route, and deliver one outbound Roost message."""
        conversation_id = conversation_id or uuid.uuid4().hex
        selected_protocol = protocol or InteractionProtocol.INFORM
        envelope = envelope or squawk_bridge.new_envelope(correlation_id=conversation_id, caller=self.agent_name)
        msg = RoostMessage(
            performative=performative,
            protocol=selected_protocol,
            conversation_id=conversation_id,
            in_reply_to=in_reply_to,
            sender=self.address(),
            receivers=list(receivers),
            capability_filter=capability_filter,
            content=content,
            body=body,
            envelope=envelope,
        )
        await self._deliver_outbound(msg)
        return msg

    async def inform(
        self,
        *,
        receivers: Sequence[AgentAddress] = (),
        capability_filter: Optional[str] = None,
        content: Any,
        body: Optional[str] = None,
    ) -> RoostMessage:
        """Send an Inform message."""
        return await self.send(
            Performative.INFORM,
            receivers=receivers,
            capability_filter=capability_filter,
            content=content,
            protocol=InteractionProtocol.INFORM,
            body=body,
        )

    async def request(
        self,
        cap_id: str,
        args: Mapping[str, Any],
        *,
        timeout: Optional[float] = None,
        receiver: Optional[AgentAddress] = None,
    ) -> Any:
        """Execute a Request conversation and return its native result."""
        if receiver is None:
            if self.registry is None:
                raise Undeliverable(cap_id)
            matches = self.registry.find_capability(cap_id, caller=self.agent_name, limit=1)
            if not matches:
                raise Undeliverable(cap_id)
            match = matches[0]
            receiver = AgentAddress(name=match.agent_name)
        conversation_id = uuid.uuid4().hex
        envelope = squawk_bridge.new_envelope(
            correlation_id=conversation_id,
            caller=self.agent_name,
            budget_ms=int(timeout * 1000) if timeout is not None else None,
        )
        opener = RoostMessage(
            performative=Performative.REQUEST,
            protocol=InteractionProtocol.REQUEST,
            conversation_id=conversation_id,
            sender=self.address(),
            receivers=[receiver],
            capability_filter=cap_id,
            content=dict(args),
            envelope=envelope,
        )
        self.engine.open(opener)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[conversation_id] = future
        try:
            await self.send(
                Performative.REQUEST,
                receivers=[receiver],
                capability_filter=None,
                content={"tool": cap_id.replace(".", "_"), **args},
                protocol=InteractionProtocol.REQUEST,
                conversation_id=conversation_id,
                envelope=envelope,
            )
            wait_timeout = timeout
            if wait_timeout is None and getattr(envelope, "budget_ms", None) is not None:
                wait_timeout = envelope.budget_ms / 1000
            if wait_timeout is None:
                return await future
            return await asyncio.wait_for(future, wait_timeout)
        except asyncio.TimeoutError as exc:
            failure = FailureInfo(code=FailureCode.TIMEOUT, detail="request timed out")
            raise RoostFailure(failure) from exc
        finally:
            self._pending.pop(conversation_id, None)

    async def query(
        self,
        question: Any,
        *,
        receiver: AgentAddress,
        timeout: Optional[float] = None,
        expected_schema: Optional[dict] = None,
    ) -> Any:
        """Execute a Query conversation without an agreement phase."""
        del expected_schema
        conversation_id = uuid.uuid4().hex
        envelope = squawk_bridge.new_envelope(
            correlation_id=conversation_id,
            caller=self.agent_name,
            budget_ms=int(timeout * 1000) if timeout is not None else None,
        )
        opener = RoostMessage(
            performative=Performative.QUERY,
            protocol=InteractionProtocol.QUERY,
            conversation_id=conversation_id,
            sender=self.address(),
            receivers=[receiver],
            content=question,
            envelope=envelope,
        )
        self.engine.open(opener)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[conversation_id] = future
        try:
            await self.send(
                Performative.QUERY,
                receivers=[receiver],
                content=question,
                protocol=InteractionProtocol.QUERY,
                conversation_id=conversation_id,
                envelope=envelope,
            )
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise RoostFailure(FailureInfo(code=FailureCode.TIMEOUT, detail="query timed out")) from exc
        finally:
            self._pending.pop(conversation_id, None)

    async def cfp(
        self,
        *,
        capability_filter: str,
        task: Any,
        bid_window_ms: int = 500,
        scorer: Optional[BidScorer] = None,
    ) -> Award:
        """Broadcast a Contract Net call, score proposals, and notify bidders."""
        del scorer
        conversation_id = uuid.uuid4().hex
        envelope = squawk_bridge.new_envelope(correlation_id=conversation_id, caller=self.agent_name)
        opener = RoostMessage(
            performative=Performative.CFP,
            protocol=InteractionProtocol.CONTRACT_NET,
            conversation_id=conversation_id,
            sender=self.address(),
            capability_filter=capability_filter,
            content=task,
            envelope=envelope,
        )
        self.engine.open(opener, budget=ConversationBudget(bid_window_ms=bid_window_ms))
        await self.send(
            Performative.CFP,
            capability_filter=capability_filter,
            content=task,
            protocol=InteractionProtocol.CONTRACT_NET,
            conversation_id=conversation_id,
            envelope=envelope,
        )
        await asyncio.sleep(bid_window_ms / 1000)
        award = self.engine.award(conversation_id)
        state = self.engine.state(conversation_id)
        if state is not None:
            for proposal in state.proposals:
                performative = Performative.ACCEPT if proposal.sender.name == award.winner else Performative.REJECT
                await self.send(
                    performative,
                    receivers=[proposal.sender],
                    protocol=InteractionProtocol.CONTRACT_NET,
                    conversation_id=conversation_id,
                    in_reply_to=proposal.message_id,
                    envelope=envelope,
                )
            self.engine.close(
                conversation_id,
                TerminalState.AWARDED if award.winner is not None else TerminalState.NO_BIDS,
            )
        return award

    async def subscribe(
        self,
        *,
        blackboard_key: Optional[str] = None,
        capability_filter: Optional[str] = None,
        handler: Optional[Handler] = None,
    ) -> str:
        """Subscribe locally to a blackboard key or remotely through Roost."""
        if blackboard_key is not None and self.blackboard is not None:

            async def store_notification(msg: RoostMessage) -> Optional[Any]:
                if handler is not None:
                    return await handler(msg)
                await self._store(msg)
                return None

            return await self.blackboard.subscribe(
                blackboard_key,
                store_notification,
                subscriber_name=self.agent_name,
            )
        if capability_filter is None:
            raise Undeliverable("subscribe requires a blackboard key or capability filter")
        msg = await self.send(
            Performative.SUBSCRIBE,
            capability_filter=capability_filter,
            protocol=InteractionProtocol.SUBSCRIBE,
        )
        self.engine.open(msg)
        return msg.conversation_id

    async def cancel(self, conversation_id: str, *, reason: str = "") -> None:
        """Close a local conversation and fail its pending waiter."""
        transition = self.engine.close(conversation_id, TerminalState.CANCELLED, reason=reason)
        for emitted in transition.emit:
            await self._send_reply(emitted)
        future = self._pending.get(conversation_id)
        if future is not None and not future.done():
            future.set_exception(RoostFailure(FailureInfo(code=FailureCode.CANCELLED, detail=reason)))

    def register_handler(self, content_type: str, handler: Handler, *, needs_decision: bool = False) -> None:
        """Register an inbound content handler with the deterministic dispatcher."""
        self.dispatcher.handlers.register(content_type, handler, needs_decision=needs_decision)

    async def find_and_mount(self, query: str, *, limit: int = 5) -> list[str]:
        """Find granted capabilities and mount them when the optional satellite is available."""
        if self.registry is None:
            return []
        matches = self.registry.find_capability(query, caller=self.agent_name, limit=limit)
        return await squawk_bridge.mount_capabilities(self.tool_manager, matches)

    @property
    def metrics(self) -> dict[str, int]:
        """Return a snapshot of endpoint message and work counters."""
        return dict(self._metrics)
