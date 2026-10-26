"""Guarded host dataset-sink contract and per-read semantic authorization."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

from .catalog import RoleCatalog
from .context import SemanticRequestIdentity
from .errors import SemanticResultError
from .governance.pbac import PbacGate
from .governance.pipeline import subject_digest
from .loader import LoadedModel
from .results import ResultHandle

ReadAuthorizer = Callable[[SemanticRequestIdentity], Awaitable[None]]

_LOGGER = logging.getLogger(__name__)
_DENIED = "result_unavailable"
_RAW_TYPE_NAMES = frozenset({"DatasetManager", "AbstractToolkit", "DataFrame"})


def _deny() -> SemanticResultError:
    """Build the single opaque denial used for every failed read check."""
    return SemanticResultError(_DENIED, "Result is unavailable")


@runtime_checkable
class GovernedDatasetSink(Protocol):
    """Trusted host adapter; every exposure invokes the registered read authorizer."""

    scope_id: str
    owner: tuple[str, str, str, str]
    guarded_reads: Literal[True]

    async def publish(self, name: str, handle: ResultHandle, authorize_read: ReadAuthorizer) -> dict[str, Any]:
        """Publish privately without exposing an unguarded manager or source."""
        ...


def handle_owner(handle: ResultHandle) -> tuple[str, str, str, str]:
    """Return the immutable (agent, user, tenant, session) owner tuple of a handle."""
    return (handle.agent_id, handle.user_id, handle.tenant_id, handle.session_id)


def _is_raw_target(value: object) -> bool:
    """Detect raw/shared DatasetManager-like targets and dataframes by class lineage."""
    return any(klass.__name__ in _RAW_TYPE_NAMES for klass in type(value).__mro__)


def _validate_sink(sink: object) -> None:
    """Fail closed unless the sink explicitly satisfies the guarded contract."""
    if _is_raw_target(sink):
        raise SemanticResultError("sink_rejected", "Raw or shared dataset managers are not guarded sinks")
    if getattr(sink, "guarded_reads", None) is not True:
        raise SemanticResultError("sink_rejected", "Sink does not declare guarded reads")
    scope_id = getattr(sink, "scope_id", None)
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise SemanticResultError("sink_rejected", "Sink scope_id is invalid")
    owner = getattr(sink, "owner", None)
    if not (
        isinstance(owner, tuple) and len(owner) == 4 and all(isinstance(part, str) and part.strip() for part in owner)
    ):
        raise SemanticResultError("sink_rejected", "Sink owner must be an immutable 4-tuple of identifiers")
    if not inspect.iscoroutinefunction(getattr(sink, "publish", None)):
        raise SemanticResultError("sink_rejected", "Sink publish must be async")


class GovernedSinkRegistry:
    """Explicit host registration of sinks; capability flags alone grant nothing."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._by_scope: dict[str, GovernedDatasetSink] = {}
        self._owners: dict[tuple[str, str, str, str], str] = {}

    def register(self, sink: GovernedDatasetSink) -> None:
        """Register a validated sink, refusing owner or scope reuse.

        Args:
            sink: Trusted host adapter.

        Raises:
            SemanticResultError: If validation fails or the scope/owner is already registered.
        """
        _validate_sink(sink)
        if sink.scope_id in self._by_scope or sink.owner in self._owners:
            raise SemanticResultError("sink_rejected", "Sink scope or owner is already registered")
        self._by_scope[sink.scope_id] = sink
        self._owners[sink.owner] = sink.scope_id

    def is_registered(self, sink: object) -> bool:
        """Return whether this exact sink instance was registered."""
        scope_id = getattr(sink, "scope_id", None)
        return isinstance(scope_id, str) and self._by_scope.get(scope_id) is sink

    async def publish(
        self,
        sink: GovernedDatasetSink,
        name: str,
        handle: ResultHandle,
        authorize_read: ReadAuthorizer,
        *,
        identity: SemanticRequestIdentity,
    ) -> dict[str, Any]:
        """Publish a handle through a registered sink after all guards pass.

        All checks run before the sink is called so no rejected request has side effects.

        Args:
            sink: Previously registered sink.
            name: Dataset name.
            handle: Retained result to publish.
            authorize_read: Callback the sink must invoke on every exposure.
            identity: Current trusted caller identity.

        Returns:
            Sink metadata, never a raw manager, source or dataframe.

        Raises:
            SemanticResultError: When the sink is unregistered, owner differs, or authorization fails.
        """
        if not self.is_registered(sink):
            raise SemanticResultError("sink_rejected", "Sink is not registered")
        if sink.owner != handle_owner(handle):
            raise SemanticResultError("sink_rejected", "Sink owner does not match the result owner")
        if (identity.agent_id, identity.ctx.user_id, identity.ctx.tenant_id, identity.session_id) != sink.owner:
            raise _deny()
        await authorize_read(identity)
        result = await sink.publish(name, handle, authorize_read)
        if not isinstance(result, dict) or any(_is_raw_target(value) for value in result.values()):
            raise SemanticResultError("sink_rejected", "Sink returned an unguarded object")
        return result


def build_read_authorizer(
    handle: ResultHandle,
    *,
    models: Callable[[], dict[str, LoadedModel]],
    catalog: Callable[[], RoleCatalog],
    pbac: PbacGate,
) -> ReadAuthorizer:
    """Close over copied provenance; reload current policy before every read.

    Args:
        handle: Retained result whose provenance is copied (never mutated afterwards).
        models: Provider of the current model snapshot.
        catalog: Provider of the current role catalog.
        pbac: Fail-closed PBAC gate.

    Returns:
        An async callback raising :class:`SemanticResultError` on any denial or failure.
    """
    snapshot = handle.model_copy(deep=True)

    def _current(current_models: dict[str, LoadedModel]) -> LoadedModel:
        loaded = current_models.get(snapshot.model)
        if loaded is None:
            raise _deny()
        if loaded.model_digest != snapshot.model_digest or loaded.policy_digest != snapshot.policy_digest:
            raise _deny()
        return loaded

    async def authorize_read(identity: SemanticRequestIdentity) -> None:
        """Authorize one exposure for the current caller identity."""
        try:
            await _authorize(identity)
        except SemanticResultError:
            raise
        except Exception as exc:  # evaluator/provider failure fails closed
            _LOGGER.warning("Read authorization failed closed: %s", type(exc).__name__)
            raise _deny() from exc

    async def _authorize(identity: SemanticRequestIdentity) -> None:
        if not isinstance(identity, SemanticRequestIdentity):
            raise _deny()
        ctx = identity.ctx
        if (
            snapshot.agent_id != identity.agent_id
            or snapshot.user_id != ctx.user_id
            or snapshot.tenant_id != ctx.tenant_id
            or snapshot.session_id != identity.session_id
            or snapshot.subject_digest != subject_digest(ctx)
        ):
            raise _deny()
        if snapshot.expires_at <= datetime.now(timezone.utc):
            raise _deny()
        loaded = _current(models())
        if loaded.policy.governed:
            visible = {
                member.name
                for member in catalog().visible_members(snapshot.model, frozenset(ctx.roles), authorized=True)
            }
            if not set(snapshot.members).issubset(visible):
                raise _deny()
            driver = loaded.schema.driver
            tables = {f"{driver}:{table}" for table in snapshot.physical_tables}
            columns_outside = [
                column
                for column in snapshot.physical_columns
                if column.rsplit(".", 1)[0] not in snapshot.physical_tables
            ]
            if columns_outside or not tables.issubset({f"{driver}:{t}" for t in loaded.schema.tables}):
                raise _deny()
            try:
                await pbac.authorize(ctx, PhysicalResources(driver=driver, tables=tables), governed=True)
            except Exception as exc:
                raise _deny() from exc
        # Reject reload races: the snapshot must still be current after the awaits.
        _current(models())
        if snapshot.expires_at <= datetime.now(timezone.utc):
            raise _deny()

    return authorize_read
