"""Stage 0 normalization for conversation turns (FEAT-525).

All functions are pure, synchronous, and depend on stdlib + ``orjson``
only. They make stored bytes canonical so token counts are stable,
content ids are stable across writers, and tracebacks do not dominate a
turn.

``normalize_turn(normalize_turn(t)) == normalize_turn(t)`` is a tested
property (idempotence).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Optional

import orjson

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolInvocation

#: Version stamp recorded on every normalized turn (``ConversationTurn.norm_version``).
NORM_VERSION: str = "1"

#: CSI sequences, e.g. ``\x1b[31m`` (color), ``\x1b[0m`` (reset).
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
#: OSC sequences, e.g. ``\x1b]0;title\x07``.
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*\x07")
#: SS3 sequences (single shift three), e.g. ``\x1bOP``.
_ANSI_SS3_RE = re.compile(r"\x1bO.")
#: C0 control characters except ``\n`` (0x0a) and ``\t`` (0x09).
_C0_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
#: Trailing whitespace on each line.
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
#: Runs of 4+ newlines (i.e. 3+ blank lines) collapse to 2 blank lines ("\n\n\n").
_BLANK_RUN_RE = re.compile(r"\n{4,}")

_TRACEBACK_HEADER = "Traceback (most recent call last):"
_FRAME_RE = re.compile(r'  File "[^\n]*\n(?:    [^\n]*\n)*')


def normalize_text(text: str) -> str:
    """Apply normalization rules 1-3 to a string, in order.

    Rules:
        1. Unicode NFC normalization.
        2. Strip ANSI escape sequences (CSI/OSC/SS3) and C0 control
           characters except ``\\n``/``\\t``; ``\\r\\n`` becomes ``\\n``.
        3. Strip trailing whitespace per line; collapse runs of 3+ blank
           lines to 2.

    Args:
        text: The raw text to normalize.

    Returns:
        The normalized text.
    """
    out = unicodedata.normalize("NFC", text)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = _ANSI_CSI_RE.sub("", out)
    out = _ANSI_OSC_RE.sub("", out)
    out = _ANSI_SS3_RE.sub("", out)
    out = _C0_RE.sub("", out)
    out = _TRAILING_WS_RE.sub("", out)
    out = _BLANK_RUN_RE.sub("\n\n\n", out)
    return out


def canonical_json_text(text: str) -> str:
    """Rewrite ``text`` as canonical (key-sorted) JSON if it is a JSON object/array.

    Args:
        text: The candidate JSON text.

    Returns:
        The canonical JSON text when ``text.strip()`` parses to a ``dict``
        or ``list``; otherwise ``text`` unchanged (scalars like ``"42"`` or
        ``"true"`` are left alone).
    """
    stripped = text.strip()
    if not stripped:
        return text
    try:
        obj = orjson.loads(stripped)
    except orjson.JSONDecodeError:
        return text
    if not isinstance(obj, (dict, list)):
        return text
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode()


def condense_traceback(text: str, *, keep_frames: int = 3) -> str:
    """Condense a Python traceback to its header, last frames, and exception line.

    Args:
        text: The candidate traceback text.
        keep_frames: Number of trailing ``File "..."`` frame blocks to keep.

    Returns:
        The condensed text when ``text`` contains a traceback header;
        otherwise ``text`` unchanged. The final exception line is always
        kept verbatim so errors stay searchable (spec C7).
    """
    if _TRACEBACK_HEADER not in text:
        return text

    header_idx = text.index(_TRACEBACK_HEADER)
    header = text[header_idx : header_idx + len(_TRACEBACK_HEADER)]
    rest = text[header_idx + len(_TRACEBACK_HEADER) :]
    if rest.startswith("\n"):
        rest = rest[1:]

    frames = _FRAME_RE.findall(rest)
    frames_end = 0
    for match in _FRAME_RE.finditer(rest):
        frames_end = match.end()
    exception_tail = rest[frames_end:].strip("\n")

    kept_frames = frames[-keep_frames:] if keep_frames > 0 else []
    lines = [header]
    lines.extend(frame.rstrip("\n") for frame in kept_frames)
    if exception_tail:
        lines.append(exception_tail)
    return "\n".join(lines)


def normalize_invocation(inv: ToolInvocation) -> ToolInvocation:
    """Return a new :class:`ToolInvocation` with normalized text fields.

    Args:
        inv: The invocation to normalize.

    Returns:
        A new ``ToolInvocation``: ``input`` canonicalized (rule 4);
        ``output`` through :func:`normalize_text` then
        :func:`canonical_json_text`; ``error`` through
        :func:`normalize_text` then :func:`condense_traceback`. All other
        fields are copied unchanged.
    """
    canonical_input = orjson.loads(
        orjson.dumps(inv.input, option=orjson.OPT_SORT_KEYS)
    )

    output: Optional[str] = inv.output
    if output is not None:
        output = canonical_json_text(normalize_text(output))

    error: Optional[str] = inv.error
    if error is not None:
        error = condense_traceback(normalize_text(error))

    return ToolInvocation(
        tool_name=inv.tool_name,
        input=canonical_input,
        output=output,
        status=inv.status,
        error=error,
        elapsed_ms=inv.elapsed_ms,
        output_chars=inv.output_chars,
        omitted=dict(inv.omitted),
        wm_key=inv.wm_key,
    )


def normalize_turn(turn: ConversationTurn) -> ConversationTurn:
    """Return a new, normalized :class:`ConversationTurn`.

    Never mutates ``turn``. Idempotent:
    ``normalize_turn(normalize_turn(t)) == normalize_turn(t)``.

    Args:
        turn: The turn to normalize.

    Returns:
        A new turn with ``user_message``, ``assistant_response`` and
        ``context_used`` run through :func:`normalize_text`; ``error``
        run through :func:`normalize_text` then
        :func:`condense_traceback`; every invocation normalized via
        :func:`normalize_invocation`; ``norm_version`` stamped to
        :data:`NORM_VERSION`.
    """
    context_used = (
        normalize_text(turn.context_used) if turn.context_used is not None else None
    )
    error = (
        condense_traceback(normalize_text(turn.error))
        if turn.error is not None
        else None
    )

    return replace(
        turn,
        user_message=normalize_text(turn.user_message),
        assistant_response=normalize_text(turn.assistant_response),
        context_used=context_used,
        error=error,
        tool_invocations=[normalize_invocation(inv) for inv in turn.tool_invocations],
        norm_version=NORM_VERSION,
    )
