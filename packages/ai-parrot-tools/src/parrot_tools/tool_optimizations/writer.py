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
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

from parrot.tools.decorators import tool_schema
from pydantic import BaseModel

from .base import OptimizationToolkitBase
from .contracts import ContractError, ValidatedContract, render_prompt_sections, validate_contract
from .models import (
    OperationResult,
    PatchManifest,
    WriterApplyArgs,
    WriterGenerateArgs,
    WriterLimits,
)
from .patches import ArtifactStore, PatchError, apply_in_memory, check_scope, normalize_patch, parse_patch
from .policy import compact_json
from .reader import stat_regular

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps provider imports lazy
    from parrot.clients.base import AbstractClient

__all__ = ("SYSTEM_PROMPT", "TargetedWriterToolkit", "build_prompt", "build_repair_prompt")

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
    # Application (TASK-3086)
    # ----------------------------------------------------------------- #
    @tool_schema(WriterApplyArgs)
    async def writer_apply(self, artifact_id: str, reviewed_sha256: str) -> OperationResult:
        """Apply a reviewed patch artifact to the worktree.

        The ``confirm`` argument added over MCP records that a human approved
        this mutation; it is not authorization a model can grant itself.

        Args:
            artifact_id: The artifact returned by ``writer_generate``.
            reviewed_sha256: The hash of the patch the caller actually read.

        Returns:
            An operation result describing the application.
        """
        started = time.perf_counter()
        return self._error(
            "writer_apply",
            "not_implemented",
            "writer_apply is implemented by TASK-3086",
            started=started,
        )
