"""Error types for AgentsFlow state checkpointing (FEAT-399)."""

from __future__ import annotations


class FlowLockedError(RuntimeError):
    """Raised when a resume/suspend is attempted on a flow_id that already
    holds an active resume lease (concurrent resume protection)."""


class CheckpointNotFoundError(LookupError):
    """Raised when a requested checkpoint (or flow) cannot be found —
    e.g. TTL-expired, deleted, or never written."""


class FlowNotExportableError(ValueError):
    """Raised by `AgentsFlow.to_definition()` when the graph contains a
    node type that is not registered in `NODE_REGISTRY` and therefore
    cannot round-trip through a `FlowDefinition` export."""


class CheckpointPersistenceError(RuntimeError):
    """A required checkpoint could not be encoded or persisted.

    Raised by `FlowCheckpointer.checkpoint()` (the awaited, required-mode
    write path — spec §2/§7) when assembling the snapshot or writing it to
    the checkpoint store fails. Unlike the fire-and-forget listener path
    (`make_listener()`), which always logs and swallows write failures,
    required mode must surface them to the caller so no downstream side
    effect starts before Redis durably records the upstream completion.
    """


class CheckpointFingerprintMismatchError(RuntimeError):
    """A `run_id` was reused with incompatible immutable input metadata.

    Raised by `AgentsFlow.resume(expected_input=...)` when the loaded
    checkpoint's `FlowCheckpoint.input_metadata` does not match the
    caller-supplied `CheckpointInputMetadata` — e.g. the workflow kind,
    topology version, or input fingerprint changed since the checkpoint was
    written. Reusing the same `run_id` across incompatible inputs must fail
    loudly rather than silently resuming the wrong run.
    """
