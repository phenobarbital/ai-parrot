"""Delegation-contract parsing and validation (FEAT-543).

This module decides — **entirely offline, before any model call** — whether
a TASK file is eligible for delegation. A stale or incomplete contract is
returned to the thinking model with a precise, actionable error; the
delegate never explores the repository and never resolves a design gap.

A TASK file is eligible when it contains exactly one ``## Delegation
Contract`` section holding exactly one ``json`` fenced block that validates
as a :class:`DelegationPacket`, and every implementation block that packet
references exists in the same file, is free of placeholders, and matches
the recorded revisions on disk.

``design_complete: true`` is an *eligibility declaration*, not proof of
correctness: this module checks structural completeness, while the thinking
model verifies semantics.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError
from pydantic import BaseModel, ConfigDict, ValidationError

from .models import DelegationPacket, ReferenceSlice, WriterLimits
from .policy import (
    OptimizationPolicy,
    PolicyError,
    SymlinkRejectedError,
    compact_json,
    measure_json_bytes,
    resolve_operand,
)
from .reader import (
    InvalidEncodingError,
    LineTooLargeError,
    RangeOutOfBoundsError,
    read_line_range,
    sha256_stream,
    stat_regular,
)

__all__ = (
    "ALLOWED_VALIDATION_PROGRAMS",
    "CodeBlock",
    "ContractError",
    "ResolvedReference",
    "ValidatedContract",
    "extract_packet",
    "find_placeholders",
    "parse_task_file",
    "render_prompt_sections",
    "validate_contract",
)

#: The only programs a packet may name in `validation_commands`. Commands are
#: never executed here — the SDD workflow owns authorized validation — but an
#: unrecognized program means the packet was not authored by that workflow.
ALLOWED_VALIDATION_PROGRAMS = frozenset({"pytest", "ruff", "black", "mypy", "python", "python3"})

#: The heading that opens the delegation section.
DELEGATION_HEADING = "## Delegation Contract"

#: Maximum number of TASK-file lines scanned.
_MAX_TASK_LINES = 200_000

_FENCE = re.compile(r"^(?P<fence>`{3,})(?P<info>.*)$")
_BLOCK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

#: Line-anchored placeholder patterns. A bare ellipsis *line* is a
#: placeholder; the string "..." inside an expression is not.
_PLACEHOLDERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bare_ellipsis", re.compile(r"^\s*\.\.\.\s*$")),
    ("todo", re.compile(r"\bTODO\b")),
    ("fixme", re.compile(r"\bFIXME\b")),
    ("xxx", re.compile(r"\bXXX\b")),
    ("angle_placeholder", re.compile(r"<[A-Za-z][A-Za-z0-9 _-]*>")),
    ("not_implemented", re.compile(r"raise NotImplementedError")),
    ("pass_implement", re.compile(r"pass\s+#\s*implement")),
)


class ContractError(ValueError):
    """A delegation contract is missing, malformed, stale or underspecified.

    Attributes:
        code: A stable snake_case code identifying the failure.
        details: Structured context telling the thinking model what to fix.
    """

    def __init__(self, code: str, message: str = "", details: Optional[dict[str, Any]] = None) -> None:
        """Initialize the error.

        Args:
            code: The stable failure code.
            message: A human-readable explanation.
            details: Structured context (block ids, paths, expected vs current).
        """
        super().__init__(message or code)
        self.code = code
        self.details = details or {}


class CodeBlock(BaseModel):
    """A labelled fenced code block inside a TASK file.

    Attributes:
        block_id: The `id=` attribute from the fence info string.
        language: The fence's language token, if any.
        text: The block's literal content.
        start_line: The 1-based line of the opening fence.
        path: The `path=` attribute, when the block *is* a file's content.
    """

    model_config = ConfigDict(extra="forbid")

    block_id: str
    language: str = ""
    text: str = ""
    start_line: int
    path: Optional[str] = None


class ResolvedReference(BaseModel):
    """A reference slice loaded from disk and checked for freshness.

    Attributes:
        slice: The packet's declared reference.
        content: The bounded excerpt actually read.
        current_sha256: The referenced file's current digest.
    """

    model_config = ConfigDict(extra="forbid")

    slice: ReferenceSlice
    content: str
    current_sha256: str


class ValidatedContract(BaseModel):
    """A TASK file proven eligible for delegation.

    Attributes:
        task_path: The repo-relative TASK file path.
        packet: The validated delegation packet.
        packet_sha256: The packet's canonical identity.
        blocks: Only the implementation blocks the packet references.
        references: The loaded, freshness-checked reference slices.
        targets_state: Target path -> current digest, or None when absent.
        context_bytes: The measured size of everything sent to the delegate.
    """

    model_config = ConfigDict(extra="forbid")

    task_path: str
    packet: DelegationPacket
    packet_sha256: str
    blocks: dict[str, CodeBlock]
    references: list[ResolvedReference]
    targets_state: dict[str, Optional[str]]
    context_bytes: int


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _parse_info(info: str) -> dict[str, str]:
    """Parse a fence info string into a language plus ``key=value`` tokens.

    Args:
        info: The text following the opening backticks.

    Returns:
        A mapping with ``language`` plus any attributes found.
    """
    parsed: dict[str, str] = {"language": ""}
    tokens = info.strip().split()
    for index, token in enumerate(tokens):
        if "=" in token:
            key, _, value = token.partition("=")
            parsed[key] = value
        elif index == 0:
            parsed["language"] = token
        else:
            parsed.setdefault("modifier", token)
    return parsed


def parse_task_file(text: str) -> tuple[str, dict[str, CodeBlock]]:
    """Extract the packet JSON and every labelled code block from a TASK file.

    The fence scanner is hand-written on purpose (no markdown dependency)
    and tracks fence length, so a shorter fence nested inside a block is
    preserved literally.

    Args:
        text: The TASK file's full text.

    Returns:
        A ``(packet_json, blocks)`` tuple keyed by block id.

    Raises:
        ContractError: The delegation section or packet block is missing,
            duplicated, or a block id is duplicated or malformed.
    """
    packets: list[str] = []
    blocks: dict[str, CodeBlock] = {}
    current: Optional[dict[str, Any]] = None
    fence_len = 0
    buffer: list[str] = []
    section_count = 0
    in_section = False

    for lineno, line in enumerate(text.splitlines(), 1):
        match = _FENCE.match(line)

        if current is None:
            if line.startswith("## "):
                in_section = line.strip() == DELEGATION_HEADING
                if in_section:
                    section_count += 1
                continue
            if match:
                current = _parse_info(match.group("info"))
                current["start_line"] = lineno
                current["in_section"] = in_section
                fence_len = len(match.group("fence"))
                buffer = []
            continue

        # Inside a block: only a bare fence at least as long closes it.
        if match and len(match.group("fence")) >= fence_len and not match.group("info").strip():
            _close_block(current, buffer, packets, blocks)
            current = None
            continue
        buffer.append(line)

    if section_count == 0:
        raise ContractError("no_delegation_section", f"no {DELEGATION_HEADING!r} section in the TASK file")
    if section_count > 1:
        raise ContractError(
            "duplicate_delegation_section",
            f"{section_count} {DELEGATION_HEADING!r} sections; exactly one is allowed",
            {"count": section_count},
        )
    if not packets:
        raise ContractError("no_packet_block", "the delegation section contains no json fenced block")
    if len(packets) > 1:
        raise ContractError(
            "duplicate_packet_block",
            f"the delegation section contains {len(packets)} json blocks; exactly one is allowed",
            {"count": len(packets)},
        )
    return packets[0], blocks


def _close_block(info: dict[str, Any], buffer: list[str], packets: list[str], blocks: dict[str, CodeBlock]) -> None:
    """Record a finished fenced block as the packet or a labelled block.

    Args:
        info: The parsed fence info string plus positional metadata.
        buffer: The block's literal lines.
        packets: Accumulator for packet JSON blocks.
        blocks: Accumulator for labelled implementation blocks.

    Raises:
        ContractError: A block id is malformed or duplicated.
    """
    body = "\n".join(buffer)
    if info.get("in_section") and info.get("language") == "json" and "id" not in info:
        packets.append(body)
        return

    block_id = info.get("id")
    if not block_id:
        return
    if not _BLOCK_ID.match(block_id):
        raise ContractError("duplicate_block_id", f"malformed block id {block_id!r}", {"block_id": block_id})
    if block_id in blocks:
        raise ContractError(
            "duplicate_block_id", f"block id {block_id!r} appears more than once", {"block_id": block_id}
        )
    blocks[block_id] = CodeBlock(
        block_id=block_id,
        language=info.get("language", ""),
        text=body,
        start_line=int(info["start_line"]),
        path=info.get("path"),
    )


def extract_packet(json_text: str) -> DelegationPacket:
    """Parse and validate the packet JSON block.

    Args:
        json_text: The raw contents of the packet fenced block.

    Returns:
        The validated packet.

    Raises:
        ContractError: The JSON is malformed or the packet is invalid.
    """
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ContractError(
            "invalid_packet_json", f"the packet block is not valid JSON: {exc}", {"error": str(exc)}
        ) from exc
    try:
        return DelegationPacket.model_validate(payload)
    except ValidationError as exc:
        errors = [
            {"loc": ".".join(str(part) for part in item.get("loc", ())), "msg": item["msg"]}
            for item in exc.errors()[:10]
        ]
        raise ContractError(
            "invalid_packet", "the packet does not satisfy the delegation schema", {"errors": errors}
        ) from exc


def find_placeholders(block: CodeBlock) -> list[tuple[int, str]]:
    """Find unresolved placeholder code inside an implementation block.

    Args:
        block: The block to scan.

    Returns:
        A list of ``(line_number, pattern_name)`` tuples, relative to the
        block's own first line.
    """
    found: list[tuple[int, str]] = []
    for offset, line in enumerate(block.text.splitlines(), 1):
        for name, pattern in _PLACEHOLDERS:
            if pattern.search(line):
                found.append((offset, name))
                break
    return found


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _resolve_scope_path(policy: OptimizationPolicy, candidate: str, *, must_exist: bool) -> Path:
    """Resolve a packet-declared path under the repository policy.

    Args:
        policy: The active policy.
        candidate: The declared repo-relative path.
        must_exist: Whether the path is required to exist.

    Returns:
        The resolved absolute path.

    Raises:
        ContractError: The path is absolute, escapes the root, traverses a
            symlink, matches the secret deny-list, or is required and absent.
    """
    if not candidate or candidate.startswith("/") or Path(candidate).is_absolute():
        raise ContractError("scope_path_invalid", f"{candidate!r} must be repository-relative", {"path": candidate})
    if any(segment in ("", ".", "..") for segment in candidate.split("/")):
        raise ContractError("scope_path_invalid", f"{candidate!r} contains a traversal segment", {"path": candidate})
    try:
        return resolve_operand(policy, candidate, must_exist=must_exist)
    except (SymlinkRejectedError, SecretFileError, PathOutsideRootError, PolicyError) as exc:
        raise ContractError("scope_path_invalid", str(exc), {"path": candidate}) from exc


def _read_text_bounded(policy: OptimizationPolicy, path: Path) -> str:
    """Read a whole text file through the bounded reader.

    ``Path.read_text`` is deliberately avoided so this module obeys the same
    allocation rules as the bounded reader.

    Args:
        policy: The active policy, supplying the per-line byte bound.
        path: The file to read.

    Returns:
        The file's text, or ``""`` when it is empty.

    Raises:
        ContractError: The file has an oversized line or invalid encoding.
    """
    if stat_regular(path).size == 0:
        return ""
    try:
        span = read_line_range(path, 1, _MAX_TASK_LINES, max_line_bytes=policy.max_result_bytes)
    except LineTooLargeError as exc:
        raise ContractError("packet_too_large", str(exc), {"line": exc.line_no}) from exc
    except InvalidEncodingError as exc:
        raise ContractError(
            "invalid_packet_json", f"the file is not valid UTF-8 at line {exc.line_no}", {"line": exc.line_no}
        ) from exc
    except RangeOutOfBoundsError:
        return ""
    return "".join(span.lines)


def _validate_commands(packet: DelegationPacket) -> None:
    """Check that every validation command is a safe, recognized argv list.

    Commands are **never executed** here; this only proves the packet came
    from the SDD workflow rather than from a model response.

    Args:
        packet: The validated packet.

    Raises:
        ContractError: A command is empty, option-shaped, or names a program
            outside the allow-list.
    """
    for argv in packet.validation_commands:
        if not argv:
            raise ContractError("invalid_validation_command", "empty argv list", {"argv": argv})
        program = argv[0]
        if not isinstance(program, str) or program.startswith("-"):
            raise ContractError("invalid_validation_command", f"option-shaped program {program!r}", {"argv": argv})
        if Path(program).name not in ALLOWED_VALIDATION_PROGRAMS:
            raise ContractError(
                "invalid_validation_command",
                f"{program!r} is not an allowed validation program",
                {"argv": argv, "allowed": sorted(ALLOWED_VALIDATION_PROGRAMS)},
            )


def _validate_blocks(packet: DelegationPacket, blocks: dict[str, CodeBlock]) -> dict[str, CodeBlock]:
    """Resolve every referenced block and reject placeholder code.

    Args:
        packet: The validated packet.
        blocks: Every labelled block found in the TASK file.

    Returns:
        Only the blocks the packet actually references.

    Raises:
        ContractError: A referenced block is missing or contains a placeholder.
    """
    needed: list[str] = list(packet.implementation_blocks)
    for target in packet.targets:
        needed.extend(target.blocks)

    resolved: dict[str, CodeBlock] = {}
    for block_id in needed:
        block = blocks.get(block_id)
        if block is None:
            raise ContractError(
                "missing_block",
                f"the TASK file has no code block with id={block_id!r}",
                {"block_id": block_id, "available": sorted(blocks)},
            )
        placeholders = find_placeholders(block)
        if placeholders:
            line, name = placeholders[0]
            raise ContractError(
                "placeholder_code",
                f"block {block_id!r} still contains unresolved placeholder code",
                {"block_id": block_id, "line": line, "pattern": name},
            )
        resolved[block_id] = block
    return resolved


def _validate_targets(
    policy: OptimizationPolicy, packet: DelegationPacket, blocks: dict[str, CodeBlock]
) -> dict[str, Optional[str]]:
    """Check every target's precondition and record its current revision.

    Args:
        policy: The active policy.
        packet: The validated packet.
        blocks: The resolved implementation blocks.

    Returns:
        Target path -> current digest, or None when the file is absent.

    Raises:
        ContractError: A precondition fails or a CREATE is underspecified.
    """
    state: dict[str, Optional[str]] = {}
    for target in packet.targets:
        resolved = _resolve_scope_path(policy, target.path, must_exist=False)
        exists = resolved.exists()

        if target.action == "create":
            if exists:
                raise ContractError(
                    "target_exists_for_create",
                    f"{target.path!r} already exists but is declared as a create",
                    {"path": target.path},
                )
            if not any(blocks[block_id].path == target.path for block_id in target.blocks):
                raise ContractError(
                    "underspecified_create",
                    f"no block tagged path={target.path} supplies the new file's content",
                    {"path": target.path, "blocks": target.blocks},
                )
            state[target.path] = None
            continue

        if not exists:
            raise ContractError(
                "target_missing_for_modify",
                f"{target.path!r} does not exist but is declared as a modify",
                {"path": target.path},
            )
        current = sha256_stream(resolved, deadline_seconds=policy.command_timeout_seconds)
        if current != target.expected_sha256:
            raise ContractError(
                "stale_target",
                f"{target.path!r} changed since the packet was written",
                {"path": target.path, "expected": target.expected_sha256, "current": current},
            )
        state[target.path] = current
    return state


def _load_references(policy: OptimizationPolicy, packet: DelegationPacket) -> list[ResolvedReference]:
    """Load and freshness-check every reference slice.

    Args:
        policy: The active policy.
        packet: The validated packet.

    Returns:
        The loaded references, in packet order.

    Raises:
        ContractError: A reference is stale or its range is invalid.
    """
    loaded: list[ResolvedReference] = []
    for slice_ in packet.references:
        resolved = _resolve_scope_path(policy, slice_.path, must_exist=True)
        current = sha256_stream(resolved, deadline_seconds=policy.command_timeout_seconds)
        if current != slice_.sha256:
            raise ContractError(
                "stale_reference",
                f"{slice_.path!r} changed since the packet was written",
                {"path": slice_.path, "expected": slice_.sha256, "current": current},
            )
        span_length = slice_.end_line - slice_.start_line + 1
        if span_length > policy.max_lines:
            raise ContractError(
                "reference_range_invalid",
                f"reference to {slice_.path!r} spans {span_length} lines, above the {policy.max_lines}-line maximum",
                {"path": slice_.path, "lines": span_length, "max_lines": policy.max_lines},
            )
        try:
            span = read_line_range(resolved, slice_.start_line, slice_.end_line, max_line_bytes=policy.max_result_bytes)
        except (RangeOutOfBoundsError, LineTooLargeError, InvalidEncodingError) as exc:
            raise ContractError(
                "reference_range_invalid",
                f"cannot read the declared range of {slice_.path!r}: {exc}",
                {"path": slice_.path},
            ) from exc
        loaded.append(ResolvedReference(slice=slice_, content="".join(span.lines), current_sha256=current))
    return loaded


def _validate_blocking(
    policy: OptimizationPolicy, task_path: str, limits_override: Optional[WriterLimits]
) -> ValidatedContract:
    """Run the whole validation off the event loop.

    Args:
        policy: The active policy.
        task_path: The repo-relative TASK file path.
        limits_override: Limits replacing the packet's own, when supplied.

    Returns:
        The validated contract.

    Raises:
        ContractError: Any eligibility rule failed.
    """
    try:
        resolved_task = resolve_operand(policy, task_path, must_exist=True)
    except (SymlinkRejectedError, SecretFileError, PathOutsideRootError) as exc:
        raise ContractError("task_outside_root", str(exc), {"path": task_path}) from exc
    except PolicyError as exc:
        raise ContractError("task_not_found", str(exc), {"path": task_path}) from exc

    pre_limits = limits_override or WriterLimits()
    if stat_regular(resolved_task).size > pre_limits.max_packet_bytes:
        raise ContractError(
            "packet_too_large",
            f"{task_path!r} is larger than the {pre_limits.max_packet_bytes}-byte packet budget",
            {"path": task_path, "max_packet_bytes": pre_limits.max_packet_bytes},
        )

    text = _read_text_bounded(policy, resolved_task)
    packet_json, blocks = parse_task_file(text)
    packet = extract_packet(packet_json)

    limits = limits_override or packet.limits
    _validate_commands(packet)
    resolved_blocks = _validate_blocks(packet, blocks)

    packet_dump = packet.model_dump(mode="json")
    packet_bytes = measure_json_bytes(packet_dump)
    if packet_bytes > limits.max_packet_bytes:
        raise ContractError(
            "packet_too_large",
            f"the packet is {packet_bytes} bytes, above the {limits.max_packet_bytes}-byte budget",
            {"bytes": packet_bytes, "max_packet_bytes": limits.max_packet_bytes},
        )

    # Blocks alone can exceed the context budget; check that before any
    # hashing or reference loading, which are the expensive steps.
    block_bytes = sum(len(block.text.encode("utf-8")) for block in resolved_blocks.values())
    if packet_bytes + block_bytes > limits.max_context_bytes:
        raise ContractError(
            "context_budget_exceeded",
            f"packet plus implementation blocks is {packet_bytes + block_bytes} bytes, above the "
            f"{limits.max_context_bytes}-byte context budget",
            {"bytes": packet_bytes + block_bytes, "max_context_bytes": limits.max_context_bytes},
        )

    targets_state = _validate_targets(policy, packet, resolved_blocks)
    references = _load_references(policy, packet)

    context_bytes = packet_bytes + block_bytes + sum(len(ref.content.encode("utf-8")) for ref in references)
    if context_bytes > limits.max_context_bytes:
        raise ContractError(
            "context_budget_exceeded",
            f"the delegation context is {context_bytes} bytes, above the {limits.max_context_bytes}-byte budget",
            {"bytes": context_bytes, "max_context_bytes": limits.max_context_bytes},
        )

    return ValidatedContract(
        task_path=resolved_task.relative_to(policy.repo_root).as_posix(),
        packet=packet,
        packet_sha256=hashlib.sha256(compact_json(packet_dump).encode("utf-8")).hexdigest(),
        blocks=resolved_blocks,
        references=references,
        targets_state=targets_state,
        context_bytes=context_bytes,
    )


async def validate_contract(
    policy: OptimizationPolicy, task_path: str, *, limits_override: Optional[WriterLimits] = None
) -> ValidatedContract:
    """Prove a TASK file is eligible for delegation, or explain why it is not.

    Everything here is deterministic and offline: no network, no model, and
    no command is ever executed.

    Args:
        policy: The active policy, supplying the repository root and limits.
        task_path: The repo-relative TASK file path.
        limits_override: Limits replacing the packet's own, when supplied.

    Returns:
        The validated contract, ready for prompt rendering.

    Raises:
        ContractError: Any eligibility rule failed.
    """
    return await asyncio.to_thread(_validate_blocking, policy, task_path, limits_override)


# --------------------------------------------------------------------------- #
# Prompt rendering
# --------------------------------------------------------------------------- #
def render_prompt_sections(contract: ValidatedContract) -> dict[str, str]:
    """Render the deterministic prompt sections for a validated contract.

    The output contains only the approved packet and its approved excerpts —
    never whole repository files and never host conversation history.

    Args:
        contract: The validated contract.

    Returns:
        A mapping with ``packet``, ``references``, ``blocks`` and
        ``acceptance`` sections, each a Markdown heading plus fenced content.
    """
    packet_section = "## Packet\n\n```json\n" + compact_json(contract.packet.model_dump(mode="json")) + "\n```"

    reference_parts = ["## References"]
    for reference in contract.references:
        slice_ = reference.slice
        reference_parts.append(
            f"\n### {slice_.path} @ {slice_.sha256[:12]} lines {slice_.start_line}-{slice_.end_line} — {slice_.purpose}\n\n"
            f"```\n{reference.content}\n```"
        )
    if len(reference_parts) == 1:
        reference_parts.append("\n(none)")

    block_parts = ["## Implementation blocks"]
    for block_id in sorted(contract.blocks):
        block = contract.blocks[block_id]
        target = f" (file: {block.path})" if block.path else ""
        block_parts.append(f"\n### {block_id}{target}\n\n```{block.language}\n{block.text}\n```")

    acceptance_parts = ["## Acceptance criteria\n"]
    for criterion in contract.packet.acceptance_criteria:
        acceptance_parts.append(f"\n- {criterion}")

    return {
        "packet": packet_section,
        "references": "".join(reference_parts),
        "blocks": "".join(block_parts),
        "acceptance": "".join(acceptance_parts),
    }
