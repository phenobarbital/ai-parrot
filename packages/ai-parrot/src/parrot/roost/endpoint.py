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
from .grant import GrantDenied, GrantPolicy
from .messages import AgentAddress, FailureInfo, RoostMessage
from .performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from .protocols import ConversationBudget, ProtocolEngine, TerminalState
from .scoring import Award, BidScorer

if TYPE_CHECKING:
    from parrot.registry import AgentRegistry
    from parrot.tools.manager import ToolManager
    from parrot.tools.working_memory.tool import WorkingMemoryToolkit

#: Wakes the host agent for one turn.
#:
#: The returned :class:`RoostMessage` MUST carry ``tokens`` — the tokens the host actually
#: spent on this turn. Roost cannot observe a provider's usage, so a response left at the
#: default ``tokens=0`` leaves the conversation effectively unbudgeted: ``token_budget`` is
#: never reached and ``FailureCode.TOKEN_BUDGET`` never fires. The endpoint logs a warning
#: once per conversation when a budgeted conversation reports 0 tokens.
#:
#: Report usage through the reply itself::
#:
#:     return msg.reply(Performative.INFORM, content=answer, tokens=usage.total_tokens)
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
        permission_context: Any = None,
        auth_token: Optional[str] = None,
        sweep_interval: float = 0.25,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.agent_name, self.config, self.engine, self.dispatcher = agent_name, config, engine, dispatcher
        self.carriers, self.tool_manager, self.blackboard = dict(carriers), tool_manager, blackboard
        self.ledger = ledger or RoostAuditLedger()
        self.working_memory, self.wake, self.registry = working_memory, wake, registry
        self.grant = grant or GrantPolicy()
        self._permission_context, self._auth_token = permission_context, auth_token
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._subs: list[tuple[Carrier, str]] = []
        self._sweep_interval = sweep_interval
        self._sweeper: Optional[asyncio.Task[None]] = None
        self._metrics = {"messages_in": 0, "messages_out": 0, "wakes": 0, "not_understood": 0, "stored": 0}
        self._token_budget_warned: set[str] = set()

    def address(self) -> AgentAddress:
        """Return this endpoint's configured transport address."""
        carrier = self.config.carrier if self.config else CarrierKind.IN_PROCESS
        return AgentAddress(name=self.agent_name, carrier=carrier)

    def _caller_authority(self) -> tuple[Any, Optional[str]]:
        """Return the caller authority to stamp on an outbound message.

        The constructor override wins; otherwise the request-scoped
        ``PermissionContext`` published on ``parrot.auth.context._pctx_var``
        is used, so a shared endpoint never mixes two callers' identities.

        Returns:
            The resolved ``(permission_context, auth_token)`` pair; either may be ``None``.
        """
        if self._permission_context is not None:
            return self._permission_context, self._auth_token
        from parrot.auth.context import _pctx_var

        return _pctx_var.get(), self._auth_token

    async def start(self) -> None:
        """Subscribe this endpoint's address (and capabilities) on every carrier."""
        if self._subs:
            return
        capabilities = self.config.capabilities if self.config is not None else ()
        for carrier in self.carriers.values():
            subscription_id = await carrier.subscribe(self.address(), self._on_message, capabilities=capabilities)
            self._subs.append((carrier, subscription_id))
        if self._sweeper is None and self._sweep_interval > 0:
            self._sweeper = asyncio.get_running_loop().create_task(self._sweep_loop())

    async def stop(self) -> None:
        """Unsubscribe and fail outstanding request waiters as cancelled."""
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
            self._sweeper = None
        for carrier, subscription_id in self._subs:
            await carrier.unsubscribe(subscription_id)
        self._subs.clear()
        failure = RoostFailure(FailureInfo(code=FailureCode.CANCELLED, detail="endpoint stopped"))
        for future in self._pending.values():
            if not future.done():
                future.set_exception(failure)
        self._pending.clear()

    async def _sweep_loop(self) -> None:
        """Periodically close expired conversations (deadline / bid window)."""
        while True:
            await asyncio.sleep(self._sweep_interval)
            try:
                await self.sweep()
            except Exception:  # noqa: BLE001 — a sweep failure must never kill the loop
                self.logger.exception("Roost sweep failed")

    async def sweep(self) -> int:
        """Run ``ProtocolEngine.expire`` and deliver the typed ``failure(TIMEOUT)`` it emits.

        Failures addressed to this agent resolve the local request waiter; the rest go out over the carriers.

        Returns:
            Number of conversations closed by this sweep.
        """
        transitions = self.engine.expire()
        for transition in transitions:
            for emitted in transition.emit:
                await self._route_emitted(emitted)
        return len(transitions)

    async def _route_emitted(self, emitted: RoostMessage) -> None:
        """Deliver an engine-emitted message: locally when it names this agent, else over a carrier.

        A budget that trips on the side which opened the conversation produces a failure
        addressed to this agent; that message is what the pending ``request``/``query`` future is
        waiting for, so it must resolve the waiter instead of going out over a carrier and
        arriving back on an already-terminal conversation.
        """
        if emitted.is_addressed_to(self.agent_name):
            await self._resolve_pending(emitted)
        else:
            await self._send_reply(emitted)

    async def _on_message(self, msg: RoostMessage) -> None:
        """Audit, dispatch, and execute an inbound Roost message."""
        self._metrics["messages_in"] += 1
        await self.ledger.record(msg, direction="served", self_name=self.agent_name)
        dispatch = self.dispatcher.dispatch(msg)
        for emitted in dispatch.emit:
            await self._route_emitted(emitted)

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
                    exhausted = self.engine.charge(msg.conversation_id, response.tokens)
                    if response.tokens == 0:
                        self._warn_unfed_token_budget(msg.conversation_id)
                    if exhausted is not None:
                        for emitted in exhausted.emit:
                            await self._route_emitted(emitted)
                    self._forget_if_closed(msg.conversation_id)
            await self._resolve_pending(msg)
            return
        if dispatch.decision is DispatchDecision.BID_FROM_CONTRACT:
            bid = self.config.bid if self.config is not None else None
            if bid is not None:
                await self._send_reply(msg.reply(Performative.PROPOSE, content=bid))
            return
        if dispatch.decision is DispatchDecision.REPLAN:
            await self._resolve_pending(msg)

    def _advertised_tool(self, msg: RoostMessage) -> Optional[str]:
        """Return the tool name for an inbound message, or ``None`` when it is not advertised.

        The capability is taken from ``msg.capability_filter`` when present; a directed request
        (which cannot carry a filter without turning into a broadcast) names it in ``content["tool"]``.
        Either way it must equal an advertised ``config.capabilities`` entry, so a caller cannot
        name an arbitrary tool registered in this agent's manager (``issue:59d1cb0c9814`` part 3).

        Args:
            msg: The inbound Roost message whose capability is being served.

        Returns:
            The underscore tool name, or ``None`` when no advertised capability matches.
        """
        if self.config is None:
            return None
        if msg.capability_filter is not None:
            wanted = msg.capability_filter.replace(".", "_")
        elif isinstance(msg.content, dict) and isinstance(msg.content.get("tool"), str):
            wanted = msg.content["tool"]
        else:
            return None
        for capability in self.config.capabilities:
            if capability.replace(".", "_") == wanted:
                return wanted
        return None

    async def _refuse(self, msg: RoostMessage, detail: str) -> None:
        """Answer *msg* with ``failure(POLICY)`` when it has an explicit sender to reply to."""
        if not msg.receivers:
            self.logger.warning("Roost cannot reply to broadcast refusal on conversation %s", msg.conversation_id)
            return
        await self._send_reply(
            msg.reply(Performative.FAILURE, failure=FailureInfo(code=FailureCode.POLICY, detail=detail))
        )

    async def _run_tool(self, msg: RoostMessage) -> None:
        """Run a deterministic serving tool through the manager's policy guard."""
        content = msg.content if isinstance(msg.content, dict) else {}
        authority = squawk_bridge.resolve_authority(msg)
        if authority is None:
            self.logger.warning("Roost refused an unauthenticated request on conversation %s", msg.conversation_id)
            await self._refuse(msg, "no caller authority on the message")
            return
        tool_name = self._advertised_tool(msg)
        if tool_name is None:
            self.logger.warning(
                "Roost refused capability %r not advertised by %s", msg.capability_filter, self.agent_name
            )
            await self._refuse(msg, "capability not advertised")
            return
        try:
            result = await self.tool_manager.execute_tool(tool_name, content, permission_context=authority)
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

    def _warn_unfed_token_budget(self, conversation_id: str) -> None:
        """Warn once per conversation that a declared token budget is receiving no usage.

        A wake callback that leaves ``RoostMessage.tokens`` at 0 makes the budget
        unenforceable; this surfaces the misintegration without changing the turn. A
        conversation that declares no budget is legitimately unbudgeted and stays silent.
        """
        state = self.engine.state(conversation_id)
        if state is None or state.budget.token_budget is None:
            return
        if conversation_id in self._token_budget_warned:
            return
        self._token_budget_warned.add(conversation_id)
        self.logger.warning(
            "Roost conversation %s declares a token budget of %s but its wake response reported 0 tokens; "
            "the WakeCallback must set RoostMessage.tokens or the budget cannot be enforced",
            conversation_id,
            state.budget.token_budget,
        )

    def _forget_if_closed(self, conversation_id: str) -> None:
        """Drop per-conversation bookkeeping once the conversation is terminal."""
        state = self.engine.state(conversation_id)
        if state is None or state.terminal is not None:
            self._token_budget_warned.discard(conversation_id)

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
        self._token_budget_warned.discard(msg.conversation_id)

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
        hops: int = 0,
    ) -> RoostMessage:
        """Build, audit, route, and deliver one outbound Roost message."""
        conversation_id = conversation_id or uuid.uuid4().hex
        selected_protocol = protocol or InteractionProtocol.INFORM
        envelope = envelope or squawk_bridge.new_envelope(correlation_id=conversation_id, caller=self.agent_name)
        pctx, token = self._caller_authority()
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
            permission_context=pctx,
            auth_token=token,
            hops=hops,
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
        hops: int = 0,
    ) -> Any:
        """Execute a Request conversation and return its native result.

        Args:
            cap_id: Capability to request.
            args: Tool arguments.
            timeout: Seconds to wait; also becomes the envelope budget.
            receiver: Explicit target agent; the caller's grant must cover *cap_id* (fail-closed).
            hops: Chain depth of the caller (e.g. ``ctx.current_hops``) seeding the hop budget.

        Raises:
            GrantDenied: *cap_id* is outside the caller's grant.
        """
        if receiver is not None and not self.grant.allows(self.config, cap_id):
            raise GrantDenied(cap_id)
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
        pctx, token = self._caller_authority()
        opener = RoostMessage(
            performative=Performative.REQUEST,
            protocol=InteractionProtocol.REQUEST,
            conversation_id=conversation_id,
            sender=self.address(),
            receivers=[receiver],
            capability_filter=cap_id,
            content=dict(args),
            envelope=envelope,
            permission_context=pctx,
            auth_token=token,
            hops=hops,
        )
        self.engine.open(opener)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[conversation_id] = future
        try:
            await self.send(
                Performative.REQUEST,
                receivers=[receiver],
                capability_filter=None,
                content={**dict(args), "tool": cap_id.replace(".", "_")},
                protocol=InteractionProtocol.REQUEST,
                conversation_id=conversation_id,
                envelope=envelope,
                hops=hops + 1,
            )
            wait_timeout = timeout
            if wait_timeout is None and getattr(envelope, "budget_ms", None) is not None:
                wait_timeout = envelope.budget_ms / 1000
            if wait_timeout is None:
                return await future
            return await asyncio.wait_for(future, wait_timeout)
        except asyncio.TimeoutError as exc:
            self._close_timed_out(conversation_id)
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
        hops: int = 0,
    ) -> Any:
        """Execute a Query conversation without an agreement phase.

        Args:
            question: Free-form query content.
            receiver: Target agent; its name is checked against the caller's grant (fail-closed).
            timeout: Seconds to wait; also becomes the envelope budget.
            expected_schema: Currently unused.
            hops: Chain depth of the caller seeding the hop budget.

        Raises:
            GrantDenied: *receiver* is outside the caller's grant.
        """
        if not self.grant.allows(self.config, receiver.name):
            raise GrantDenied(receiver.name)
        del expected_schema
        conversation_id = uuid.uuid4().hex
        envelope = squawk_bridge.new_envelope(
            correlation_id=conversation_id,
            caller=self.agent_name,
            budget_ms=int(timeout * 1000) if timeout is not None else None,
        )
        pctx, token = self._caller_authority()
        opener = RoostMessage(
            performative=Performative.QUERY,
            protocol=InteractionProtocol.QUERY,
            conversation_id=conversation_id,
            sender=self.address(),
            receivers=[receiver],
            content=question,
            envelope=envelope,
            permission_context=pctx,
            auth_token=token,
            hops=hops,
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
                hops=hops + 1,
            )
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            self._close_timed_out(conversation_id)
            raise RoostFailure(FailureInfo(code=FailureCode.TIMEOUT, detail="query timed out")) from exc
        finally:
            self._pending.pop(conversation_id, None)

    def _close_timed_out(self, conversation_id: str) -> None:
        """Mark a locally timed-out conversation terminal so late replies are not-understood."""
        state = self.engine.state(conversation_id)
        if state is not None and state.terminal is None:
            self.engine.close(conversation_id, TerminalState.TIMED_OUT, reason="timeout")

    async def cfp(
        self,
        *,
        capability_filter: str,
        task: Any,
        bid_window_ms: int = 500,
        scorer: Optional[BidScorer] = None,
    ) -> Award:
        """Broadcast a Contract Net call, score proposals, and notify bidders."""
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
        award = self.engine.award(conversation_id, scorer)
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
