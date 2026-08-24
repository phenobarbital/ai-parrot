"""BusinessAutomationToolkit — the generic, domain-neutral automation engine.

FEAT-453, Module 5 (Goals G4, G5). Knows about "run a named business
operation with these parameters, pausing for human confirmation before
anything with legal effect" — nothing about any specific site. Contains
**zero** site-specific identifiers (no vendor/product names anywhere in this
package); site-specific plans live in an external, private plans directory
(Module 6, TASK-2391) loaded at runtime.

Gating follows Decision D2: reuse the shipped HITL stack
(:class:`~parrot.auth.confirmation.ConfirmationGuard`) rather than a bespoke
gate. ``run_operation`` manually invokes the guard for ``OperationKind.SUBMIT``
operations *before* the browser is ever opened — ``DRAFT``/``READ`` operations
never touch the guard at all.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from parrot.auth.confirmation import ConfirmationGuard, InMemoryConfirmationWindowStore
from parrot.tools.toolkit import AbstractToolkit

from parrot_tools.scraping import FlowExecutor, ScrapingFlow, TemplatePlan
from parrot_tools.scraping.session_actions import CredentialResolverFn

from .models import BusinessOperation, OperationKind
from .store import PlanDirectoryStore

if TYPE_CHECKING:
    from parrot.auth.broker import CredentialBroker
    from parrot.human import HumanInteractionManager
    from parrot.human.channels.base import HumanChannel

logger = logging.getLogger(__name__)

#: Invocation-channel label passed to ``CredentialBroker.resolve()`` for
#: audit context — distinct from (and never to be confused with) a
#: :class:`HumanChannel` instance, which is a completely different concept
#: (a notification/interaction transport, not an audit-log string).
_BROKER_INVOCATION_CHANNEL = "business_automation"


def _credential_resolver_from_broker(broker: "CredentialBroker", user_id: str) -> CredentialResolverFn:
    """Adapt a :class:`CredentialBroker` into a :class:`CredentialResolverFn`
    (code-review remediation, FEAT-453 AC-5).

    :meth:`CredentialBroker.resolve` is a generic, surface-agnostic
    ``(provider, channel, user_id) -> ResolvedCredential | NeedsAuth``
    broker built for OAuth/token providers — it has no built-in concept of
    a form-login ``(username, password)`` pair. This adapter bridges the
    two shapes: ``ResolvedCredential.secret`` may be a ``{"username":
    ..., "password": ...}`` dict (the convention this adapter expects a
    form-login provider's resolver to return), a 2-tuple/list, or a single
    opaque secret (e.g. an API key used as the "password" with no separate
    username). A ``NeedsAuth`` miss, a ``KeyError``/``ValueError`` from an
    unregistered provider or missing identity, or any other broker
    exception all resolve to ``None`` — :func:`~.session_actions.exec_authenticate`
    already fails the step closed on a ``None`` result when
    ``credential_provider`` is set (Decision D2/G3); this adapter never
    itself decides to fail open.

    Args:
        broker: The configured :class:`CredentialBroker`.
        user_id: Canonical per-user identity for this toolkit — see
            ``credential_user_id`` on :class:`BusinessAutomationToolkit`.
            This is a single-operator financial agent, not a multi-tenant
            surface, so a fixed identity (default ``"gestoria"``) is
            deliberate, not a placeholder oversight.
    """

    async def _resolve(action: Any) -> Optional[Any]:
        from parrot.auth.credentials import NeedsAuth

        try:
            result = await broker.resolve(action.credential_provider, _BROKER_INVOCATION_CHANNEL, user_id)
        except Exception:
            logger.exception(
                "CredentialBroker.resolve() raised for provider=%r; failing "
                "the authenticate step closed",
                action.credential_provider,
            )
            return None

        if isinstance(result, NeedsAuth):
            logger.warning(
                "CredentialBroker has no authorized credential for provider=%r "
                "(user=%r) — auth_url=%r; failing the authenticate step closed",
                action.credential_provider,
                user_id,
                result.auth_url,
            )
            return None

        secret = result.secret
        if isinstance(secret, dict):
            return secret.get("username"), secret.get("password")
        if isinstance(secret, (tuple, list)) and len(secret) == 2:
            return secret[0], secret[1]
        if isinstance(secret, str):
            # A single opaque secret (e.g. an API key) — no separate
            # username field for this provider.
            return None, secret

        logger.error(
            "CredentialBroker returned an unrecognized secret shape (%s) for "
            "provider=%r; failing the authenticate step closed",
            type(secret).__name__,
            action.credential_provider,
        )
        return None

    return _resolve


class BusinessAutomationToolkit(AbstractToolkit):
    """Generic engine for named, parameterized business operations.

    Holds a :class:`~parrot_tools.scraping.FlowExecutor`, an operation
    registry, and a submit-gate policy backed by the shared HITL stack
    (Decision D2). ``auto_open = True`` opens the browser lazily on first
    use (FEAT-391), exactly as :class:`~parrot.tools.obsidian.ObsidianToolkit`
    does for the vault.

    The operation/flow/template registries are populated either directly via
    the ``operations``/``flows``/``templates`` constructor kwargs (used by
    this task's own tests) or — once TASK-2391 lands — by a
    ``TemplatePlanStore`` that scans ``plans_dir``. This task wires the seam
    (``plans_dir`` is accepted and stored) but does not implement the
    directory scan itself; that is explicitly TASK-2391's responsibility.
    """

    auto_open = True

    def __init__(
        self,
        plans_dir: Union[str, Path],
        browser: Any = None,
        credential_broker: Optional[CredentialBroker] = None,
        human_manager: Optional[HumanInteractionManager] = None,
        checkpoint_dir: Optional[Path] = None,
        credential_user_id: str = "gestoria",
        human_channel: Optional["HumanChannel"] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit.

        Args:
            plans_dir: External, private plans directory (Module 6). When
                none of the ``operations``/``flows``/``templates`` override
                kwargs are given, this directory is loaded via
                :class:`~parrot_tools.business_automation.store.PlanDirectoryStore`
                at construction time (TASK-2391) — a malformed directory (or
                a missing one) raises loudly, matching that store's own
                "never silently reject one bad file" contract, rather than
                booting an agent with a silently-empty operation registry.
            browser: Live browser handle forwarded to :class:`FlowExecutor`.
            credential_broker: Optional :class:`CredentialBroker` for
                broker-backed ``Authenticate`` steps (Module 4). When set,
                adapted via :func:`_credential_resolver_from_broker` and
                forwarded to :class:`FlowExecutor` (code-review remediation,
                AC-5) — without this, a ``credential_provider``-backed
                ``Authenticate`` was previously unreachable from
                :meth:`run_operation`, always failing closed regardless of
                whether a broker was configured.
            human_manager: Optional :class:`HumanInteractionManager`. ``None``
                means every ``OperationKind.SUBMIT`` operation fails closed
                (Decision D2) — this is the safe default for a financial
                write, not an oversight.
            checkpoint_dir: Directory for :class:`FlowExecutor` checkpoints.
            credential_user_id: Canonical identity used when resolving
                credentials through *credential_broker* (see
                :func:`_credential_resolver_from_broker`). This engine is a
                single-operator financial agent, not a multi-tenant surface,
                so a fixed default (``"gestoria"``, matching this feature's
                own naming convention — Module 10) is deliberate.
            human_channel: Optional :class:`HumanChannel` forwarded to
                :class:`FlowExecutor` for mid-plan ``await_human`` steps
                (code-review remediation). Deliberately a **separate**
                parameter from *human_manager* rather than reusing one of
                ``human_manager.channels`` — TASK-2385 flagged that sharing
                a channel instance with a ``HumanInteractionManager`` risks
                ``exec_await_human``'s ``register_response_handler()`` call
                colliding with the manager's own registration on that same
                channel. Configure a dedicated channel instance here instead.
            **kwargs: Forwarded to :class:`AbstractToolkit`. ``operations``,
                ``flows``, and ``templates`` (mappings keyed by name) are
                popped here to seed the registries directly instead of
                scanning ``plans_dir`` — the interim seam this task's own
                tests (and TASK-2395/2396/2397's) still use for unit-level
                fixtures.
        """
        operations_override = kwargs.pop("operations", None)
        flows_override = kwargs.pop("flows", None)
        templates_override = kwargs.pop("templates", None)
        overrides_given = any(
            override is not None for override in (operations_override, flows_override, templates_override)
        )

        super().__init__(**kwargs)

        self.plans_dir = Path(plans_dir)
        self._browser = browser
        self._credential_broker = credential_broker
        self._human_manager = human_manager
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        self._credential_user_id = credential_user_id
        self._human_channel = human_channel
        self._credential_resolver: Optional[CredentialResolverFn] = (
            _credential_resolver_from_broker(credential_broker, credential_user_id)
            if credential_broker is not None
            else None
        )

        self._plan_store: Optional[PlanDirectoryStore] = None
        if overrides_given:
            # Interim/test seam: registries seeded directly, plans_dir is
            # never scanned.
            self._operations: Dict[str, BusinessOperation] = dict(operations_override or {})
            self._flows: Dict[str, ScrapingFlow] = dict(flows_override or {})
            self._templates: Dict[str, TemplatePlan] = dict(templates_override or {})
        else:
            # TASK-2391's PlanDirectoryStore scans plans_dir now; run_operation()
            # hot-reloads it on every call (Module 6's documented "hot-reload
            # on change"). A malformed directory raises here — the same
            # ValueError the store itself raises — closing the seam TASK-2390's
            # own docstring deferred ("This task wires the seam ... does not
            # implement the directory scan itself").
            self._plan_store = PlanDirectoryStore(self.plans_dir)
            self._plan_store.load()
            self._operations = self._plan_store.operations
            self._flows = self._plan_store.flows
            self._templates = self._plan_store.templates

        self._confirmation_guard = ConfirmationGuard(
            store=InMemoryConfirmationWindowStore(),
            human_manager=human_manager,
        )

        self._flow_executor: Optional[FlowExecutor] = None
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._run_tasks: Dict[str, asyncio.Task[None]] = {}

    # ── FEAT-391 lazy lifecycle ──────────────────────────────────────────

    async def _open(self) -> None:
        """Construct the FlowExecutor bound to the configured browser."""
        self._flow_executor = FlowExecutor(
            self._browser,
            concurrency=1,  # FEAT-222: fan-out over a shared session is deferred debt
            checkpoint_dir=self._checkpoint_dir,
            templates=self._templates,
            credential_resolver=self._credential_resolver,
            channel=self._human_channel,
        )

    async def _close(self) -> None:
        """Release the FlowExecutor reference (it does not own the browser)."""
        self._flow_executor = None
        await super()._close()

    # ── Tools ─────────────────────────────────────────────────────────────

    async def list_operations(self) -> Dict[str, Any]:
        """List every registered business operation.

        Returns:
            ``{"operations": [{"name", "kind", "description"}, ...]}``.
        """
        return {
            "operations": [
                {
                    "name": op.name,
                    "kind": op.kind.value,
                    "description": op.description,
                }
                for op in self._operations.values()
            ]
        }

    async def describe_operation(self, name: str) -> Dict[str, Any]:
        """Describe one operation's parameters and confirmation policy.

        Args:
            name: The operation name (see :meth:`list_operations`).

        Returns:
            A dict with ``name``, ``description``, ``kind``, and ``params``,
            or ``{"status": "error", ...}`` if *name* is unknown.
        """
        op = self._operations.get(name)
        if op is None:
            return {"status": "error", "error": f"Unknown operation: {name!r}"}
        return {
            "name": op.name,
            "description": op.description,
            "kind": op.kind.value,
            "params": [p.model_dump() for p in op.params],
        }

    async def run_operation(self, name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run a named business operation with these parameters.

        ``OperationKind.SUBMIT`` operations pause for human confirmation
        (Decision D2) *before* the browser is opened — a denial never opens
        a browser. ``DRAFT``/``READ`` operations never touch the
        confirmation guard at all. The plan is validated
        (:meth:`~parrot_tools.scraping.plan.ScrapingPlan.validate_steps`)
        before any driver is constructed (Module 3, Goal G2). Long-running
        execution happens in the background — this returns a ``run_id``
        immediately so a chat turn is never held open.

        Args:
            name: The operation to run (see :meth:`list_operations`).
            params: Parameters bound into the operation's flow templates.

        Returns:
            ``{"status": "started", "run_id": ..., "operation": ...}`` on
            success, or an error/denial dict (``"error"``, ``"cancelled"``,
            ``"timeout"``) otherwise.
        """
        params = params or {}
        if self._plan_store is not None:
            try:
                if self._plan_store.reload_if_changed():
                    self._operations = self._plan_store.operations
                    self._flows = self._plan_store.flows
                    self._templates = self._plan_store.templates
            except ValueError as exc:
                # A plans_dir edited into a malformed state mid-run must not
                # crash every subsequent call — the store itself already
                # left its last-good registries untouched (see
                # PlanDirectoryStore.load()); surface this as a clean error
                # like every other run_operation() failure path.
                return {
                    "status": "error",
                    "operation": name,
                    "error": f"plans_dir hot-reload failed: {exc}",
                }

        op = self._operations.get(name)
        if op is None:
            return {"status": "error", "operation": name, "error": f"Unknown operation: {name!r}"}

        if op.kind == OperationKind.SUBMIT:
            decision = await self._request_submit_confirmation(op, params)
            if not decision.allowed:
                return {
                    "status": decision.status,
                    "operation": op.name,
                    "reason": decision.reason,
                }

        flow = self._flows.get(op.flow_ref)
        if flow is None:
            return {
                "status": "error",
                "operation": op.name,
                "error": f"No flow registered for flow_ref={op.flow_ref!r}",
            }

        try:
            self._validate_flow(flow, params)
        except Exception as exc:  # noqa: BLE001 — any validation failure is a clean error, not a crash
            return {"status": "error", "operation": op.name, "error": str(exc)}

        await self._ensure_open()

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        self._runs[run_id] = {"status": "running", "operation": op.name, "params": params}
        task = asyncio.create_task(self._execute_run(run_id, flow, params))
        self._run_tasks[run_id] = task

        return {"status": "started", "run_id": run_id, "operation": op.name}

    async def resume_operation(self, run_id: str, resume_from: Optional[str] = None) -> Dict[str, Any]:
        """Resume a previously started (and interrupted) operation run.

        Args:
            run_id: A ``run_id`` returned by a prior :meth:`run_operation`
                call.
            resume_from: The flow node id to resume from (forwarded to
                :meth:`FlowExecutor.run`'s ``resume_from``). ``None`` lets
                the executor's own checkpoint discover where to continue.

        Returns:
            ``{"status": "started", "run_id": ..., "resumed": True}`` on
            success, or an error dict if *run_id* or its operation cannot be
            resolved.
        """
        record = self._runs.get(run_id)
        if record is None:
            return {
                "status": "error",
                "error": f"Unknown run_id {run_id!r}. Known: {sorted(self._runs)}",
            }

        op = self._operations.get(record.get("operation", ""))
        if op is None:
            return {
                "status": "error",
                "run_id": run_id,
                "error": "Cannot resume: the original operation is no longer registered",
            }

        flow = self._flows.get(op.flow_ref)
        if flow is None:
            return {
                "status": "error",
                "run_id": run_id,
                "error": f"No flow registered for flow_ref={op.flow_ref!r}",
            }

        await self._ensure_open()

        params = record.get("params", {})
        self._runs[run_id] = {"status": "running", "operation": op.name, "params": params}
        task = asyncio.create_task(self._execute_run(run_id, flow, params, resume_from=resume_from))
        self._run_tasks[run_id] = task

        return {"status": "started", "run_id": run_id, "operation": op.name, "resumed": True}

    # ── Internal ──────────────────────────────────────────────────────────

    async def _request_submit_confirmation(self, op: BusinessOperation, params: Dict[str, Any]) -> Any:
        """Gate a SUBMIT-kind operation through the shared HITL stack.

        Builds a minimal stand-in object exposing only ``name`` and
        ``routing_meta`` — the two attributes
        :class:`~parrot.auth.confirmation.ConfirmationGuard` actually reads
        — since ``run_operation`` dispatches every operation through a
        single method (this is a manual, code-level gate rather than the
        static, whole-method ``AbstractToolkit.confirming_tools`` marking,
        which cannot vary per resolved operation kind).

        ``confirm_window_seconds=0`` is set explicitly (Decision D2): the
        guard's default window would otherwise allow a repeated identical
        submit within the window to auto-approve — exactly the duplicate
        filing hazard this feature exists to prevent.
        """
        tool_stub = SimpleNamespace(
            name=f"run_operation:{op.name}",
            routing_meta={
                "requires_confirmation": True,
                "confirm_window_seconds": 0,
                "confirm_template": op.confirm_prompt or f"Run business operation {op.name!r} with: {{params}}",
            },
        )
        return await self._confirmation_guard.confirm(tool=tool_stub, parameters=params)

    def _validate_flow(self, flow: ScrapingFlow, params: Dict[str, Any]) -> None:
        """Bind and validate every node's template before any driver exists.

        Module 3 (Goal G2): a malformed plan fails before the browser opens.
        Best-effort — nodes whose inputs depend on a prior node's output
        (``FlowNode.inputs``) are validated with the flow/caller params only
        (a static lint pass, not a full dry run); the executor performs the
        real cross-node resolution at run time.
        """
        merged = {**flow.global_params, **params}
        for node in flow.nodes:
            template = self._templates.get(node.plan_ref)
            if template is None:
                raise ValueError(f"No TemplatePlan registered for plan_ref={node.plan_ref!r} " f"(node={node.id!r})")
            plan = template.bind(**merged)
            plan.validate_steps()

    async def _execute_run(
        self,
        run_id: str,
        flow: ScrapingFlow,
        params: Dict[str, Any],
        *,
        resume_from: Optional[str] = None,
    ) -> None:
        """Background task executing *flow* and recording its outcome."""
        try:
            assert self._flow_executor is not None  # _ensure_open() ran before this task started
            result = await self._flow_executor.run(flow, params=params, resume_from=resume_from)
            self._runs[run_id] = {
                "status": "done" if result.success else "failed",
                "operation": self._runs.get(run_id, {}).get("operation"),
                "params": params,
                "result": result,
            }
        except Exception as exc:
            self.logger.exception("Business operation run %s failed", run_id)
            self._runs[run_id] = {
                "status": "failed",
                "operation": self._runs.get(run_id, {}).get("operation"),
                "params": params,
                "error": str(exc),
            }
