"""Evidence-bound completion validation (FEAT-538).

A tool succeeding is not evidence that a step is done. This module is
where that principle is enforced: before a step may be marked complete,
its declared evidence is resolved to **exact immutable versions** and
checked against code-registered validators.

Two completion modes, and recall must always be able to tell them apart:

``validated``
    Every validator named by the step's policy must pass, and every
    expected output alias must bind to an exact ``artifact_id@version``.

``agent_asserted``
    At least one *accessible* evidence reference plus the required note.
    This is the weaker source, and it is labelled as such everywhere it
    appears — an asserted completion is a claim, not a proof.

The subtle rule this module exists to get right is the difference
between an **overwrite** and a **mutation**:

- An *overwrite* moves an alias to a **new** version. The old version is
  untouched and remains perfectly valid evidence. Completions that cite
  it stay valid.
- A *mutation* changes the content **behind a version that is already
  bound as evidence**. That invalidates the evidence and must block the
  completion — and, once recorded, reopen anything already completed
  against it.

Getting these two confused in either direction is a correctness failure:
treating an overwrite as mutation would spuriously invalidate sound work,
and treating a mutation as an overwrite would let a step stay "complete"
against content that no longer exists as it was verified.

Validation runs **outside** any long-held lock, then commits against the
same task revision and the same evidence generation it validated. If
either moved underneath it, the result is discarded and the caller
retries — never a stale completion.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from parrot.interfaces.artifact_store import ArtifactStore

from .models import (
    ArtifactAvailability,
    ArtifactDescriptor,
    CompletionMode,
    CompletionSource,
    EvidenceRef,
    RevisionConflict,
    TaskScope,
    TaskState,
    TaskStep,
    UnknownValidatorError,
)

__all__ = (
    "VALIDATOR_NAMES",
    "ValidationOutcome",
    "EvidenceBinding",
    "CompletionValidator",
    "CompletionValidationError",
    "EvidenceMutated",
    "resolve_evidence",
    "validate_completion",
    "VALIDATORS",
)


class CompletionValidationError(Exception):
    """A completion was refused because its evidence does not support it."""


class EvidenceMutated(CompletionValidationError):
    """Content changed behind a version that is already bound as evidence.

    Distinct from an overwrite, which is normal and harmless. This is the
    case where the *same* version no longer matches the fingerprint it
    was verified with, so anything completed against it must be reopened.

    Attributes:
        ref: The version whose content changed.
        expected: The fingerprint recorded when the evidence was bound.
        actual: The fingerprint observed now.
    """

    def __init__(self, ref: EvidenceRef, expected: Optional[str], actual: Optional[str]) -> None:
        """Initialize the error.

        Args:
            ref: The mutated version.
            expected: Fingerprint recorded at binding time.
            actual: Fingerprint observed now.
        """
        self.ref = ref
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"evidence {ref} was mutated in place (fingerprint {expected!r} -> {actual!r}); "
            "this is a mutation, not an overwrite, so the completion cannot stand"
        )


class ValidationOutcome:
    """The result of validating one step's completion.

    Attributes:
        passed: Whether the completion may proceed.
        source: How the completion would be recorded. ``agent_asserted``
            is always the weaker label.
        results: Per-validator ``(name, passed)`` pairs, recorded in the
            journal so replay consumes them rather than re-running them.
        bound: The exact versions the completion binds.
        failures: Human-readable reasons, when it did not pass.
        invalidated: Versions found to have been mutated in place.
    """

    __slots__ = ("passed", "source", "results", "bound", "failures", "invalidated")

    def __init__(
        self,
        *,
        passed: bool,
        source: Optional[CompletionSource],
        results: Sequence[Tuple[str, bool]] = (),
        bound: Sequence[EvidenceRef] = (),
        failures: Sequence[str] = (),
        invalidated: Sequence[EvidenceRef] = (),
    ) -> None:
        """Initialize an outcome.

        Args:
            passed: Whether completion may proceed.
            source: The completion source to record.
            results: Per-validator outcomes.
            bound: Exact versions bound as evidence.
            failures: Reasons for refusal.
            invalidated: Versions mutated in place.
        """
        self.passed = passed
        self.source = source
        self.results: Tuple[Tuple[str, bool], ...] = tuple(results)
        self.bound: Tuple[EvidenceRef, ...] = tuple(bound)
        self.failures: Tuple[str, ...] = tuple(failures)
        self.invalidated: Tuple[EvidenceRef, ...] = tuple(invalidated)

    def __repr__(self) -> str:
        """Return a debug representation."""
        return (
            f"ValidationOutcome(passed={self.passed}, source={self.source}, "
            f"bound={len(self.bound)}, failures={len(self.failures)})"
        )


class EvidenceBinding:
    """One resolved piece of evidence.

    Attributes:
        ref: The exact version.
        descriptor: Its read projection at resolution time.
        alias: The alias it was resolved from, when it was.
    """

    __slots__ = ("ref", "descriptor", "alias")

    def __init__(self, ref: EvidenceRef, descriptor: ArtifactDescriptor, alias: Optional[str] = None) -> None:
        """Initialize a binding.

        Args:
            ref: The exact version.
            descriptor: Its descriptor.
            alias: The alias resolved from, if any.
        """
        self.ref = ref
        self.descriptor = descriptor
        self.alias = alias


#: Signature every registered validator satisfies.
CompletionValidator = Callable[["_ValidationContext"], Awaitable[bool]]


class _ValidationContext:
    """Everything a validator is allowed to look at.

    Deliberately narrow: a validator sees the resolved bindings and the
    task state, never the store's internals and never a way to mutate
    anything.

    Attributes:
        scope: Trusted runtime scope.
        state: The task projection being validated against.
        step: The step whose completion is proposed.
        bindings: Resolved evidence.
        artifacts: The artifact store, for read-only checks.
    """

    __slots__ = ("scope", "state", "step", "bindings", "artifacts")

    def __init__(
        self,
        scope: TaskScope,
        state: TaskState,
        step: TaskStep,
        bindings: Sequence[EvidenceBinding],
        artifacts: ArtifactStore,
    ) -> None:
        """Initialize a validation context.

        Args:
            scope: Trusted runtime scope.
            state: The task projection.
            step: The step being completed.
            bindings: Resolved evidence.
            artifacts: The artifact store.
        """
        self.scope = scope
        self.state = state
        self.step = step
        self.bindings: Tuple[EvidenceBinding, ...] = tuple(bindings)
        self.artifacts = artifacts


# ─────────────────────────────────────────────────────────────
# Built-in validators
# ─────────────────────────────────────────────────────────────


async def _artifact_exists(ctx: _ValidationContext) -> bool:
    """Every bound version resolves and its payload is reachable.

    An ``expired`` or ``missing`` payload fails: a step cannot be
    complete on evidence nobody can look at.

    Args:
        ctx: The validation context.

    Returns:
        Whether every binding exists and is available.
    """
    if not ctx.bindings:
        return False
    return all(
        b.descriptor.availability in (ArtifactAvailability.MEMORY, ArtifactAvailability.PERSISTED)
        and not b.descriptor.invalidated
        for b in ctx.bindings
    )


async def _artifact_fingerprint_matches(ctx: _ValidationContext) -> bool:
    """Every bound version carries a fingerprint that actually proves something.

    An **unverifiable** artifact can never satisfy this validator, even
    though it may carry a computable fingerprint — nested mutable content
    hashes via its ``repr``, which is not integrity proof (TASK-2970).

    Args:
        ctx: The validation context.

    Returns:
        Whether every binding is verifiable and fingerprinted.
    """
    if not ctx.bindings:
        return False
    return all(b.descriptor.evidence_verifiable and bool(b.descriptor.fingerprint) for b in ctx.bindings)


async def _artifact_non_empty(ctx: _ValidationContext) -> bool:
    """Every bound version has content, judged by CAPTURED shape.

    Deliberately uses the captured shape rather than loading the payload:
    a validator that loaded data to check whether it is empty would make
    completion arbitrarily expensive and would defeat the byte ceilings.

    Args:
        ctx: The validation context.

    Returns:
        Whether every binding is non-empty.
    """
    if not ctx.bindings:
        return False
    for binding in ctx.bindings:
        shape = binding.descriptor.shape
        if shape is not None:
            if not shape or shape[0] == 0:
                return False
        elif not binding.descriptor.byte_size:
            return False
    return True


async def _no_pending_tool_failures(ctx: _ValidationContext) -> bool:
    """The step has no unresolved failure or blocked reason outstanding.

    An unresolved outcome is exactly the thing that must not be papered
    over by declaring the step done.

    Args:
        ctx: The validation context.

    Returns:
        Whether the step is clear of pending failures.
    """
    return ctx.step.blocked_reason is None


#: The code-registered validators. A policy naming anything outside this
#: mapping is rejected: an unknown validator must never be treated as a
#: vacuous pass, which would silently downgrade `validated` completion.
VALIDATORS: Dict[str, CompletionValidator] = {
    "artifact_exists": _artifact_exists,
    "artifact_fingerprint_matches": _artifact_fingerprint_matches,
    "artifact_non_empty": _artifact_non_empty,
    "no_pending_tool_failures": _no_pending_tool_failures,
}

#: Names of every registered validator, for configuration validation.
VALIDATOR_NAMES: Tuple[str, ...] = tuple(sorted(VALIDATORS))


# ─────────────────────────────────────────────────────────────
# Evidence resolution
# ─────────────────────────────────────────────────────────────


async def resolve_evidence(
    artifacts: ArtifactStore,
    scope: TaskScope,
    *,
    task_id: str,
    refs: Sequence[EvidenceRef] = (),
    aliases: Sequence[str] = (),
) -> List[EvidenceBinding]:
    """Resolve evidence to exact versions, **once**.

    Aliases are resolved a single time and pinned to the version they
    named at that moment. Resolving twice would open a window in which an
    overwrite between the two reads silently changed what was validated.

    Args:
        artifacts: The artifact store.
        scope: Trusted runtime scope.
        task_id: The owning task, which also scopes the alias namespace.
        refs: Exact versions supplied by the caller.
        aliases: Aliases to resolve and pin.

    Returns:
        The resolved bindings, in the order requested: refs first, then
        aliases.

    Raises:
        CompletionValidationError: If a reference or alias cannot be
            resolved in this scope.
    """
    bindings: List[EvidenceBinding] = []

    for ref in refs:
        descriptor = await artifacts.get_version(scope, ref, task_id=task_id)
        if descriptor is None:
            raise CompletionValidationError(f"evidence {ref} does not resolve in this scope")
        bindings.append(EvidenceBinding(ref, descriptor))

    for alias in aliases:
        descriptor = await artifacts.get_current(scope, alias, task_id=task_id)
        if descriptor is None:
            raise CompletionValidationError(
                f"expected output {alias!r} has not been produced; it resolves to no artifact"
            )
        bindings.append(EvidenceBinding(descriptor.ref, descriptor, alias=alias))

    return bindings


async def _detect_mutation(
    artifacts: ArtifactStore,
    scope: TaskScope,
    binding: EvidenceBinding,
    *,
    task_id: str,
) -> Optional[EvidenceMutated]:
    """Detect in-place mutation of an already-bound version.

    This is the overwrite/mutation distinction in code. The version is
    re-read and its fingerprint compared with the one captured at
    resolution. A **different version** now sitting behind the alias is an
    overwrite and is explicitly *not* a mutation — the old version is
    untouched and remains valid evidence.

    Args:
        artifacts: The artifact store.
        scope: Trusted runtime scope.
        binding: The binding to re-check.
        task_id: The owning task.

    Returns:
        An :class:`EvidenceMutated` describing the change, or ``None``
        when the version is unchanged.
    """
    current = await artifacts.get_version(scope, binding.ref, task_id=task_id)
    if current is None:
        return EvidenceMutated(binding.ref, binding.descriptor.fingerprint, None)
    if current.invalidated and not binding.descriptor.invalidated:
        return EvidenceMutated(binding.ref, binding.descriptor.fingerprint, current.fingerprint)
    if binding.descriptor.fingerprint and current.fingerprint != binding.descriptor.fingerprint:
        return EvidenceMutated(binding.ref, binding.descriptor.fingerprint, current.fingerprint)
    return None


# ─────────────────────────────────────────────────────────────
# Completion validation
# ─────────────────────────────────────────────────────────────


async def validate_completion(
    artifacts: ArtifactStore,
    scope: TaskScope,
    state: TaskState,
    step_id: str,
    *,
    evidence_refs: Sequence[EvidenceRef] = (),
    note: Optional[str] = None,
) -> ValidationOutcome:
    """Decide whether a step's completion is supported by its evidence.

    Runs **outside** any long-held lock. The caller commits the result
    against the same task revision and the same evidence it validated;
    :func:`assert_unchanged` re-checks both.

    Args:
        artifacts: The artifact store.
        scope: Trusted runtime scope.
        state: The task projection at validation time.
        step_id: The step being completed.
        evidence_refs: Exact versions the caller offers as evidence.
        note: The completion note.

    Returns:
        A :class:`ValidationOutcome`. ``passed`` is ``False`` with
        populated ``failures`` rather than raising for an *unsupported*
        completion — a refusal is an ordinary answer, not an exception.

    Raises:
        UnknownValidatorError: If the policy names a validator that is
            not code-registered. Never treated as a vacuous pass.
        EvidenceMutated: If content changed behind an already-bound
            version. This is not an ordinary refusal: it means existing
            completions must be reopened.
        CompletionValidationError: If evidence cannot be resolved.
    """
    step = state.steps_by_id.get(step_id)
    if step is None:
        raise CompletionValidationError(f"unknown step {step_id!r}")

    policy = step.completion_policy

    unknown = [name for name in policy.validators if name not in VALIDATORS]
    if unknown:
        raise UnknownValidatorError(
            f"step {step_id} names unregistered validators: {sorted(unknown)}; "
            "an unknown validator is never a vacuous pass"
        )

    failures: List[str] = []
    if policy.require_note and not note:
        failures.append("a completion note is required")

    bindings = await resolve_evidence(
        artifacts, scope, task_id=state.task_id, refs=evidence_refs, aliases=policy.expected_outputs
    )

    # Mutation of an already-bound version blocks completion outright.
    invalidated: List[EvidenceRef] = []
    for binding in bindings:
        mutation = await _detect_mutation(artifacts, scope, binding, task_id=state.task_id)
        if mutation is not None:
            invalidated.append(binding.ref)
    if invalidated:
        raise EvidenceMutated(
            invalidated[0],
            next(b.descriptor.fingerprint for b in bindings if b.ref == invalidated[0]),
            None,
        )

    if policy.mode is CompletionMode.VALIDATED:
        return await _validate_strict(artifacts, scope, state, step, bindings, policy, failures)
    return _validate_asserted(bindings, failures)


async def _validate_strict(
    artifacts: ArtifactStore,
    scope: TaskScope,
    state: TaskState,
    step: TaskStep,
    bindings: Sequence[EvidenceBinding],
    policy: Any,
    failures: List[str],
) -> ValidationOutcome:
    """Run every registered validator the policy names.

    Args:
        artifacts: The artifact store.
        scope: Trusted runtime scope.
        state: The task projection.
        step: The step being completed.
        bindings: Resolved evidence.
        policy: The step's completion policy.
        failures: Failures accumulated so far.

    Returns:
        The outcome.
    """
    ctx = _ValidationContext(scope, state, step, bindings, artifacts)
    results: List[Tuple[str, bool]] = []
    for name in policy.validators:
        passed = await VALIDATORS[name](ctx)
        results.append((name, passed))
        if not passed:
            failures.append(f"validator {name!r} did not pass")

    missing = [alias for alias in policy.expected_outputs if not any(b.alias == alias for b in bindings)]
    if missing:
        failures.append(f"expected outputs did not bind: {sorted(missing)}")

    return ValidationOutcome(
        passed=not failures,
        source=CompletionSource.VALIDATED if not failures else None,
        results=results,
        bound=[b.ref for b in bindings],
        failures=failures,
    )


def _validate_asserted(bindings: Sequence[EvidenceBinding], failures: List[str]) -> ValidationOutcome:
    """Apply the weaker ``agent_asserted`` rules.

    Requires at least one *accessible* evidence reference plus the note.
    An assertion backed by nothing reachable is not an assertion, it is a
    guess.

    Args:
        bindings: Resolved evidence.
        failures: Failures accumulated so far.

    Returns:
        The outcome, labelled ``agent_asserted`` when it passes.
    """
    accessible = [
        b
        for b in bindings
        if b.descriptor.availability in (ArtifactAvailability.MEMORY, ArtifactAvailability.PERSISTED)
        and not b.descriptor.invalidated
    ]
    if not accessible:
        failures.append("asserted completion requires at least one accessible evidence reference")

    return ValidationOutcome(
        passed=not failures,
        source=CompletionSource.AGENT_ASSERTED if not failures else None,
        results=(),
        bound=[b.ref for b in bindings],
        failures=failures,
    )


async def assert_unchanged(
    artifacts: ArtifactStore,
    scope: TaskScope,
    *,
    task_id: str,
    validated_revision: int,
    current_revision: int,
    bound: Sequence[EvidenceRef],
    fingerprints: Sequence[Optional[str]],
) -> None:
    """Re-check, at commit time, everything validation depended on.

    Validation deliberately runs outside long-held locks, which means the
    world can move underneath it. This is the guard that turns that into
    a retry rather than a stale completion.

    Args:
        artifacts: The artifact store.
        scope: Trusted runtime scope.
        task_id: The owning task.
        validated_revision: Task revision at validation time.
        current_revision: Task revision now.
        bound: The versions the outcome bound.
        fingerprints: Their fingerprints at validation time, positionally
            aligned with ``bound``.

    Raises:
        RevisionConflict: If the task moved. The caller revalidates.
        EvidenceMutated: If any bound version's content changed.
    """
    if validated_revision != current_revision:
        raise RevisionConflict(task_id, validated_revision, current_revision)

    for ref, expected in zip(bound, fingerprints):
        descriptor = await artifacts.get_version(scope, ref, task_id=task_id)
        if descriptor is None:
            raise EvidenceMutated(ref, expected, None)
        # Invalidation is checked SEPARATELY from the fingerprint. An
        # invalidated version keeps its fingerprint, so comparing digests
        # alone would let a completion commit against evidence that was
        # invalidated while it was being validated.
        if descriptor.invalidated:
            raise EvidenceMutated(ref, expected, descriptor.fingerprint)
        if expected is not None and descriptor.fingerprint != expected:
            raise EvidenceMutated(ref, expected, descriptor.fingerprint)
