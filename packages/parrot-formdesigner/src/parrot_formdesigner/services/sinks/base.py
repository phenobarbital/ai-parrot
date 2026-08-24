"""Submission sink ABC, capability enforcement and error taxonomy.

Structured after :class:`parrot_formdesigner.services.blob_storage.
AbstractBlobStorage` — an ABC with a small mandatory surface (capability
declaration, provisioning, write) plus optional operations (read, list)
whose defaults raise so a write-only backend needs no stub overrides.

The error taxonomy defined here is the contract the submit-path
integration (TASK-2428) maps onto HTTP status codes:

- :class:`SinkUnavailableError` -> ``503``
- :class:`SinkNotCapableError` -> ``501``
- :class:`SinkTargetMismatchError` -> ``422``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from parrot_formdesigner.core.persistence import SinkCapability

if TYPE_CHECKING:
    from parrot_formdesigner.core.schema import FormSchema
    from parrot_formdesigner.services.submissions import FormSubmission


class SinkError(Exception):
    """Base class for all submission-sink errors."""


class SinkUnavailableError(SinkError):
    """Destination unreachable or rate-limited.

    HTTP mapping: ``503 Service Unavailable``. The submit path fails the
    request with no fallback and persists nothing anywhere (spec section 1,
    Goal 8).
    """


class SinkNotCapableError(SinkError):
    """Operation not in the sink's declared capability set.

    HTTP mapping: ``501 Not Implemented``. The response should name the
    sink type and its declared capabilities so the caller can tell a
    genuine gap from a bug.
    """


class SinkTargetMismatchError(SinkError):
    """Existing target incompatible with the form (e.g. a changed
    destination or an incompatible existing column type).

    HTTP mapping: ``422 Unprocessable Entity``.
    """


class AbstractSubmissionSink(ABC):
    """Destination for a single form's submissions.

    Concrete backends implement :attr:`capabilities`, :meth:`ensure_target`
    and :meth:`write`. ``read`` and ``list_revisions`` default to raising
    :class:`SinkNotCapableError`, so a write-only backend (e.g. CSV, Google
    Sheets) is fully instantiable without overriding them.
    """

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[SinkCapability]:
        """Return the frozenset of operations this sink supports."""

    @property
    def family(self) -> str:
        """Data family for the submission mapper: ``"tabular"`` or ``"document"``.

        Tabular sinks (Postgres, CSV, Google Sheets, and the ``bigquery``
        ``asyncdb`` driver) receive
        :func:`~parrot_formdesigner.services.sinks.mapper.
        flatten_submission`'s output; document sinks (the ``mongo``/
        ``arango`` ``asyncdb`` drivers) receive
        :func:`~parrot_formdesigner.services.sinks.mapper.nest_submission`'s
        output instead (FEAT-457, TASK-2428's submit-path branch decides
        which mapper to call based on this property). Defaults to
        ``"tabular"`` — the common case; ``AsyncDBSink`` overrides this
        per its configured driver.
        """
        return "tabular"

    @abstractmethod
    async def ensure_target(self, form: FormSchema) -> None:
        """Idempotently create/extend the destination. Additive only.

        Args:
            form: The form whose destination must exist and be up to date.
        """

    @abstractmethod
    async def write(self, submission: FormSubmission, payload: Any) -> str:
        """Persist one submission.

        Args:
            submission: The submission record being persisted.
            payload: The mapped payload to write (tabular row or nested
                document — see the submission mapper).

        Returns:
            The persisted submission's ``submission_id``.
        """

    async def read(self, submission_id: str) -> FormSubmission | None:
        """Retrieve a single submission by id.

        Args:
            submission_id: The submission id to look up.

        Returns:
            The matching submission, or ``None`` if not found.

        Raises:
            SinkNotCapableError: If this sink does not declare ``READ``.
        """
        raise SinkNotCapableError(
            f"{type(self).__name__} does not support read "
            f"(capabilities={sorted(c.value for c in self.capabilities)})"
        )

    async def list_revisions(
        self, root_submission_id: str
    ) -> list[FormSubmission]:
        """List all revisions of a submission.

        Args:
            root_submission_id: The root submission id whose revisions to list.

        Returns:
            The list of revisions, most recent first.

        Raises:
            SinkNotCapableError: If this sink does not declare ``LIST``.
        """
        raise SinkNotCapableError(
            f"{type(self).__name__} does not support list_revisions "
            f"(capabilities={sorted(c.value for c in self.capabilities)})"
        )

    async def close(self) -> None:
        """Release any resources held by this sink. No-op by default."""
        return

    def require(self, capability: SinkCapability) -> None:
        """Raise unless ``capability`` is in this sink's capability set.

        Shared enforcement path for both backends and the HTTP handler.

        Args:
            capability: The capability the caller intends to invoke.

        Raises:
            SinkNotCapableError: If ``capability`` is not declared.
        """
        if capability not in self.capabilities:
            raise SinkNotCapableError(
                f"{type(self).__name__} does not support "
                f"{capability.value!r} "
                f"(capabilities={sorted(c.value for c in self.capabilities)})"
            )
