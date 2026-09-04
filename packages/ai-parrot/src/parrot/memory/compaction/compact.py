"""``compact_history`` — the pure three-tier retention pre-pass (FEAT-525).

This is the heart of the feature: a pure, synchronous function that turns
a :class:`~parrot.memory.abstract.ConversationHistory` plus a
:class:`~parrot.memory.compaction.models.ContextBudget` into
:class:`~parrot.memory.compaction.models.TurnView` objects (RAW or
PRUNED, with the ``assistant_suffix`` already materialized) and the list
of :class:`~parrot.memory.compaction.models.Omission` s the bot must
flush before rendering. Nothing here touches a store, the network, or
mutates its inputs.
"""

from __future__ import annotations

import math
from typing import Collection, Dict, List, Optional, Set, Tuple

from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import (
    CompactionResult,
    ContextBudget,
    Limit,
    Omission,
    TurnState,
    TurnView,
)
from parrot.memory.compaction.policies import PrunePolicy, format_invocation_line, get_policy, prune_turn
from parrot.memory.compaction.tokens import TokenCounter, count_turn, get_default_counter, needs_recount


def _is_foreign(turn: ConversationTurn, current_chatbot_id: Optional[str]) -> bool:
    """Whether ``turn`` belongs to an agent other than ``current_chatbot_id``."""
    return (
        current_chatbot_id is not None
        and turn.chatbot_id is not None
        and turn.chatbot_id != current_chatbot_id
    )


def render_raw_view(
    turn: ConversationTurn,
    limit: Limit,
    *,
    oversize: Collection[int] = (),
    policies: Optional[Dict[str, PrunePolicy]] = None,
    counter: TokenCounter,
) -> Tuple[str, Tuple[Omission, ...]]:
    """Render the RAW-view ``<tool-activity>`` suffix for a turn.

    Every invocation renders in full (name, status, elapsed, canonical
    input, output excerpt, error) **except** those whose index is in
    ``oversize`` — those go through their :class:`PrunePolicy` instead
    (the oversize rule applied inside the verbatim tier: any output above
    ``budget.oversize_tool_tokens`` is pruned in every turn but the
    newest, even when the turn itself renders RAW).

    Args:
        turn: The turn to render.
        limit: Bounds on the block (``max_invocations``, ``max_output_chars``,
            ``max_block_tokens``).
        oversize: Indices (into ``turn.tool_invocations``) to render
            through their prune policy instead of as a full excerpt.
        policies: Consulted before the module registry for oversize
            invocations (see :func:`~parrot.memory.compaction.policies.prune_turn`).
        counter: Used only to decide whether the whole block must be
            collapsed under ``limit.max_block_tokens``.

    Returns:
        A tuple of ``(assistant_suffix, omissions)``. ``assistant_suffix``
        is ``""`` when the turn has no invocations.
    """
    if not turn.tool_invocations:
        return "", ()

    considered = turn.tool_invocations[: limit.max_invocations]
    lines: List[str] = []
    omissions: List[Omission] = []

    for idx, inv in enumerate(considered):
        # An invocation renders through its PrunePolicy (a notice, not a
        # raw excerpt) when the render-time oversize check flags it, OR
        # when its output was already offloaded at write time — `inv.output`
        # is then only the ≤200-char preview, and the line must still carry
        # the write-time notice via the policy instead of a plain `out=`.
        if idx in oversize or "output" in inv.omitted:
            policy = None
            if policies is not None and inv.tool_name in policies:
                policy = policies[inv.tool_name]
            if policy is None:
                policy = get_policy(inv.tool_name)
            pruned = policy.prune(inv, turn_id=turn.turn_id, limit=limit)
            lines.append(pruned.notice)
            omissions.extend(pruned.omissions)
            continue

        parts: List[str] = []
        if inv.output:
            excerpt = inv.output[: limit.max_output_chars]
            if len(inv.output) > limit.max_output_chars:
                excerpt += f" …(+{len(inv.output) - limit.max_output_chars:,} chars)"
            parts.append(f"out={excerpt}")
        if inv.error:
            parts.append(f"error={inv.error}")
        lines.append(format_invocation_line(inv, limit=limit, body=" ".join(parts)))

    remaining = len(turn.tool_invocations) - len(considered)
    if remaining > 0:
        lines.append(f"… +{remaining} more")

    if counter.count("\n".join(lines)) > limit.max_block_tokens:
        kept_lines = list(lines)
        dropped = 0
        while kept_lines and counter.count("\n".join(kept_lines)) > limit.max_block_tokens:
            kept_lines.pop()
            dropped += 1
        if dropped > 0:
            kept_lines.append(f"… +{dropped} more")
        lines = kept_lines

    block = "\n".join(lines)
    return f"\n\n<tool-activity>\n{block}\n</tool-activity>", tuple(omissions)


def render_tool_activity(turn: ConversationTurn, limit: Limit) -> str:
    """Render the RAW-view ``<tool-activity>`` suffix, with no oversize exceptions.

    Convenience wrapper over :func:`render_raw_view` for the common case
    (no oversize indices). Uses an internal, offline
    :class:`~parrot.memory.compaction.tokens.HeuristicCounter` for its own
    ``max_block_tokens`` collapsing check — callers that need the
    calibrated counter for the walk itself should call
    :func:`render_raw_view` directly.

    Args:
        turn: The turn to render.
        limit: Bounds on the block.

    Returns:
        The rendered suffix, or ``""`` when the turn has no invocations.
    """
    from parrot.memory.compaction.tokens import HeuristicCounter

    suffix, _omissions = render_raw_view(turn, limit, counter=HeuristicCounter())
    return suffix


def compact_history(
    history: ConversationHistory,
    budget: ContextBudget,
    *,
    policies: Optional[Dict[str, PrunePolicy]] = None,
    boundary_turn_id: Optional[str] = None,
    counter: Optional[TokenCounter] = None,
    calibration: float = 1.0,
    current_chatbot_id: Optional[str] = None,
    include_other_agents: bool = True,
) -> CompactionResult:
    """Walk a history newest → oldest and classify each turn RAW / PRUNED / DROPPED.

    Pure and synchronous (spec G1/G9): never mutates ``history``, its
    turns, or their invocations; performs no I/O; the same inputs always
    produce an equal :class:`CompactionResult`.

    Three tiers (spec G10), walked newest → oldest with a running
    calibrated token sum:

    1. **Verbatim (RAW)** while ``n_raw < budget.min_verbatim_turns`` or
       the cumulative size stays within both ``budget.verbatim_tokens``
       and the high-watermark budget.
    2. **Pruned** while the cumulative size stays within the high
       watermark (or the turn is the newest kept turn — the newest is
       never dropped).
    3. **Dropped** beyond that — and every older turn is dropped too
       (tiers are contiguous); sets ``stage2_needed``.

    A persisted ``boundary_turn_id`` forces every turn at or before it to
    render PRUNED regardless of budget (monotonic: turns that once
    rendered PRUNED never render RAW again for this history). Any
    invocation whose output exceeds ``budget.oversize_tool_tokens`` is
    pruned in every turn but the newest, even inside the verbatim tier.

    Args:
        history: The history to compact.
        budget: The retention configuration.
        policies: Per-tool prune-policy overrides, consulted before the
            module registry.
        boundary_turn_id: The previously persisted boundary, if any.
        counter: The token counter to size turns and rendered blocks
            with. Defaults to :func:`~parrot.memory.compaction.tokens.get_default_counter`.
        calibration: Multiplier applied to every calibrated size (the
            memory's EWMA of provider/estimate ratio).
        current_chatbot_id: The agent doing the asking, for the foreign-turn
            rule (mirrors :func:`~parrot.memory.render.render_history`).
        include_other_agents: When ``False``, foreign turns are excluded
            from consideration entirely (not even counted as dropped).

    Returns:
        A :class:`CompactionResult` with ``views`` ordered oldest → newest,
        ready for :func:`~parrot.memory.render.render_history`.
    """
    counter = counter or get_default_counter()
    available = budget.available
    watermark = int(budget.high_watermark * available)

    candidates = [
        t
        for t in history.turns
        if (t.assistant_response or "").strip() and (include_other_agents or not _is_foreign(t, current_chatbot_id))
    ]

    if len(candidates) > budget.max_turns:
        ceiling_dropped: Tuple[str, ...] = tuple(t.turn_id for t in candidates[: -budget.max_turns])
        kept = candidates[-budget.max_turns :]
    else:
        ceiling_dropped = ()
        kept = candidates

    boundary_index = next((i for i, t in enumerate(kept) if t.turn_id == boundary_turn_id), None)

    views_rev: List[TurnView] = []
    omissions: List[Omission] = []
    seen_content_ids: Set[str] = set()
    cum = 0
    n_raw = 0
    pruned_seen = False
    watermark_overflow = False
    extra_dropped_rev: List[str] = []

    last_index = len(kept) - 1
    for idx in range(last_index, -1, -1):
        turn = kept[idx]
        newest = idx == last_index

        tc = turn.token_count if not needs_recount(turn, counter) else count_turn(turn, counter)

        # An invocation counts as "oversize" for the render-time rule when
        # its current output still exceeds the threshold, OR when it was
        # already offloaded at write time (`inv.output` is then just the
        # preview — small, but the content is gone regardless of size).
        oversize = (
            ()
            if newest
            else tuple(
                i
                for i, inv in enumerate(turn.tool_invocations)
                if "output" in inv.omitted or counter.count(inv.output or "") > budget.oversize_tool_tokens
            )
        )

        forced = boundary_index is not None and idx <= boundary_index

        raw_suffix, raw_omissions = render_raw_view(
            turn, budget.tool_activity_limit, oversize=oversize, policies=policies, counter=counter
        )
        raw_size = math.ceil(calibration * (tc.user + tc.assistant + counter.count(raw_suffix)))

        pr_suffix, pr_omissions = prune_turn(turn, limit=budget.tool_activity_limit, policies=policies)
        pr_size = math.ceil(calibration * (tc.user + tc.assistant + counter.count(pr_suffix)))

        # A turn with an oversize invocation can never be classified RAW —
        # its "verbatim" rendering already collapses that invocation to the
        # same notice PRUNED would use (spec: oversize applies "even in the
        # verbatim tier"). Without this, `min_verbatim_turns` would force
        # such turns RAW purely on their (now-tiny, notice-only) rendered
        # size, defeating the pruned tier for every oversize-heavy history.
        has_oversize = len(oversize) > 0

        if (
            not forced
            and not pruned_seen
            and not has_oversize
            and (
                n_raw < budget.min_verbatim_turns
                or (cum + raw_size <= budget.verbatim_tokens and cum + raw_size <= watermark)
            )
        ):
            state: Optional[TurnState] = TurnState.RAW
        elif cum + pr_size <= watermark or n_raw == 0:
            state = TurnState.PRUNED
        else:
            state = None

        if state is None:
            watermark_overflow = True
            for j in range(idx, -1, -1):
                extra_dropped_rev.append(kept[j].turn_id)
            break

        if state is TurnState.RAW:
            views_rev.append(
                TurnView(
                    turn_id=turn.turn_id,
                    chatbot_id=turn.chatbot_id,
                    user_text=turn.user_message or "",
                    assistant_text=turn.assistant_response or "",
                    assistant_suffix=raw_suffix,
                    state=TurnState.RAW,
                    estimated_tokens=raw_size,
                )
            )
            for om in raw_omissions:
                if om.content_id not in seen_content_ids:
                    seen_content_ids.add(om.content_id)
                    omissions.append(om)
            cum += raw_size
            n_raw += 1
        else:
            views_rev.append(
                TurnView(
                    turn_id=turn.turn_id,
                    chatbot_id=turn.chatbot_id,
                    user_text=turn.user_message or "",
                    assistant_text=turn.assistant_response or "",
                    assistant_suffix=pr_suffix,
                    state=TurnState.PRUNED,
                    estimated_tokens=pr_size,
                )
            )
            for om in pr_omissions:
                if om.content_id not in seen_content_ids:
                    seen_content_ids.add(om.content_id)
                    omissions.append(om)
            cum += pr_size
            pruned_seen = True

    views = tuple(reversed(views_rev))
    dropped_turn_ids = ceiling_dropped + tuple(reversed(extra_dropped_rev))

    stage2_needed = watermark_overflow or cum > available

    pruned_views = [v for v in views if v.state is TurnState.PRUNED]
    new_boundary = pruned_views[-1].turn_id if pruned_views else boundary_turn_id

    return CompactionResult(
        views=views,
        omissions=tuple(omissions),
        history_estimate=cum,
        boundary_turn_id=new_boundary,
        stage2_needed=stage2_needed,
        dropped_turn_ids=dropped_turn_ids,
    )
