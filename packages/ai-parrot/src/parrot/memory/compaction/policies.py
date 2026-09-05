"""Per-tool prune policies for per-turn conversation compaction (FEAT-525).

A PRUNED view keeps the user message and assistant text intact and
replaces each tool invocation's I/O with a one-line notice carrying
enough to recover the bytes (``id="om_…"``) or to re-run the tool. Errors
are never omitted (spec C7).

All functions here are pure and synchronous; content ids are computed via
:func:`parrot.memory.compaction.omission.content_id`, the same function
the write-time offload (``ConversationMemory.add_turn``) uses, so ids
match whether an output was offloaded at write time or pruned later at
render time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import orjson

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import Limit, Omission, ToolInvocation, ToolStatus
from parrot.memory.compaction.omission import content_id

#: Version stamp for the pruning rules, in case the notice/line format
#: ever needs to change in a way older renders should not be replayed
#: against.
POLICY_VERSION: str = "1"


@dataclass(frozen=True)
class PrunedInvocation:
    """One invocation's rendered PRUNED-view line, plus any new omissions."""

    notice: str
    omissions: Tuple[Omission, ...]


class PrunePolicy(Protocol):
    """A per-tool strategy for rendering one invocation's PRUNED-view line."""

    name: str

    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        """Render ``inv`` for a PRUNED view.

        Args:
            inv: The invocation to render.
            turn_id: The owning turn's id (stamped on any new ``Omission``).
            limit: Bounds on the rendered line (only ``max_input_chars``
                is used here).

        Returns:
            The rendered line plus any newly created omissions.
        """
        ...


def format_invocation_line(inv: ToolInvocation, *, limit: Limit, body: str) -> str:
    """Build the shared ``"- {tool} {ok|error}[ {Ns}] in=... {body}"`` line.

    Args:
        inv: The invocation being rendered. Its ``input`` is canonicalized
            and truncated for the ``in=`` field — pass a copy with a
            narrowed ``input`` (e.g. via :func:`dataclasses.replace`) to
            show a restricted summary instead of the full arguments.
        limit: ``limit.max_input_chars`` bounds the ``in=`` field.
        body: Already-rendered notice / error fragment(s), joined with a
            single space and appended after ``in=...``.

    Returns:
        The formatted line.
    """
    status_word = "error" if (inv.status is ToolStatus.ERROR or inv.error) else "ok"
    elapsed = f" {inv.elapsed_ms / 1000:.1f}s" if inv.elapsed_ms is not None else ""

    canonical_input = orjson.dumps(inv.input, option=orjson.OPT_SORT_KEYS).decode()
    if len(canonical_input) > limit.max_input_chars:
        canonical_input = canonical_input[: limit.max_input_chars] + "…"

    line = f"- {inv.tool_name} {status_word}{elapsed} in={canonical_input}"
    if body:
        line = f"{line} {body}"
    return line


def omission_notice(inv: ToolInvocation, content_id_: str, chars: int) -> str:
    """Build the ``<tool-output-omitted .../>`` notice for one field.

    Args:
        inv: The invocation the omission belongs to (for ``tool_name``
            and ``wm_key``).
        content_id_: The id the content is (or will be) stored under.
        chars: The original content's character length.

    Returns:
        ``<tool-output-omitted tool="..." chars="..." id="..."[ wm="..."]/>``;
        the ``wm=`` attribute appears only when ``inv.wm_key`` is set.
    """
    wm = f' wm="{inv.wm_key}"' if inv.wm_key else ""
    return f'<tool-output-omitted tool="{inv.tool_name}" chars="{chars}" id="{content_id_}"{wm}/>'


def _pick_keys(data: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    """Return a new dict keeping only the first-present values for ``keys``."""
    return {k: data[k] for k in keys if k in data}


def _first_line(value: Any) -> Any:
    """Return the first line of a string value unchanged otherwise."""
    if isinstance(value, str) and value:
        return value.splitlines()[0]
    return value


def _try_parse_json(text: Optional[str]) -> Any:
    """Best-effort JSON parse; returns ``None`` on any failure or empty input."""
    if not text:
        return None
    try:
        return orjson.loads(text)
    except orjson.JSONDecodeError:
        return None


def _prune_shared(
    inv: ToolInvocation,
    *,
    turn_id: str,
    limit: Limit,
    narrowed_input: Optional[Dict[str, Any]] = None,
    extra_parts: Sequence[str] = (),
) -> PrunedInvocation:
    """Shared omission/notice/error rule set used by every built-in policy.

    Rules (spec §3 Module 7):
        1. ``"output" in inv.omitted`` → notice reusing the stored id and
           ``inv.output_chars``; no new :class:`Omission`.
        2. Else, a non-empty ``inv.output`` → notice for a freshly
           computed :func:`content_id`; one new :class:`Omission`.
        3. Otherwise → no notice (nothing to omit).
        4. ``inv.error`` is always appended verbatim (never omitted, C7),
           after any notice/extra summary.

    Args:
        inv: The invocation to render.
        turn_id: The owning turn's id.
        limit: Line-rendering bounds.
        narrowed_input: When given, the ``in=`` field shows this
            restricted view of the arguments instead of the full
            ``inv.input``.
        extra_parts: Additional summary fragments (e.g. ``"exit=0"``,
            ``"rows=12"``) inserted between the notice and the error.

    Returns:
        The rendered line plus any newly created omissions.
    """
    omissions: List[Omission] = []
    parts: List[str] = []

    if "output" in inv.omitted:
        chars = inv.output_chars if inv.output_chars is not None else len(inv.output or "")
        parts.append(omission_notice(inv, inv.omitted["output"], chars))
    elif inv.output:
        cid = content_id(inv.output)
        omissions.append(Omission(cid, inv.output, turn_id, inv.tool_name, "output"))
        parts.append(omission_notice(inv, cid, len(inv.output)))

    parts.extend(extra_parts)

    if inv.error:
        parts.append(f"error={inv.error}")

    line_source = inv if narrowed_input is None else replace(inv, input=narrowed_input)
    line = format_invocation_line(line_source, limit=limit, body=" ".join(p for p in parts if p))
    return PrunedInvocation(line, tuple(omissions))


class DefaultPolicy:
    """Fallback policy: the shared rule set, full ``in=`` arguments."""

    name = "default"

    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        return _prune_shared(inv, turn_id=turn_id, limit=limit)


class FileWritePolicy:
    """Keeps the target path in ``in=``; content is offloaded/omitted like the default."""

    name = "file_write"

    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        narrowed = _pick_keys(inv.input, ("path", "file_path", "filename"))
        return _prune_shared(inv, turn_id=turn_id, limit=limit, narrowed_input=narrowed)


class FileReadPolicy:
    """Keeps the source path in ``in=``; content is offloaded/omitted like the default."""

    name = "file_read"

    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        narrowed = _pick_keys(inv.input, ("path", "file_path", "filename"))
        return _prune_shared(inv, turn_id=turn_id, limit=limit, narrowed_input=narrowed)


class ShellPolicy:
    """Keeps the command in ``in=``; adds ``exit=`` when the output JSON carries one."""

    name = "shell"

    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        narrowed = _pick_keys(inv.input, ("command", "cmd"))
        extra: List[str] = []
        parsed = _try_parse_json(inv.output)
        if isinstance(parsed, dict):
            for key in ("exit_code", "exitcode", "returncode", "exit"):
                if key in parsed:
                    extra.append(f"exit={parsed[key]}")
                    break
        return _prune_shared(inv, turn_id=turn_id, limit=limit, narrowed_input=narrowed, extra_parts=extra)


class SubAgentPolicy:
    """Keeps only the first line of the delegated task/prompt in ``in=``."""

    name = "sub_agent"

    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        narrowed = {k: _first_line(inv.input[k]) for k in ("task", "prompt") if k in inv.input}
        return _prune_shared(inv, turn_id=turn_id, limit=limit, narrowed_input=narrowed)


class QueryPolicy:
    """Keeps the query/url in ``in=``; adds ``rows=``/``hits=`` when derivable from the output."""

    name = "query"

    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        narrowed = _pick_keys(inv.input, ("query", "sql", "url"))
        extra: List[str] = []
        parsed = _try_parse_json(inv.output)
        if isinstance(parsed, list):
            extra.append(f"rows={len(parsed)}")
        elif isinstance(parsed, dict):
            for key in ("rows", "results"):
                value = parsed.get(key)
                if isinstance(value, list):
                    extra.append(f"rows={len(value)}")
                    break
            else:
                hits = parsed.get("hits")
                if isinstance(hits, list):
                    extra.append(f"hits={len(hits)}")
                elif hits is not None:
                    extra.append(f"hits={hits}")
        return _prune_shared(inv, turn_id=turn_id, limit=limit, narrowed_input=narrowed, extra_parts=extra)


#: Starter alias table mapping known tool names to a built-in policy.
#: Small and editable — unknown names fall back to :class:`DefaultPolicy`.
_BUILTIN_ALIASES: Dict[str, PrunePolicy] = {
    "write_file": FileWritePolicy(),
    "save_file": FileWritePolicy(),
    "read_file": FileReadPolicy(),
    "open_file": FileReadPolicy(),
    "bash": ShellPolicy(),
    "shell": ShellPolicy(),
    "run_command": ShellPolicy(),
    "execute_command": ShellPolicy(),
    "delegate": SubAgentPolicy(),
    "run_subagent": SubAgentPolicy(),
    "spawn_agent": SubAgentPolicy(),
    "query_database": QueryPolicy(),
    "execute_query": QueryPolicy(),
    "sql_query": QueryPolicy(),
    "http_request": QueryPolicy(),
    "fetch_url": QueryPolicy(),
    "web_search": QueryPolicy(),
    "search": QueryPolicy(),
}

#: Registry populated by :func:`register_policy`; consulted before the
#: built-in alias table so callers can override any name, including ones
#: already in :data:`_BUILTIN_ALIASES`.
_REGISTRY: Dict[str, PrunePolicy] = {}


def register_policy(tool_name: str, policy: PrunePolicy) -> None:
    """Register (or override) the policy used for ``tool_name``.

    Args:
        tool_name: The exact tool name to match.
        policy: The policy to use for it.
    """
    _REGISTRY[tool_name] = policy


def get_policy(tool_name: str) -> PrunePolicy:
    """Resolve the policy for a tool name.

    Lookup order: the :func:`register_policy` registry (exact name), then
    the built-in alias table, then :class:`DefaultPolicy`.

    Args:
        tool_name: The tool name to resolve.

    Returns:
        The resolved policy.
    """
    if tool_name in _REGISTRY:
        return _REGISTRY[tool_name]
    if tool_name in _BUILTIN_ALIASES:
        return _BUILTIN_ALIASES[tool_name]
    return DefaultPolicy()


def prune_turn(
    turn: ConversationTurn,
    *,
    limit: Limit = Limit(),
    policies: Optional[Dict[str, PrunePolicy]] = None,
) -> Tuple[str, Tuple[Omission, ...]]:
    """Render the PRUNED-view ``<tool-activity>`` suffix for a turn.

    Pure: does not read ``context_used`` and does not mutate ``turn``.

    Args:
        turn: The turn to render.
        limit: Bounds on each rendered line.
        policies: When given, consulted before the module registry /
            built-in alias table for each invocation's tool name.

    Returns:
        A tuple of ``(assistant_suffix, omissions)``. ``assistant_suffix``
        is ``""`` for a turn with no invocations; otherwise it wraps one
        line per invocation in ``<tool-activity>...</tool-activity>``,
        followed by a recovery hint line **iff** at least one
        ``<tool-output-omitted`` notice was emitted.
    """
    if not turn.tool_invocations:
        return "", ()

    lines: List[str] = []
    omissions: List[Omission] = []
    has_notice = False

    for inv in turn.tool_invocations:
        policy = None
        if policies is not None and inv.tool_name in policies:
            policy = policies[inv.tool_name]
        if policy is None:
            policy = get_policy(inv.tool_name)

        pruned = policy.prune(inv, turn_id=turn.turn_id, limit=limit)
        lines.append(pruned.notice)
        omissions.extend(pruned.omissions)
        if "<tool-output-omitted" in pruned.notice:
            has_notice = True

    suffix = "\n\n<tool-activity>\n" + "\n".join(lines) + "\n</tool-activity>"
    if has_notice:
        suffix += (
            "\nOmitted content can be recovered with read_omitted_content(content_id) "
            f'or read_omitted_content(turn_id="{turn.turn_id}").'
        )
    return suffix, tuple(omissions)
