"""Question budget scopes, process-local registry and suspension/snapshot transfer (FEAT-550, spec §2.6 / §3 M2)."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import secrets
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from parrot.clients.budget import QuestionBudget  # TASK-3133
from parrot.core.exceptions import (  # TASK-3132
    BudgetRegistryFull,
    BudgetResumeConflict,
    BudgetScopeConflict,
    BudgetSnapshotInvalid,
    BudgetStateMissing,
)
from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.models.token_budget import BudgetSnapshot, TokenBudgetPolicy  # TASK-3132

TOKEN_BUDGET_STATE_KEY = "token_budget"
_CURRENT_SCOPE: ContextVar[Optional["BudgetScope"]] = ContextVar("parrot_budget_scope", default=None)
logger = logging.getLogger(__name__)


def current_budget_scope() -> Optional["BudgetScope"]:
    """Return the live inherited scope, or None when no question budget is active."""
    return _CURRENT_SCOPE.get()


class BudgetScope:
    """Live ledger reference, owner identity and immutable inherited policy."""

    def __init__(
        self,
        ledger: QuestionBudget,
        *,
        registry: "BudgetRegistry",
        is_root: bool,
        owner_call_id: Optional[str] = None,
    ) -> None:
        self.ledger = ledger
        self.registry = registry
        self.is_root = is_root
        self.owner_call_id = owner_call_id or (str(uuid.uuid4()) if is_root else None)
        self.loop_id = id(asyncio.get_running_loop())
        self._token: Optional[Token] = None

    @property
    def operation_id(self) -> str:
        return self.ledger.operation_id

    @property
    def policy(self) -> TokenBudgetPolicy:
        return self.ledger.policy

    owner_designated: bool = False

    def designate_owner(self, call_id: str) -> None:
        """Mark this root's answer owner once; descendants can never claim (spec §2.1/§2.3)."""
        if not self.is_root:
            raise BudgetScopeConflict(
                "only a root scope can designate the answer owner", operation_id=self.operation_id
            )
        if not self.owner_designated:
            self.owner_call_id, self.owner_designated = call_id, True

    def child(self) -> "BudgetScope":
        """Derive a descendant scope: spending rights only, never finalization ownership (spec §2.1)."""
        return BudgetScope(self.ledger, registry=self.registry, is_root=False, owner_call_id=None)

    async def __aenter__(self) -> "BudgetScope":
        """Bind in-process context and validate the owning event loop."""
        if self.loop_id != id(asyncio.get_running_loop()):
            raise BudgetScopeConflict(
                "budget scope entered on a different event loop",
                operation_id=self.operation_id,
            )
        self._token = _CURRENT_SCOPE.set(self)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Restore context; close, suspend or retain uncertain state as appropriate."""
        try:
            if not self.is_root:
                # Child scopes never own finalization; they never close the ledger.
                return
            if exc_type is None:
                await self.ledger.close()
                await self.registry.mark_closed(self.operation_id)
            elif isinstance(exc, HumanInteractionInterrupt):
                # The provider already called registry.suspend() before raising this;
                # leave the ledger's live state as-is so a resume can pick it back up.
                pass
            else:
                await self.ledger.close(terminal_reason=type(exc).__name__)
                await self.registry.mark_closed(self.operation_id)
        finally:
            if self._token is not None:
                _CURRENT_SCOPE.reset(self._token)


@dataclass
class _Record:
    ledger: QuestionBudget
    status: Literal["active", "suspended", "closed"] = "active"
    nonce: Optional[str] = None
    high_water: int = 0
    updated_at: float = field(default_factory=time.monotonic)
    detached: bool = False


class BudgetRegistry:
    """Bounded process-local registry; each operation stays on its owning loop."""

    def __init__(self, *, max_retained: int = 1024, retention_seconds: int = 3600) -> None:
        """Configure finite suspended/closed retention without evicting active work."""
        self._max_retained = max_retained
        self._retention_seconds = retention_seconds
        self._records: dict[str, _Record] = {}
        self._closed_ids: set[str] = set()
        self._lock = asyncio.Lock()

    async def create(self, policy: TokenBudgetPolicy) -> BudgetScope:
        """Allocate one root identity or fail if retained capacity is exhausted."""
        async with self._lock:
            self._prune_locked()
            if len(self._records) >= self._max_retained:
                raise BudgetRegistryFull(f"registry holds {len(self._records)} records")
            operation_id = str(uuid.uuid4())
            ledger = QuestionBudget(policy, operation_id)
            self._records[operation_id] = _Record(ledger)
            logger.debug("budget registry: created %s", operation_id)
            return BudgetScope(ledger, registry=self, is_root=True)

    async def suspend(self, scope: BudgetScope) -> dict[str, Any]:
        """Mint a fresh resume nonce and return the namespaced state envelope (spec §2.6)."""
        async with self._lock:
            rec = self._records[scope.operation_id]
            rec.nonce, rec.status, rec.updated_at = secrets.token_urlsafe(16), "suspended", time.monotonic()
            report = await scope.ledger.report()
            rec.high_water = max(rec.high_water, report.total_tokens)
            return {
                "operation_id": scope.operation_id,
                "policy": scope.policy.model_dump(),
                "revision": report.revision,
                "consumed_floor": report.total_tokens,
                "resume_nonce": rec.nonce,
                "owner_call_id": scope.owner_call_id,
            }

    async def resume(self, state: dict[str, Any], *, snapshot: Optional[BudgetSnapshot] = None) -> BudgetScope:
        """Consume the suspension nonce after policy, identity and floor checks."""
        envelope = state.get(TOKEN_BUDGET_STATE_KEY)
        if not isinstance(envelope, dict):
            raise BudgetStateMissing("resume state carries no token_budget envelope")
        async with self._lock:
            rec = self._records.get(envelope.get("operation_id", ""))
            if rec is None:
                if snapshot is None:
                    raise BudgetStateMissing(
                        f"no live record for operation {envelope.get('operation_id')!r} and no snapshot provided"
                    )
                return await self._import_snapshot_locked(envelope, snapshot)

            if rec.detached:
                raise BudgetResumeConflict(f"operation {envelope.get('operation_id')} was already exported/detached")
            if snapshot is not None and rec.nonce is None and rec.status == "active":
                # Identical re-import of an already-live record: no-op (idempotent).
                return BudgetScope(
                    rec.ledger,
                    registry=self,
                    is_root=True,
                    owner_call_id=envelope.get("owner_call_id"),
                )
            envelope_policy = envelope.get("policy")
            if envelope_policy is not None and rec.ledger.policy.model_dump() != envelope_policy:
                raise BudgetSnapshotInvalid("resume envelope policy does not match the live ledger's policy")
            if rec.ledger.revision < envelope.get("revision", 0):
                raise BudgetSnapshotInvalid("resume envelope revision is ahead of the live ledger")
            if rec.nonce is None or rec.nonce != envelope.get("resume_nonce"):
                raise BudgetResumeConflict(
                    f"resume nonce for operation {envelope.get('operation_id')} already consumed or mismatched"
                )

            # Atomically consume the nonce and reactivate.
            rec.nonce = None
            rec.status = "active"
            rec.updated_at = time.monotonic()
            return BudgetScope(
                rec.ledger,
                registry=self,
                is_root=True,
                owner_call_id=envelope.get("owner_call_id"),
            )

    async def _import_snapshot_locked(self, envelope: dict[str, Any], snapshot: BudgetSnapshot) -> BudgetScope:
        """Rebuild a ledger from a trusted snapshot; caller holds ``self._lock``."""
        operation_id = envelope.get("operation_id", "")
        if operation_id in self._closed_ids:
            raise BudgetSnapshotInvalid(f"operation {operation_id!r} is already closed and cannot be reopened")
        if snapshot.operation_id != operation_id:
            raise BudgetSnapshotInvalid("snapshot operation_id does not match the resume envelope")
        envelope_policy = envelope.get("policy")
        if envelope_policy is not None and snapshot.policy.model_dump() != envelope_policy:
            raise BudgetSnapshotInvalid("snapshot policy does not match the resume envelope")
        if snapshot.resume_nonce != envelope.get("resume_nonce"):
            raise BudgetSnapshotInvalid("snapshot resume nonce does not match the resume envelope")
        if snapshot.consumed_floor < envelope.get("consumed_floor", 0):
            raise BudgetSnapshotInvalid("snapshot cannot lower a known consumed floor")

        ledger = QuestionBudget(snapshot.policy, operation_id)
        ledger.restore_settled(
            input_tokens=snapshot.settled_input_tokens,
            output_tokens=snapshot.settled_output_tokens,
            revision=snapshot.revision,
            attempt_count=snapshot.attempt_count,
            round_count=snapshot.round_count,
        )
        self._records[operation_id] = _Record(
            ledger,
            status="active",
            nonce=None,
            high_water=snapshot.consumed_floor,
        )
        return BudgetScope(
            ledger,
            registry=self,
            is_root=True,
            owner_call_id=snapshot.owner_call_id or envelope.get("owner_call_id"),
        )

    async def export_settled(self, operation_id: str) -> BudgetSnapshot:
        """Transfer a quiescent suspension; refuse in-flight/uncertain ownership."""
        async with self._lock:
            rec = self._records.get(operation_id)
            if rec is None or rec.status != "suspended":
                raise BudgetSnapshotInvalid(f"operation {operation_id!r} is not a suspended record eligible for export")
            report = await rec.ledger.report()
            if report.in_flight_tokens != 0 or report.uncertain_tokens != 0 or report.finalization_attempted:
                raise BudgetSnapshotInvalid(
                    f"operation {operation_id!r} is not quiescent (in-flight/uncertain/finalizing)"
                )
            snapshot = BudgetSnapshot(
                operation_id=operation_id,
                policy=rec.ledger.policy,
                settled_input_tokens=report.input_tokens,
                settled_output_tokens=report.output_tokens,
                revision=report.revision,
                consumed_floor=report.total_tokens,
                resume_nonce=rec.nonce or "",
                attempt_count=rec.ledger.attempt_count,
                round_count=rec.ledger.round_count,
                owner_call_id=None,
                suspended_metadata={},
            )
            rec.detached = True
            return snapshot

    async def release(self, operation_id: str) -> None:
        """Release retained terminal state; never discard an active reservation."""
        async with self._lock:
            rec = self._records.get(operation_id)
            if rec is None:
                return
            if rec.status == "active":
                raise BudgetScopeConflict(f"cannot release active operation {operation_id!r}")
            self._records.pop(operation_id, None)
            self._closed_ids.add(operation_id)

    async def mark_closed(self, operation_id: str) -> None:
        """Record terminal state so a snapshot can never reopen it (called by BudgetScope.__aexit__)."""
        async with self._lock:
            rec = self._records.get(operation_id)
            if rec is not None:
                rec.status, rec.updated_at = "closed", time.monotonic()
            self._closed_ids.add(operation_id)

    def _prune_locked(self) -> None:
        """Drop suspended/closed records past retention; never touch active ones."""
        cutoff = time.monotonic() - self._retention_seconds
        for op_id in [k for k, r in self._records.items() if r.status != "active" and r.updated_at < cutoff]:
            self._records.pop(op_id)
            self._closed_ids.add(op_id)


_DEFAULT_REGISTRY: Optional[BudgetRegistry] = None


def get_default_registry() -> BudgetRegistry:
    """Process-wide default registry used when a client/bot is not handed one explicitly."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = BudgetRegistry()
    return _DEFAULT_REGISTRY


_MISSING = object()
BUDGET_KWARGS: frozenset[str] = frozenset(
    {"token_budget", "budget_mode", "final_answer_reserve", "budget_scope", "budget_snapshot"}
)


@dataclass(frozen=True)
class BudgetDefaults:
    """Constructor-level budget settings of a client or bot (spec §2.1)."""

    token_budget: Optional[int] = None
    budget_mode: str = "estimated"
    final_answer_reserve: "int | float" = 0.15
    registry: Optional[BudgetRegistry] = None


@dataclass(frozen=True)
class BudgetRequest:
    """Resolved outcome of one call's budget keywords."""

    policy: Optional[TokenBudgetPolicy]
    scope: Optional[BudgetScope]  # inherited/explicit parent scope, or None for a root
    snapshot: Optional[BudgetSnapshot]
    disabled: bool

    @property
    def active(self) -> bool:
        return not self.disabled and (self.policy is not None or self.scope is not None)


def resolve_budget_request(call_kwargs: dict[str, Any], *, defaults: BudgetDefaults, method_name: str) -> BudgetRequest:
    """Pop the §2.1 keywords from *call_kwargs* (mutating it) and decide root/child/disabled."""
    tb = call_kwargs.pop("token_budget", _MISSING)
    mode = call_kwargs.pop("budget_mode", _MISSING)
    reserve = call_kwargs.pop("final_answer_reserve", _MISSING)
    explicit_scope = call_kwargs.pop("budget_scope", None)
    snapshot = call_kwargs.pop("budget_snapshot", None)
    if snapshot is not None and method_name != "resume":
        raise TypeError("budget_snapshot is only accepted by resume()")
    parent = explicit_scope or current_budget_scope()
    if parent is not None:
        if tb is _MISSING and mode is _MISSING and reserve is _MISSING:
            # Omitted settings: inherit the parent scope/policy unchanged.
            return BudgetRequest(parent.policy, parent, snapshot, False)
        parent_policy = parent.policy
        effective_budget = parent_policy.token_budget if tb is _MISSING else tb
        effective_mode = parent_policy.budget_mode if mode is _MISSING else mode
        effective_reserve = parent_policy.final_answer_reserve if reserve is _MISSING else reserve
        if (
            effective_budget == parent_policy.token_budget
            and effective_mode == parent_policy.budget_mode
            and effective_reserve == parent_policy.final_answer_reserve
        ):
            # Explicitly repeated but identical settings: still a child.
            return BudgetRequest(parent.policy, parent, snapshot, False)
        # A child cannot disable or replace the active question policy.
        raise BudgetScopeConflict(
            "child call cannot alter the inherited question's token budget policy",
            operation_id=parent.operation_id,
        )
    if tb is None:  # explicit None at an independent root disables the constructor budget
        return BudgetRequest(None, None, snapshot, True)
    budget = defaults.token_budget if tb is _MISSING else tb
    if budget is None:
        if mode is not _MISSING or reserve is not _MISSING:
            raise ValueError("budget_mode/final_answer_reserve require an effective token_budget")
        return BudgetRequest(None, None, snapshot, True)
    policy = TokenBudgetPolicy(
        token_budget=budget,
        budget_mode=defaults.budget_mode if mode is _MISSING else mode,
        final_answer_reserve=defaults.final_answer_reserve if reserve is _MISSING else reserve,
    )
    return BudgetRequest(policy, None, snapshot, False)


async def _enter_scope(
    self: Any, request: BudgetRequest, *, method_name: str, state: Optional[dict] = None
) -> BudgetScope:
    """Materialise the scope for one call: child of parent, resumed ledger, or new root."""
    registry = getattr(self, "_budget_registry", None) or get_default_registry()
    if request.scope is not None:
        return request.scope.child()
    if method_name == "resume" and state is not None and TOKEN_BUDGET_STATE_KEY in state:
        return await registry.resume(state, snapshot=request.snapshot)
    return await registry.create(request.policy)


def _amend_signature(fn: Callable, wrapper: Callable) -> None:
    sig = inspect.signature(fn)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        wrapper.__signature__ = sig  # type: ignore[attr-defined]
        return
    extra = [inspect.Parameter(n, inspect.Parameter.KEYWORD_ONLY, default=None) for n in sorted(BUDGET_KWARGS)]
    wrapper.__signature__ = sig.replace(parameters=[*sig.parameters.values(), *extra])  # type: ignore[attr-defined]


def wrap_budgeted_coroutine(fn: Callable, *, method_name: str) -> Callable:
    """Wrap a coroutine method: resolve keywords, bind scope for the await, strip keywords."""

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if (
            not (BUDGET_KWARGS & kwargs.keys())
            and current_budget_scope() is None
            and getattr(self, "_budget_defaults_active", False) is False
        ):
            return await fn(self, *args, **kwargs)  # zero-cost pass-through (AC: nothing added to no-budget path)
        defaults = self._budget_defaults() if hasattr(self, "_budget_defaults") else BudgetDefaults()
        request = resolve_budget_request(kwargs, defaults=defaults, method_name=method_name)
        if not request.active:
            return await fn(self, *args, **kwargs)
        gate = getattr(self, "_budget_gate", None)
        if gate is not None:
            gate(method_name, request)  # raises BudgetUnsupported when the provider did not opt in (TASK-3136)
        state = (
            inspect.signature(fn).bind_partial(self, *args, **kwargs).arguments.get("state")
            if method_name == "resume"
            else None
        )
        scope = await _enter_scope(self, request, method_name=method_name, state=state)
        async with scope:
            return await fn(self, *args, **kwargs)

    _amend_signature(fn, wrapper)
    wrapper.__parrot_budget_wrapped__ = True  # type: ignore[attr-defined]
    return wrapper


def wrap_budgeted_async_generator(fn: Callable, *, method_name: str) -> Callable:
    """Wrap an async-generator method: hold the scope binding through iteration (spec §2.4)."""

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any):
        if (
            not (BUDGET_KWARGS & kwargs.keys())
            and current_budget_scope() is None
            and getattr(self, "_budget_defaults_active", False) is False
        ):
            async for item in fn(self, *args, **kwargs):
                yield item
            return
        defaults = self._budget_defaults() if hasattr(self, "_budget_defaults") else BudgetDefaults()
        request = resolve_budget_request(kwargs, defaults=defaults, method_name=method_name)
        if not request.active:
            async for item in fn(self, *args, **kwargs):
                yield item
            return
        gate = getattr(self, "_budget_gate", None)
        if gate is not None:
            gate(method_name, request)
        state = (
            inspect.signature(fn).bind_partial(self, *args, **kwargs).arguments.get("state")
            if method_name == "resume"
            else None
        )
        scope = await _enter_scope(self, request, method_name=method_name, state=state)
        async with scope:
            async for item in fn(self, *args, **kwargs):
                yield item

    _amend_signature(fn, wrapper)
    wrapper.__parrot_budget_wrapped__ = True  # type: ignore[attr-defined]
    return wrapper


def budget_entry(fn: Callable, *, method_name: str) -> Callable:
    """Pick the right wrapper for *fn*; idempotent on already-wrapped functions."""
    if getattr(fn, "__parrot_budget_wrapped__", False):
        return fn
    if inspect.isasyncgenfunction(fn):
        return wrap_budgeted_async_generator(fn, method_name=method_name)
    return wrap_budgeted_coroutine(fn, method_name=method_name)


__all__ = [
    "BudgetScope",
    "BudgetRegistry",
    "current_budget_scope",
    "get_default_registry",
    "TOKEN_BUDGET_STATE_KEY",
    "BUDGET_KWARGS",
    "BudgetDefaults",
    "BudgetRequest",
    "resolve_budget_request",
    "wrap_budgeted_coroutine",
    "wrap_budgeted_async_generator",
    "budget_entry",
]
