"""Generation-bound REPL materialization of exact evidence (FEAT-538).

Recovering a task must not silently drag its data back into a worker.
This module is the **only** way an artifact version becomes a live
variable again, and it is deliberately narrow:

- **Explicit only.** Nothing here runs as a side effect of recall, of a
  descriptor read, or of listing artifacts. Recall is read-only and
  bounded (AC10); if describing a binding could materialize one, a single
  recall could pull megabytes back into a worker.
- **Exact versions only.** :meth:`ReplBindingResolver.load` takes an
  ``artifact_id`` and a ``version``. A bare alias is mutable and is not
  evidence, so there is no alias-shaped entry point.
- **Verified before bound.** The materialized payload is re-fingerprinted
  and compared with the descriptor's recorded fingerprint *before* the
  value is injected. Binding content that no longer matches what was
  fingerprinted would break the evidence chain the whole feature exists
  to protect.
- **Strict transport only.** DataFrames travel as Arrow IPC and JSON/text
  as safe JSON, via the strict paths TASK-2992 added. There is no pickle
  fallback for task evidence, and a value the strict path refuses is
  refused here too.
- **Never a namespace restore.** One named variable per explicit request.
  Arbitrary namespaces are never reconstructed and saved code is never
  replayed.

Stale bindings versus lost bytes
--------------------------------

These are different failures and this module never conflates them. A
worker restarting invalidates its **binding** — the variable is gone from
that process — but the artifact is still perfectly locatable in the
store. Every refusal therefore reports ``artifact_locatable``, so a
caller can tell "rebind this into the new worker" from "this evidence is
actually gone".
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from parrot.interfaces.artifact_store import ArtifactStore, PayloadRefusal
from parrot.tools.repl_worker.protocol import TransportEnvelope
from parrot.tools.repl_worker.transport import StrictTransportError, ensure_strict_json
from pydantic import BaseModel, ConfigDict, Field

from .config import TaskMemoryConfig
from .models import ArtifactAvailability, ArtifactDescriptor, ArtifactKind, EvidenceRef, Limits, ReplBinding, TaskScope
from .snapshots import canonical_json_bytes, fingerprint_bytes, fingerprint_dataframe

__all__ = (
    "BindingStatus",
    "ReplLoadRefusal",
    "ReplLoadResult",
    "WorkerLike",
    "ReplBindingResolver",
)

logger = logging.getLogger(__name__)


class BindingStatus(str, Enum):
    """Outcome of a resolve or load request."""

    #: The value is live in the worker under a generation-bound binding.
    BOUND = "bound"
    #: The requested worker generation is not the live one. The binding is
    #: stale; the artifact itself is untouched and still locatable.
    BINDING_INVALID = "binding_invalid"
    #: The load was refused before anything was injected.
    REFUSED = "refused"


class ReplLoadRefusal(str):
    """Why a load was refused.

    A plain ``str`` subclass, matching :class:`PayloadRefusal`, so the
    reason survives JSON and reaches a tool result without a second enum
    to keep in sync.
    """

    #: The version does not resolve in the caller's scope.
    FOREIGN_SCOPE = "foreign_scope"
    #: No such artifact version exists at all.
    UNKNOWN_VERSION = "unknown_version"
    #: The payload exceeds the configured or requested byte ceiling.
    TOO_LARGE = "too_large"
    #: The materialized content no longer matches its recorded fingerprint.
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    #: The evidence kind has no safe strict-transport representation.
    UNSUPPORTED = "unsupported"
    #: The version carries no fingerprint that proves anything.
    UNVERIFIABLE = "unverifiable"
    #: The version's evidence was invalidated.
    INVALIDATED = "invalidated"
    #: The version's bytes are gone or expired.
    MISSING = "missing"
    #: The strict transport refused the value.
    STRICT_REFUSED = "strict_refused"


class ReplLoadResult(BaseModel):
    """The result of a resolve or load request.

    Attributes:
        status: Whether the value was bound, the binding is stale, or the
            load was refused.
        ref: The exact version requested.
        binding: The generation-bound binding, present only on
            :attr:`BindingStatus.BOUND`.
        refusal: A :class:`ReplLoadRefusal` reason, when refused.
        artifact_locatable: Whether the artifact itself can still be
            found in the store. ``True`` for a stale binding — a worker
            restart loses the variable, **not** the evidence. This is the
            field that stops the two failures being conflated.
        byte_size: Recorded payload size, reported even on refusal so a
            caller can see how far over a ceiling it was.
        guidance: What the caller should do instead, when refused.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: BindingStatus
    ref: EvidenceRef
    binding: Optional[ReplBinding] = None
    refusal: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    artifact_locatable: bool = False
    byte_size: Optional[int] = Field(default=None, ge=0)
    guidance: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)

    @property
    def ok(self) -> bool:
        """Whether the value is live in the worker."""
        return self.status is BindingStatus.BOUND


@runtime_checkable
class WorkerLike(Protocol):
    """The worker surface this resolver needs.

    Both :class:`~parrot.tools.repl_worker.handle.WorkerHandle` and
    :class:`~parrot.tools.repl_worker.inprocess.InProcessHandle` satisfy
    it. Depending on the protocol rather than either class keeps the
    resolver usable in both execution modes without branching.
    """

    @property
    def generation(self) -> str:
        """Stable identity of this worker generation."""
        ...

    async def inject_dataframe(
        self,
        name: str,
        df: Any,
        *,
        strict: bool = False,
        envelope: Any = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        """Bind a DataFrame into the worker namespace."""
        ...

    async def set_var(self, name: str, value: Any) -> None:
        """Bind one namespace variable."""
        ...


#: Refusals that describe the *binding*, not the artifact. On any of
#: these the evidence itself is still locatable.
_LOCATABLE_REFUSALS = frozenset(
    {
        ReplLoadRefusal.TOO_LARGE,
        ReplLoadRefusal.UNSUPPORTED,
        ReplLoadRefusal.UNVERIFIABLE,
        ReplLoadRefusal.STRICT_REFUSED,
        ReplLoadRefusal.FINGERPRINT_MISMATCH,
        ReplLoadRefusal.INVALIDATED,
    }
)


class ReplBindingResolver:
    """Materializes exact artifact versions into a live REPL worker.

    Args:
        artifacts: The artifact store to resolve versions from.
        config: Byte-ceiling configuration. Defaults to
            :class:`TaskMemoryConfig`'s own defaults.
    """

    def __init__(self, artifacts: ArtifactStore, config: Optional[TaskMemoryConfig] = None) -> None:
        """Initialize the resolver.

        Args:
            artifacts: The artifact store.
            config: Byte-ceiling configuration.
        """
        self._artifacts = artifacts
        self._config = config or TaskMemoryConfig()

    # ── read-only ────────────────────────────────────────────────────

    async def describe(
        self,
        scope: TaskScope,
        artifact_id: str,
        version: int,
        worker_session_id: Optional[str] = None,
        *,
        task_id: Optional[str] = None,
    ) -> ReplLoadResult:
        """Report whether a binding would be valid, **without materializing**.

        This is what a descriptor read or a recall may call. It performs
        no injection and loads no payload, so it can never become a way
        for a read path to pull data back into a worker.

        Args:
            scope: Trusted runtime scope.
            artifact_id: Artifact identity.
            version: Exact version.
            worker_session_id: The worker generation the caller believes
                holds the binding. ``None`` asks only about the artifact.
            task_id: Owning task, scoping the lookup.

        Returns:
            A :class:`ReplLoadResult` that never carries a payload.
        """
        ref = EvidenceRef(artifact_id=artifact_id, version=version)
        descriptor = await self._artifacts.get_version(scope, ref, task_id=task_id)
        if descriptor is None:
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.UNKNOWN_VERSION,
                artifact_locatable=False,
                guidance="no such artifact version in this scope",
            )

        gate = self._gate(descriptor, ref)
        if gate is not None:
            return gate

        binding = descriptor.repl_binding
        if worker_session_id is not None and (binding is None or binding.worker_session_id != worker_session_id):
            return self._stale(ref, descriptor)

        return ReplLoadResult(
            status=BindingStatus.BOUND if binding is not None else BindingStatus.REFUSED,
            ref=ref,
            binding=binding,
            refusal=None if binding is not None else ReplLoadRefusal.MISSING,
            artifact_locatable=True,
            byte_size=descriptor.byte_size,
            guidance=None if binding is not None else "no live binding; call load() to materialize it",
        )

    # ── explicit materialization ─────────────────────────────────────

    async def load(
        self,
        scope: TaskScope,
        artifact_id: str,
        version: int,
        worker_session_id: Optional[str] = None,
        *,
        worker: WorkerLike,
        variable_name: Optional[str] = None,
        task_id: Optional[str] = None,
        max_bytes: Optional[int] = None,
        fencing_token: Optional[int] = None,
    ) -> ReplLoadResult:
        """Materialize one exact version into ``worker``, on explicit request.

        The order of checks is the guarantee. Scope, existence,
        availability, kind, verifiability and the byte ceiling are all
        settled **before** anything is loaded; the fingerprint is verified
        **before** anything is injected; and the binding is published only
        **after** the worker has acknowledged the injection.

        Args:
            scope: Trusted runtime scope. A version belonging to another
                scope reads as absent.
            artifact_id: Artifact identity.
            version: Exact version. There is no alias entry point: a bare
                alias is mutable and is not evidence.
            worker_session_id: The worker generation the caller expects.
                When it does not match ``worker.generation`` the request
                is reported as :attr:`BindingStatus.BINDING_INVALID` and
                **nothing is injected** — the caller then retries against
                the live generation to rebind. ``None`` binds to whatever
                generation ``worker`` currently is.
            worker: The live worker to bind into.
            variable_name: Name to bind under. Defaults to the artifact's
                alias, then to its id.
            task_id: Owning task, scoping the lookup.
            max_bytes: Caller's byte ceiling. Clamped by the configured
                hard ceiling — a caller may lower it, never raise it.
            fencing_token: Monotonic token carried in the envelope so a
                superseded owner's late reply can be rejected.

        Returns:
            A :class:`ReplLoadResult`. On success it carries a
            generation-bound :class:`ReplBinding`.
        """
        ref = EvidenceRef(artifact_id=artifact_id, version=version)

        descriptor = await self._artifacts.get_version(scope, ref, task_id=task_id)
        if descriptor is None:
            # Absent and foreign are the same answer on purpose: telling
            # them apart would make this an existence oracle for another
            # scope's artifact ids.
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.UNKNOWN_VERSION,
                artifact_locatable=False,
                guidance="no such artifact version in this scope",
            )

        gate = self._gate(descriptor, ref)
        if gate is not None:
            return gate

        # A generation mismatch is settled BEFORE any load: materializing
        # into a worker the caller did not mean to target would be worse
        # than refusing.
        if worker_session_id is not None and worker_session_id != worker.generation:
            return self._stale(ref, descriptor)

        ceiling = self._config.resolve_rehydrate_bytes(max_bytes)
        if ceiling == 0:
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.TOO_LARGE,
                artifact_locatable=True,
                byte_size=descriptor.byte_size,
                guidance="rehydration is disabled (max_rehydrate_bytes=0)",
            )

        payload_result = await self._artifacts.load_payload(scope, ref, max_bytes=ceiling)
        if not payload_result.ok:
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=_map_payload_refusal(payload_result.refusal),
                artifact_locatable=payload_result.refusal not in (PayloadRefusal.MISSING, PayloadRefusal.EXPIRED),
                byte_size=payload_result.byte_size or descriptor.byte_size,
                guidance=payload_result.guidance or "the payload exceeds the configured rehydration ceiling",
            )

        value = payload_result.payload

        # Verify BEFORE binding. Content that no longer matches its
        # recorded fingerprint must never become a live variable — that is
        # exactly how a completed step would end up citing evidence that
        # is not what was verified.
        actual = _recompute_fingerprint(value, descriptor.kind)
        if actual is None or actual != descriptor.fingerprint:
            logger.warning(
                "[task-memory] refusing to bind %s: fingerprint %s != recorded %s",
                ref,
                actual,
                descriptor.fingerprint,
            )
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.FINGERPRINT_MISMATCH,
                artifact_locatable=True,
                byte_size=descriptor.byte_size,
                guidance="the stored content no longer matches its recorded fingerprint",
            )

        name = variable_name or descriptor.alias or artifact_id
        envelope = TransportEnvelope(
            scope_key=scope.cache_key(),
            task_id=task_id or descriptor.task_id,
            artifact_id=artifact_id,
            version=version,
            worker_generation=worker.generation,
            fencing_token=fencing_token,
        )

        try:
            if descriptor.kind is ArtifactKind.DATAFRAME:
                await worker.inject_dataframe(name, value, strict=True, envelope=envelope, max_bytes=ceiling)
            else:
                # JSON and text travel as safe JSON. `ensure_strict_json`
                # refuses anything that would not round-trip exactly,
                # before any pickle payload could be constructed.
                ensure_strict_json(value, name=name, max_bytes=ceiling)
                await worker.set_var(name, value)
        except StrictTransportError as exc:
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.STRICT_REFUSED,
                artifact_locatable=True,
                byte_size=descriptor.byte_size,
                guidance=str(exc),
            )

        # Published only after the worker acknowledged the injection.
        return ReplLoadResult(
            status=BindingStatus.BOUND,
            ref=ref,
            binding=ReplBinding(
                worker_session_id=worker.generation,
                worker_generation=0,
                variable_name=name,
                ref=ref,
            ),
            artifact_locatable=True,
            byte_size=payload_result.byte_size or descriptor.byte_size,
        )

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _stale(ref: EvidenceRef, descriptor: ArtifactDescriptor) -> ReplLoadResult:
        """Report a stale binding without touching the artifact.

        Args:
            ref: The requested version.
            descriptor: Its descriptor.

        Returns:
            A ``binding_invalid`` result that still reports the artifact
            as locatable.
        """
        return ReplLoadResult(
            status=BindingStatus.BINDING_INVALID,
            ref=ref,
            binding=None,
            refusal=None,
            artifact_locatable=True,
            byte_size=descriptor.byte_size,
            guidance=(
                "the worker generation this binding was made against is gone; "
                "the artifact is unaffected — call load() again to rebind it"
            ),
        )

    @staticmethod
    def _gate(descriptor: ArtifactDescriptor, ref: EvidenceRef) -> Optional[ReplLoadResult]:
        """Refuse a version that cannot be safe evidence, before any load.

        Args:
            descriptor: The version's descriptor.
            ref: The requested version.

        Returns:
            A refusal, or ``None`` when the version may proceed.
        """
        if descriptor.invalidated:
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.INVALIDATED,
                artifact_locatable=True,
                byte_size=descriptor.byte_size,
                guidance="this version's evidence was invalidated",
            )
        if descriptor.availability in (ArtifactAvailability.MISSING, ArtifactAvailability.EXPIRED):
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.MISSING,
                artifact_locatable=False,
                byte_size=descriptor.byte_size,
                guidance=f"the payload is {descriptor.availability.value}",
            )
        if not descriptor.kind.is_supported_evidence:
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.UNSUPPORTED,
                artifact_locatable=True,
                byte_size=descriptor.byte_size,
                guidance=(
                    f"{descriptor.kind.value} has no safe strict-transport representation; "
                    "strict mode never creates a pickle payload"
                ),
            )
        if not descriptor.evidence_verifiable or not descriptor.fingerprint:
            return ReplLoadResult(
                status=BindingStatus.REFUSED,
                ref=ref,
                refusal=ReplLoadRefusal.UNVERIFIABLE,
                artifact_locatable=True,
                byte_size=descriptor.byte_size,
                guidance=(
                    "this version carries no fingerprint that proves its content, " "so it cannot be bound as evidence"
                ),
            )
        return None


def _map_payload_refusal(refusal: Optional[str]) -> str:
    """Translate an artifact-store refusal into a resolver refusal.

    Args:
        refusal: The store's reason.

    Returns:
        The corresponding :class:`ReplLoadRefusal`.
    """
    return {
        PayloadRefusal.TOO_LARGE: ReplLoadRefusal.TOO_LARGE,
        PayloadRefusal.MISSING: ReplLoadRefusal.MISSING,
        PayloadRefusal.EXPIRED: ReplLoadRefusal.MISSING,
        PayloadRefusal.UNSUPPORTED: ReplLoadRefusal.UNSUPPORTED,
        PayloadRefusal.INVALIDATED: ReplLoadRefusal.INVALIDATED,
    }.get(refusal or "", ReplLoadRefusal.MISSING)


def _recompute_fingerprint(value: Any, kind: ArtifactKind) -> Optional[str]:
    """Re-derive a value's fingerprint the same way the snapshot layer did.

    Deliberately reuses :mod:`.snapshots` rather than re-deriving the
    canonical forms: two independent implementations of "the canonical
    bytes" would eventually disagree, and the disagreement would surface
    as a spurious mutation report.

    Args:
        value: The materialized payload.
        kind: Its evidence kind.

    Returns:
        The fingerprint, or ``None`` when the value cannot be
        fingerprinted at all.
    """
    try:
        if kind is ArtifactKind.DATAFRAME:
            return fingerprint_dataframe(value)
        if kind is ArtifactKind.TEXT:
            return fingerprint_bytes(str(value).encode("utf-8"))
        if kind is ArtifactKind.JSON:
            return fingerprint_bytes(canonical_json_bytes(value))
    except Exception:  # noqa: BLE001 — an unfingerprintable value is a refusal, not a crash
        return None
    return None
