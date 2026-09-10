"""Targeted patch generation for already-decided TASK work (FEAT-543).

:class:`TargetedWriterToolkit` delegates *implementation*, never *design*.
It accepts a TASK file whose ``## Delegation Contract`` proves the design is
already complete, builds a bounded prompt from that packet alone, asks a
configured :class:`~parrot.clients.base.AbstractClient` for a unified diff,
validates the diff against the approved scope and the expected source bytes,
and stores it as an artifact.

Safety properties:

* **No repository exploration and no design mode.** The delegate sees only
  the packet, its approved reference slices and its decided implementation
  blocks — never whole files and never host conversation history.
* **An incomplete or stale contract costs zero model calls.** Validation
  runs first; a `ContractError` returns to the thinking model unchanged.
* **No silent model switching.** A client whose fallback model is enabled is
  refused at construction, and a response reporting a substituted model
  aborts the operation with no repair attempt.
* **Generation never touches a target file.** The result is an artifact id
  plus a patch path; the thinking model reviews the hunks with the bounded
  reader and only then calls ``writer_apply``.

Provider satellites stay lazy: importing this module pulls in no AWS SDK.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

from parrot.tools.decorators import tool_schema
from pydantic import BaseModel

from .base import OptimizationToolkitBase
from .contracts import ContractError, ValidatedContract, render_prompt_sections, validate_contract
from .git import LocalGitToolkit
from .models import (
    DelegationPacket,
    OperationResult,
    PatchManifest,
    WriterApplyArgs,
    WriterGenerateArgs,
    WriterLimits,
)
from .patches import (
    ApplyJournal,
    ArtifactStore,
    JournalEntry,
    PatchError,
    apply_in_memory,
    check_scope,
    normalize_patch,
    parse_patch,
)
from .policy import LockTimeoutError, WorktreeLock, compact_json
from .reader import sha256_stream, stat_regular

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps provider imports lazy
    from parrot.clients.base import AbstractClient

__all__ = ("SYSTEM_PROMPT", "TargetedWriterToolkit", "build_prompt", "build_repair_prompt")

#: Default permissions for a newly created file.
_CREATE_MODE = 0o644

#: Instructions for the delegate. It implements decisions that are already
#: made; it does not design, explore, or choose files.
SYSTEM_PROMPT = """You are a code-writing delegate operating under a strict contract.

The design is ALREADY DECIDED. Your only job is to express the decided
implementation as a unified diff. You must not design, explore, or improve
anything.

Rules:
1. Output ONLY a unified diff. No prose, no explanation, no markdown fences,
   no commentary before or after the diff.
2. Use exactly this header form:
       --- a/<path>
       +++ b/<path>
   and for a new file:
       --- /dev/null
       +++ b/<path>
3. Patch ONLY the target paths listed in the packet. Never touch any other
   file, for any reason.
4. Where an implementation block is the complete content of a new file, use
   it verbatim.
5. Context lines must match the provided source excerpts EXACTLY, including
   indentation and blank lines. There is no fuzzy matching.
6. Never emit a deletion, rename, copy, mode change, binary payload or
   submodule update. Only file creation and modification are supported.
7. Never invent an API, import, or behaviour that is not already specified.
   If something is genuinely underspecified, emit no diff at all.
8. Never include shell commands, test invocations, or instructions."""


def build_prompt(contract: ValidatedContract) -> str:
    """Build the delegation prompt from approved content only.

    Args:
        contract: The validated contract.

    Returns:
        The prompt text: packet, references, implementation blocks and
        acceptance criteria, and nothing else.
    """
    sections = render_prompt_sections(contract)
    return "\n\n".join(
        [
            f"# Implement {contract.packet.task_id}",
            sections["packet"],
            sections["references"],
            sections["blocks"],
            sections["acceptance"],
            "## Output\n\nReturn only the unified diff implementing the packet's targets.",
        ]
    )


def build_repair_prompt(contract: ValidatedContract, previous_patch: str, error: PatchError) -> str:
    """Build the single permitted repair prompt.

    The delegate gets the same approved context plus a bounded diagnostic —
    never additional repository content, and never a second chance at a
    contract that was itself invalid.

    Args:
        contract: The validated contract.
        previous_patch: The rejected patch text.
        error: The rejection.

    Returns:
        The repair prompt text.
    """
    excerpt = previous_patch[:2000]
    return "\n\n".join(
        [
            build_prompt(contract),
            "## Your previous attempt was rejected",
            f"Rejection code: {error.code}",
            f"Details: {compact_json(error.details)}",
            "Rejected output (truncated):\n\n```\n" + excerpt + "\n```",
            "Return a corrected unified diff. Output only the diff.",
        ]
    )


class TargetedWriterToolkit(OptimizationToolkitBase):
    """Generate and apply validated patches for already-decided TASK work.

    Example:
        >>> toolkit = TargetedWriterToolkit(repo_root="/repo", llm_client=client)
        >>> result = await toolkit.writer_generate("sdd/tasks/active/TASK-1-x.md")
        >>> result.data["artifact_id"]
        '...'
    """

    arg_models: dict[str, type[BaseModel]] = {
        "writer_generate": WriterGenerateArgs,
        "writer_apply": WriterApplyArgs,
    }

    #: Only generation needs a model; a server configured without `llm:`
    #: exposes `writer_apply` alone.
    llm_dependent_tools: frozenset = frozenset({"writer_generate"})

    #: Applying mutates the worktree and therefore requires host approval.
    confirming_tools: frozenset = frozenset({"writer_apply"})

    #: Acquire the client lazily on first use, and release it deterministically.
    auto_open: bool = True

    def __init__(
        self,
        *,
        repo_root: str | Path,
        llm_client: Optional["AbstractClient"] = None,
        limits: Optional[WriterLimits] = None,
        expected_model_ids: Sequence[str] = (),
        owns_client: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit and refuse a client that may switch models.

        Args:
            repo_root: The repository checkout this toolkit is confined to.
            llm_client: The configured client, injected by MCP config.
            limits: Budgets for one generation.
            expected_model_ids: Additional model identities the provider may
                legitimately report (e.g. Bedrock's translated model id).
            owns_client: When True, this toolkit opens and closes the client.
            **kwargs: Policy overrides and toolkit keyword arguments.

        Raises:
            ValueError: The client permits a fallback model, which would let
                the provider silently answer with a different model.
        """
        super().__init__(repo_root=repo_root, **kwargs)
        fallback = getattr(llm_client, "_fallback_model", None) if llm_client is not None else None
        if fallback:
            raise ValueError(
                "TargetedWriterToolkit requires a client with fallback disabled "
                "(configure llm_kwargs: {fallback_model: null}); "
                f"got fallback_model={fallback!r}"
            )
        self._client = llm_client
        self._owns_client = bool(owns_client and llm_client is not None)
        self._limits = limits or WriterLimits()
        self._expected_models = tuple(expected_model_ids)
        self._client_lock = asyncio.Lock()
        self._store = ArtifactStore(self.policy.repo_root)

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #
    async def _open(self) -> None:
        """Enter the client's context so its resources are acquired once."""
        if self._owns_client and self._client is not None:
            await self._client.__aenter__()

    async def _close(self) -> None:
        """Release the client's resources; MCP shutdown is not assumed to."""
        try:
            if self._owns_client and self._client is not None:
                await self._client.__aexit__(None, None, None)
                await self._client.close()
        finally:
            await super()._close()

    # ----------------------------------------------------------------- #
    # Generation
    # ----------------------------------------------------------------- #
    @tool_schema(WriterGenerateArgs)
    async def writer_generate(self, task_path: str) -> OperationResult:
        """Generate a reviewed-patch artifact for an eligible TASK file.

        Validates the TASK's delegation contract, calls the configured model
        with no tools and no history, validates the returned unified diff
        against the approved scope and current source bytes, and stores it.
        **No target file is modified.** The result carries an artifact id and
        a patch path for the thinking model to review before applying.

        Args:
            task_path: Repository-relative path of the TASK file.

        Returns:
            An operation result whose ``data`` carries ``artifact_id``,
            ``patch_path``, ``patch_sha256``, ``targets``, ``usage``,
            ``repairs``, ``configured_model`` and ``actual_model``.
        """
        started = time.perf_counter()
        operation = "writer_generate"
        try:
            args = WriterGenerateArgs(task_path=task_path)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "invalid_arguments", str(exc), started=started)

        if self._client is None:
            return self._error(
                operation, "no_client", "this toolkit was configured without a model client", started=started
            )

        try:
            contract = await validate_contract(self.policy, args.task_path, limits_override=self._limits)
        except ContractError as exc:
            # No model call has happened, and none will.
            return self._error(operation, exc.code, str(exc), details=exc.details, started=started)

        allowed = {target.path: target.action for target in contract.packet.targets}
        try:
            sources = await asyncio.to_thread(self._read_sources, contract)
        except OSError as exc:
            return self._error(operation, "source_unreadable", str(exc), started=started)

        try:
            return await self._generate_locked(contract, allowed, sources, started)
        except (TimeoutError, asyncio.TimeoutError):
            return self._error(
                operation,
                "deadline_exceeded",
                f"generation exceeded {self._limits.generation_deadline_seconds}s",
                details={"deadline_seconds": self._limits.generation_deadline_seconds},
                started=started,
            )

    def _read_sources(self, contract: ValidatedContract) -> dict[str, Optional[bytes]]:
        """Read the current bytes of every modify target.

        The size is taken from an already-verified stat, and one extra byte
        is requested so a file that grew mid-read is detected rather than
        silently truncated.

        Args:
            contract: The validated contract.

        Returns:
            Target path -> current bytes, or None for a create.

        Raises:
            OSError: A target could not be read.
        """
        sources: dict[str, Optional[bytes]] = {}
        for target in contract.packet.targets:
            if target.action == "create":
                sources[target.path] = None
                continue
            path = self.policy.repo_root / target.path
            size = stat_regular(path).size
            with open(path, "rb") as handle:
                sources[target.path] = handle.read(size + 1)
        return sources

    async def _generate_locked(
        self,
        contract: ValidatedContract,
        allowed: dict[str, str],
        sources: dict[str, Optional[bytes]],
        started: float,
    ) -> OperationResult:
        """Run the model attempts under the lock and the overall deadline.

        Args:
            contract: The validated contract.
            allowed: Approved path -> create/modify.
            sources: Current bytes per target.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded operation result.
        """
        operation = "writer_generate"
        limits = self._limits
        configured_model = str(getattr(self._client, "model", "") or "")
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        saw_usage = False
        actual_model: Optional[str] = None
        prompt = build_prompt(contract)
        if len(prompt.encode("utf-8")) > limits.max_context_bytes:
            return self._error(
                operation,
                "context_budget_exceeded",
                "the rendered prompt exceeds the configured context budget",
                details={"bytes": len(prompt.encode("utf-8")), "max_context_bytes": limits.max_context_bytes},
                started=started,
            )

        repairs = 0
        async with self._client_lock:
            async with asyncio.timeout(limits.generation_deadline_seconds):
                while True:
                    message = await self._client.ask(
                        prompt=prompt,
                        system_prompt=SYSTEM_PROMPT,
                        max_tokens=limits.max_output_tokens,
                        temperature=0.0,
                        use_tools=False,
                        history=None,
                    )

                    metadata = getattr(message, "metadata", None) or {}
                    usage = getattr(message, "usage", None)
                    if usage is not None:
                        for field in usage_total:
                            value = getattr(usage, field, None)
                            if value:
                                usage_total[field] += int(value)
                                saw_usage = True
                    actual_model = getattr(message, "model", None)

                    if metadata.get("used_fallback_model"):
                        return self._error(
                            operation,
                            "model_substituted",
                            "the provider answered with a fallback model",
                            details={"configured": configured_model, "actual": actual_model},
                            started=started,
                        )
                    if self._expected_models and actual_model not in {configured_model, *self._expected_models}:
                        return self._error(
                            operation,
                            "model_substituted",
                            "the provider reported an unexpected model identity",
                            details={"configured": configured_model, "actual": actual_model},
                            started=started,
                        )
                    if metadata.get("tool_calls"):
                        return self._error(
                            operation, "unexpected_tool_call", "the delegate attempted a tool call", started=started
                        )

                    text = self._response_text(message)
                    if text is None:
                        return self._error(
                            operation,
                            "unexpected_tool_call",
                            "the delegate returned a structured response instead of a patch",
                            started=started,
                        )

                    try:
                        normalized = normalize_patch(text)
                        patches = parse_patch(normalized, max_bytes=limits.max_patch_bytes)
                        check_scope(patches, allowed)
                        after = apply_in_memory(patches, sources)
                        break
                    except PatchError as exc:
                        if repairs < limits.max_repairs:
                            repairs += 1
                            prompt = build_repair_prompt(contract, text, exc)
                            continue
                        return self._error(
                            operation,
                            exc.code,
                            str(exc),
                            details={**exc.details, "repairs": repairs},
                            started=started,
                        )

        recorded_usage: dict[str, Optional[int]] = (
            {field: value for field, value in usage_total.items()}
            if saw_usage
            else {field: None for field in usage_total}
        )
        return self._store_artifact(
            contract=contract,
            patch_text=normalized,
            after=after,
            allowed=allowed,
            configured_model=configured_model,
            actual_model=actual_model,
            usage=recorded_usage,
            repairs=repairs,
            started=started,
        )

    @staticmethod
    def _response_text(message: Any) -> Optional[str]:
        """Extract patch text from a model response.

        Args:
            message: The provider's response object.

        Returns:
            The text, or None when the response was not plain text.
        """
        response = getattr(message, "response", None)
        if isinstance(response, str) and response:
            return response
        output = getattr(message, "output", None)
        if isinstance(output, str):
            return output
        return None

    def _store_artifact(
        self,
        *,
        contract: ValidatedContract,
        patch_text: str,
        after: dict[str, bytes],
        allowed: dict[str, str],
        configured_model: str,
        actual_model: Optional[str],
        usage: dict[str, Optional[int]],
        repairs: int,
        started: float,
    ) -> OperationResult:
        """Persist the validated patch and return its manifest summary.

        Args:
            contract: The validated contract.
            patch_text: The normalized, validated patch.
            after: Path -> resulting bytes, from the in-memory application.
            allowed: Approved path -> create/modify.
            configured_model: The model identity configuration requested.
            actual_model: The model identity the provider reported.
            usage: Recorded token usage; None means the provider reported none.
            repairs: How many repair calls were consumed.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded operation result.
        """
        artifact_id = self._store.new_id()
        packet_json = compact_json(contract.packet.model_dump(mode="json"))
        manifest = PatchManifest(
            artifact_id=artifact_id,
            task_id=contract.packet.task_id,
            task_path=contract.task_path,
            packet_sha256=hashlib.sha256(packet_json.encode("utf-8")).hexdigest(),
            patch_sha256=hashlib.sha256(patch_text.encode("utf-8")).hexdigest(),
            before_hashes=dict(contract.targets_state),
            after_hashes={path: hashlib.sha256(data).hexdigest() for path, data in after.items()},
            allowed_paths=sorted(allowed),
            configured_model=configured_model or "unknown",
            actual_model=actual_model,
            used_fallback=False,
            usage=usage,
            repairs=repairs,
            elapsed_ms=self._elapsed_ms(started),
            validation_state="validated",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._store.write_generation(artifact_id, manifest=manifest, patch_text=patch_text, packet_json=packet_json)
        self.logger.info(
            "writer_generate produced artifact %s for %s (model=%s, repairs=%d)",
            artifact_id,
            contract.packet.task_id,
            actual_model,
            repairs,
        )
        return self._ok(
            "writer_generate",
            {
                "artifact_id": artifact_id,
                "patch_path": f"artifacts/tool-optimizations/{artifact_id}/patch.diff",
                "patch_sha256": manifest.patch_sha256,
                "targets": sorted(allowed),
                "usage": usage,
                "repairs": repairs,
                "configured_model": manifest.configured_model,
                "actual_model": actual_model,
            },
            started=started,
        )

    # ----------------------------------------------------------------- #
    # Application
    # ----------------------------------------------------------------- #
    @tool_schema(WriterApplyArgs)
    async def writer_apply(self, artifact_id: str, reviewed_sha256: str) -> OperationResult:
        """Apply a reviewed patch artifact to the worktree.

        Every precondition is re-checked before anything is written: the
        reviewed patch hash, the packet identity, the delegation contract,
        the absence of staged targets, and each target's current revision.
        Files are then replaced one at a time through adjacent temporary
        files, with a recovery journal recording what was intended.

        Multi-file mutation is not globally atomic. On failure, only files
        that still match exactly what this operation wrote are restored; a
        file a concurrent editor has touched is never overwritten, and the
        operation reports ``recovery_required`` instead.

        Applying never stages, commits or pushes anything.

        The ``confirm`` argument added over MCP records that a human approved
        this mutation; it is not authorization a model can grant itself.

        Args:
            artifact_id: The artifact returned by ``writer_generate``.
            reviewed_sha256: The hash of the patch the caller actually read.

        Returns:
            An operation result whose ``data`` carries ``applied``,
            ``artifact_id`` and ``journal_path``, or ``already_applied``.
        """
        started = time.perf_counter()
        operation = "writer_apply"
        try:
            args = WriterApplyArgs(artifact_id=artifact_id, reviewed_sha256=reviewed_sha256)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "invalid_arguments", str(exc), started=started)

        try:
            manifest, patch_text, packet_json = self._store.load(args.artifact_id)
        except PatchError as exc:
            return self._error(operation, exc.code, str(exc), details=exc.details, started=started)

        # The hash proves artifact identity — that the caller reviewed THIS
        # patch. It is not, and cannot be, proof of semantic review.
        if args.reviewed_sha256 != manifest.patch_sha256:
            return self._error(
                operation,
                "review_hash_mismatch",
                "the reviewed hash does not match the stored patch; read the patch and pass its hash",
                details={"expected": manifest.patch_sha256, "supplied": args.reviewed_sha256},
                started=started,
            )

        try:
            packet = DelegationPacket.model_validate_json(packet_json)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "packet_mismatch", f"the stored packet is unusable: {exc}", started=started)
        recomputed = hashlib.sha256(compact_json(packet.model_dump(mode="json")).encode("utf-8")).hexdigest()
        if recomputed != manifest.packet_sha256:
            return self._error(
                operation,
                "packet_mismatch",
                "the stored packet does not round-trip to its recorded identity",
                details={"expected": manifest.packet_sha256, "actual": recomputed},
                started=started,
            )

        git = LocalGitToolkit(repo_root=self.policy.repo_root, policy=self.policy)
        layout = await git._discover(operation, started)
        if isinstance(layout, OperationResult):
            return layout

        try:
            async with WorktreeLock(layout.lock_path, self.policy.command_timeout_seconds):
                return await self._apply_locked(operation, git, manifest, packet, patch_text, started)
        except LockTimeoutError as exc:
            return self._error(operation, "worktree_busy", str(exc), started=started)

    async def _apply_locked(
        self,
        operation: str,
        git: LocalGitToolkit,
        manifest: PatchManifest,
        packet: DelegationPacket,
        patch_text: str,
        started: float,
    ) -> OperationResult:
        """Re-check every precondition, then write, under the worktree lock.

        Args:
            operation: The operation name.
            git: A private Git toolkit used only to read staged names.
            manifest: The artifact's manifest.
            packet: The artifact's packet.
            patch_text: The stored, normalized patch.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded operation result.
        """
        root = self.policy.repo_root
        artifact_id = manifest.artifact_id
        targets = {target.path: target.action for target in packet.targets}

        # Idempotent re-run: if every target already equals what this
        # artifact produces, report that instead of re-writing.
        current = await asyncio.to_thread(self._current_hashes, sorted(targets))
        if all(current.get(path) == manifest.after_hashes.get(path) for path in targets):
            return self._ok(
                operation,
                {"already_applied": True, "artifact_id": artifact_id, "applied": sorted(targets)},
                started=started,
            )

        journal = self._store.read_journal(artifact_id)
        if journal is not None and journal.state == "recovery_required":
            return self._error(
                operation,
                "recovery_pending",
                "a previous apply needs manual recovery; resolve it before retrying",
                details={
                    "journal_path": self._journal_path(artifact_id),
                    "unrecoverable": [entry.path for entry in journal.entries if entry.state == "unrecoverable"],
                },
                started=started,
            )

        staged_step, staged_raw = await git._run_git(["diff", "--cached", "--name-only", "-z"])
        if staged_step.exit_code != 0:
            return self._error(operation, "status_failed", "could not read the staged file list", started=started)
        staged = {item for item in staged_raw.decode("utf-8", "replace").split("\x00") if item}
        conflicting = sorted(staged & set(targets))
        if conflicting:
            return self._error(
                operation,
                "staged_target",
                "a target file is already staged; publish or unstage it yourself first",
                details={"staged": conflicting},
                started=started,
            )

        for path, action in sorted(targets.items()):
            expected = manifest.before_hashes.get(path)
            actual = current.get(path)
            if action == "create" and actual is not None:
                return self._error(
                    operation,
                    "create_collision",
                    f"{path!r} was created since the patch was generated",
                    details={"path": path},
                    started=started,
                )
            if action == "modify" and actual != expected:
                return self._error(
                    operation,
                    "target_changed",
                    f"{path!r} changed since the patch was generated",
                    details={"path": path, "expected": expected, "actual": actual},
                    started=started,
                )

        try:
            await validate_contract(self.policy, manifest.task_path, limits_override=self._limits)
        except ContractError as exc:
            return self._error(operation, exc.code, str(exc), details=exc.details, started=started)

        try:
            sources = await asyncio.to_thread(self._read_sources_for_packet, packet)
            patches = parse_patch(patch_text, max_bytes=self._limits.max_patch_bytes)
            check_scope(patches, targets)
            after = apply_in_memory(patches, sources)
        except PatchError as exc:
            return self._error(operation, exc.code, str(exc), details=exc.details, started=started)
        except OSError as exc:
            return self._error(operation, "source_unreadable", str(exc), started=started)

        for path, data in after.items():
            digest = hashlib.sha256(data).hexdigest()
            if digest != manifest.after_hashes.get(path):
                return self._error(
                    operation,
                    "after_hash_mismatch",
                    f"re-applying the patch to {path!r} no longer reproduces the recorded result",
                    details={"path": path, "expected": manifest.after_hashes.get(path), "actual": digest},
                    started=started,
                )

        journal = ApplyJournal(
            artifact_id=artifact_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            entries=[
                JournalEntry(
                    path=target.path,
                    before_sha256=manifest.before_hashes.get(target.path),
                    after_sha256=manifest.after_hashes[target.path],
                    before_index=index,
                )
                for index, target in enumerate(packet.targets)
            ],
            state="pending",
        )
        for index, target in enumerate(packet.targets):
            self._store.save_before(artifact_id, index, sources.get(target.path))
        self._store.write_journal(artifact_id, journal)

        created_dirs: list[Path] = []
        try:
            for index, target in enumerate(packet.targets):
                destination = root / target.path
                data = after[target.path]
                if target.action == "create":
                    mode = _CREATE_MODE
                    if not destination.parent.exists():
                        created_dirs.extend(_missing_parents(root, destination.parent))
                        await asyncio.to_thread(destination.parent.mkdir, 0o755, True, True)
                else:
                    # Preserve the existing file's permissions across the replace.
                    mode = os.stat(destination).st_mode & 0o777
                await asyncio.to_thread(_write_atomic, destination, data, mode)
                journal.entries[index].state = "written"
                self._store.write_journal(artifact_id, journal)
        except BaseException as exc:  # noqa: BLE001 — rollback then report
            return await self._rollback(operation, journal, created_dirs, exc, started)

        for entry in journal.entries:
            digest = await asyncio.to_thread(_sha_or_none, root / entry.path)
            if digest != entry.after_sha256:
                return await self._rollback(
                    operation,
                    journal,
                    created_dirs,
                    PatchError("verification_failed", f"{entry.path!r} does not match the expected result"),
                    started,
                )
            entry.state = "verified"
        journal.state = "applied"
        self._store.write_journal(artifact_id, journal)

        self.logger.info("writer_apply applied artifact %s to %d file(s)", artifact_id, len(journal.entries))
        return self._ok(
            operation,
            {
                "applied": [entry.path for entry in journal.entries],
                "artifact_id": artifact_id,
                "journal_path": self._journal_path(artifact_id),
                "already_applied": False,
            },
            started=started,
        )

    async def _rollback(
        self,
        operation: str,
        journal: ApplyJournal,
        created_dirs: list[Path],
        error: BaseException,
        started: float,
    ) -> OperationResult:
        """Restore only the files that still match exactly what we wrote.

        A file a concurrent editor has since changed is left untouched and
        marked unrecoverable — overwriting it would destroy their work.

        Args:
            operation: The operation name.
            journal: The journal to update in place.
            created_dirs: Directories this operation created, for cleanup.
            error: The failure that triggered the rollback.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded error result.
        """
        root = self.policy.repo_root
        artifact_id = journal.artifact_id
        for index in range(len(journal.entries) - 1, -1, -1):
            entry = journal.entries[index]
            if entry.state != "written":
                continue
            destination = root / entry.path
            digest = await asyncio.to_thread(_sha_or_none, destination)
            if digest != entry.after_sha256:
                entry.state = "unrecoverable"
                continue
            original = self._store.load_before(artifact_id, entry.before_index)
            try:
                if original is None:
                    await asyncio.to_thread(destination.unlink)
                else:
                    await asyncio.to_thread(_write_atomic, destination, original, _CREATE_MODE)
                entry.state = "restored"
            except OSError:
                entry.state = "unrecoverable"

        for directory in reversed(created_dirs):
            with contextlib.suppress(OSError):
                directory.rmdir()

        unrecoverable = [entry.path for entry in journal.entries if entry.state == "unrecoverable"]
        journal.state = "recovery_required" if unrecoverable else "rolled_back"
        self._store.write_journal(artifact_id, journal)

        if unrecoverable:
            return self._error(
                operation,
                "recovery_required",
                "the apply failed and some files could not be safely restored",
                details={
                    "unrecoverable": unrecoverable,
                    "journal_path": self._journal_path(artifact_id),
                    "cause": str(error),
                },
                started=started,
            )
        code = getattr(error, "code", None) or "write_failed"
        return self._error(
            operation,
            code,
            f"the apply failed and was rolled back: {error}",
            details={"journal_path": self._journal_path(artifact_id), "errno": getattr(error, "errno", None)},
            started=started,
        )

    def _current_hashes(self, paths: Sequence[str]) -> dict[str, Optional[str]]:
        """Hash each path that currently exists.

        Args:
            paths: Repo-relative paths.

        Returns:
            Path -> digest, or None when the file is absent.
        """
        return {path: _sha_or_none(self.policy.repo_root / path) for path in paths}

    def _read_sources_for_packet(self, packet: DelegationPacket) -> dict[str, Optional[bytes]]:
        """Read the current bytes of every modify target in a packet.

        Args:
            packet: The delegation packet.

        Returns:
            Target path -> current bytes, or None for a create.
        """
        sources: dict[str, Optional[bytes]] = {}
        for target in packet.targets:
            if target.action == "create":
                sources[target.path] = None
                continue
            path = self.policy.repo_root / target.path
            size = stat_regular(path).size
            with open(path, "rb") as handle:
                sources[target.path] = handle.read(size + 1)
        return sources

    @staticmethod
    def _journal_path(artifact_id: str) -> str:
        """Return the repo-relative path of an artifact's journal."""
        return f"artifacts/tool-optimizations/{artifact_id}/journal.json"

    async def _recovery_report(self, artifact_id: str) -> OperationResult:
        """Report an artifact's journal state (not exposed as a tool).

        Args:
            artifact_id: The artifact identifier.

        Returns:
            An operation result describing each journal entry.
        """
        started = time.perf_counter()
        operation = "recovery_report"
        try:
            journal = self._store.read_journal(artifact_id)
        except PatchError as exc:
            return self._error(operation, exc.code, str(exc), started=started)
        if journal is None:
            return self._error(
                operation, "no_journal", f"artifact {artifact_id!r} has never been applied", started=started
            )
        return self._ok(
            operation,
            {
                "artifact_id": artifact_id,
                "state": journal.state,
                "journal_path": self._journal_path(artifact_id),
                "entries": [{"path": entry.path, "state": entry.state} for entry in journal.entries],
            },
            started=started,
        )


def _sha_or_none(path: Path) -> Optional[str]:
    """Return a file's SHA-256, or None when it does not exist.

    Args:
        path: The file to hash.

    Returns:
        The digest, or None.
    """
    try:
        return sha256_stream(path, deadline_seconds=60)
    except (FileNotFoundError, OSError):
        return None


def _missing_parents(root: Path, target: Path) -> list[Path]:
    """List the directories that would have to be created under ``root``.

    Args:
        root: The repository root.
        target: The deepest directory needed.

    Returns:
        The missing directories, outermost first.
    """
    missing: list[Path] = []
    current = target
    while current != root and root in current.parents and not current.exists():
        missing.append(current)
        current = current.parent
    return list(reversed(missing))


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    """Replace ``path`` with ``data`` via an adjacent temporary file.

    The temporary file is adjacent to the destination so the rename stays
    within one filesystem, which is what makes the replacement atomic.

    Args:
        path: The destination file.
        data: The bytes to write.
        mode: Permission bits for the new file.

    Raises:
        OSError: The write or replacement failed; the temp file is removed.
    """
    temp = path.parent / f".{path.name}.parrot-tmp"
    if temp.exists():
        temp.unlink()
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)
        raise
