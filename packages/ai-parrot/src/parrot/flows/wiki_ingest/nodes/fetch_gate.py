"""Fetch-gate node — the agent's own participant-filtered fetch loop +
dedup gate (FEAT-481, spec Module 2).

**Additive-only (G11).** Mirrors the fetch/pagination *pattern* already
used by ``FirefliesObsidianAgent.sync_fireflies_transcripts`` (inherits
``add_fireflies_mcp_server`` from ``MCPEnabledMixin``, imports
``FirefliesFilters``) in this subsystem's **own** loop — never calls or
modifies ``agents/obsidian.py``. Unlike that agent's listing parser
(``_parse_fireflies_response``, which truncates ``dateString`` to
``YYYY-MM-DD``), this module's own parser keeps the **full** ISO
``dateString`` so a later node (spec Module 8) can render meeting
filenames in the meeting's original timezone (§8.4) rather than losing
that information here.

**No revisions (R3).** ``MeetingRegistry.classify()`` is a generic
create/skip/revise oracle — a "revise" outcome means "the id is known but
the content hash changed". This subsystem's contract amendment (R3)
means transcripts are immutable: a known id is a **permanent skip**
regardless of hash — so a "revise" from ``classify()`` is mapped to
``duplicate-skip`` here, never fetched again, never treated as an update.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.agents.meeting_registry import MeetingRegistry
from parrot.agents.obsidian import FirefliesFilters

from .. import conf

logger = logging.getLogger(__name__)

#: Fireflies MCP tool call cap per page (mirrors
#: FirefliesObsidianAgent.sync_fireflies_transcripts).
_PAGE_SIZE_CAP = 50


class GatedMeeting(BaseModel):
    """One Fireflies listing item after the dedup gate has run.

    Attributes:
        fireflies_id: The raw Fireflies transcript id.
        source_id: ``"fireflies:<id>"`` (D4).
        title: Meeting title from the listing.
        meeting_date: ``YYYY-MM-DD`` (Fireflies-reported, NOT necessarily
            the meeting's original-timezone date — Module 8's renderer
            re-derives that from ``meeting_date_iso``).
        meeting_date_iso: The full, untruncated ``dateString`` from the
            listing (preserves timezone/offset — §8.4).
        participants: Participant emails from the listing.
        duration_minutes: Meeting duration in minutes.
        outcome: ``"fetch"`` (new/unknown id — fetched this call),
            ``"skip"`` (known id, unchanged — no fetch, or rejected),
            or ``"duplicate-skip"`` (known id, content differs — a
            permanent skip per R3, never a revision).
        transcript_text: Full transcript text, when ``outcome == "fetch"``.
        summary_text: Fireflies native summary text, when fetched and
            available.
        fingerprint: Transcript ``sha256`` (only computed when fetched).
        summary_fingerprint: Summary ``sha256`` (only computed when
            fetched and available).
    """

    fireflies_id: str
    source_id: str
    title: str
    meeting_date: str
    meeting_date_iso: str | None = None
    participants: list[str] = Field(default_factory=list)
    duration_minutes: float = 0.0
    outcome: Literal["fetch", "skip", "duplicate-skip"]
    transcript_text: str | None = None
    summary_text: str | None = None
    fingerprint: str | None = None
    summary_fingerprint: str | None = None


async def _call_fireflies_tool(agent: Any, tool_name: str, args: dict[str, Any]) -> Any:
    """Call a Fireflies MCP tool via the agent's own ``tool_manager``.

    Mirrors ``FirefliesObsidianAgent._call_fireflies_tool`` — a small,
    independent helper (spec Module 2), not a reuse of that method.

    Args:
        agent: The agent instance (``tool_manager`` + MCP tools already
            registered via :func:`_ensure_fireflies_mcp`).
        tool_name: Fireflies tool name (e.g. ``"fireflies_get_transcripts"``).
        args: Tool arguments.

    Returns:
        The tool's ``ToolResult``.

    Raises:
        ValueError: If the tool is not registered.
    """
    full_name = f"mcp_fireflies_{tool_name}"
    tool = agent.tool_manager.get_tool(full_name)
    if not tool:
        raise ValueError(f"Tool not found: {full_name}")
    return await tool.execute(**args)


async def _ensure_fireflies_mcp(agent: Any, *, api_key: str | None = None) -> None:
    """Lazily register the Fireflies MCP server on ``agent`` (once).

    Args:
        agent: The agent instance (``add_fireflies_mcp_server`` from
            ``MCPEnabledMixin``, inherited via ``BasicAgent`` — no edit
            needed).
        api_key: Optional explicit Fireflies API key (falls back to
            ``FIREFLIES_API_KEY`` inside ``add_fireflies_mcp_server``).
    """
    if getattr(agent, "_wiki_kb_fireflies_mcp_ready", False):
        return
    await agent.add_fireflies_mcp_server(api_key=api_key)
    agent._wiki_kb_fireflies_mcp_ready = True


def _parse_fireflies_listing(response_text: str) -> list[dict[str, Any]]:
    """Parse a ``fireflies_get_transcripts`` listing response.

    A self-contained parser for this subsystem's own loop (spec Module 2
    — "mirror the pattern", not reuse ``FirefliesObsidianAgent``'s
    private parser). Unlike that parser, ``dateString`` is preserved in
    full (``date_iso``) alongside the truncated ``YYYY-MM-DD`` (``date``)
    so a later node can recover the meeting's original timezone (§8.4).

    Args:
        response_text: Raw MCP tool response text.

    Returns:
        A list of dicts with keys ``id``, ``title``, ``date``,
        ``date_iso``, ``participants``, ``duration``.
    """
    items: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    in_participants = False

    for line in response_text.split("\n"):
        stripped = line.strip()

        if not stripped or stripped.startswith("["):
            in_participants = False
            continue

        if stripped.startswith("- id:"):
            if current and "id" in current:
                items.append(current)
            current = {"participants": []}
            try:
                _, id_value = stripped.split(":", 1)
                current["id"] = id_value.strip().strip('"')
            except ValueError:
                pass
            in_participants = False
            continue

        if "participants" in stripped.lower() and stripped.endswith("{"):
            in_participants = True
            continue

        if in_participants and stripped and not stripped.startswith("{") and not stripped.startswith("}"):
            if "@" in stripped:
                email = stripped.rstrip(",")
                if email and email not in current.get("participants", []):
                    current.setdefault("participants", []).append(email)
            continue

        if ":" in stripped and not stripped.startswith("-") and not in_participants:
            try:
                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').rstrip(",")
                if key == "title":
                    current["title"] = value
                elif key == "dateString":
                    current["date_iso"] = value
                    current["date"] = value[:10]
                elif key == "organizer_email":
                    current["organizer"] = value
                    if value not in current.get("participants", []):
                        current.setdefault("participants", []).append(value)
                elif key == "duration":
                    try:
                        current["duration"] = float(value)
                    except ValueError:
                        pass
            except ValueError:
                pass

    if current and "id" in current:
        items.append(current)
    return items


def _scan_raw_processed_ids(raw_processed_root: Path) -> set[str]:
    """Scan ``Raw/Processed/`` for already-captured source ids.

    A `Raw/` bundle for source id ``<id>`` lives in a directory named
    ``<id>`` (the raw Fireflies id, sanitized, WITHOUT the ``"fireflies:"``
    prefix — a literal colon is Obsidian-unsafe punctuation, §8.2)
    containing a ``transcript.*`` file (spec Module 3 convention).

    Args:
        raw_processed_root: The ``Raw/Processed/`` directory (may not
            exist yet on a fresh vault).

    Returns:
        The set of raw Fireflies ids found (∪ the ``MeetingRegistry`` gate
        — spec Module 2).
    """
    if not raw_processed_root.is_dir():
        return set()
    return {transcript_file.parent.name for transcript_file in raw_processed_root.rglob("transcript.*")}


def _resolve_from_date(
    *,
    since: str | None,
    lookback_days: int | None,
    suggested: str | None,
    max_catchup_days: int,
) -> str | None:
    """Resolve the effective listing ``fromDate`` (G10 catch-up bound).

    Precedence: explicit ``since`` > ``lookback_days`` > the registry's
    ``suggest_from_date()`` watermark. The result is never older than
    ``max_catchup_days`` ago, so a manual wide-window request cannot
    trigger an unbounded reconciliation (spec Module 1
    ``WIKI_KB_MAX_CATCHUP_DAYS``).

    Args:
        since: Explicit ISO date lower bound.
        lookback_days: Days back from today, alternative to ``since``.
        suggested: ``MeetingRegistry.suggest_from_date()``'s watermark.
        max_catchup_days: The large-backlog guard.

    Returns:
        The effective ``fromDate`` (``YYYY-MM-DD``), or ``None`` when no
        bound applies (fresh registry, no override — fetch everything).
    """
    today = datetime.now(UTC).date()
    floor_date = (today - timedelta(days=max_catchup_days)).isoformat()

    candidate: str | None
    if since is not None:
        candidate = since
    elif lookback_days is not None:
        candidate = (today - timedelta(days=lookback_days)).isoformat()
    else:
        candidate = suggested

    if candidate is None:
        return None
    return max(candidate, floor_date)


async def run_fetch_gate(
    agent: Any,
    *,
    registry: MeetingRegistry,
    raw_processed_root: Path | None = None,
    limit: int | None = None,
    force_refetch: bool = False,
    since: str | None = None,
    lookback_days: int | None = None,
    api_key: str | None = None,
) -> list[GatedMeeting]:
    """Fetch participant-filtered Fireflies meetings through the dedup gate.

    Never re-downloads an already-processed meeting (G2): the gate is
    ``MeetingRegistry.classify()`` (∪ a scan of ``Raw/Processed/``) —
    GraphIndex is never consulted here. A "revise" outcome (content
    changed for a known id) is a permanent ``duplicate-skip`` (R3) — this
    subsystem has no revision workflow.

    Args:
        agent: The agent instance — needs ``tool_manager`` and
            ``add_fireflies_mcp_server`` (inherited via
            ``MCPEnabledMixin`` → ``BasicAgent``).
        registry: This subsystem's own :class:`MeetingRegistry` (spec
            Module 4's ``build_meeting_registry()``).
        raw_processed_root: The vault's ``Raw/Processed/`` directory, for
            the ∪ scan. ``None`` skips the scan (e.g. a fresh vault).
        limit: Max meetings to fetch, total across pages (default: no
            cap beyond the API's own page size).
        force_refetch: Bypass the cheap-skip path and always refetch +
            fingerprint a known id (still yields ``duplicate-skip`` if the
            id is already recorded — R3 is unconditional).
        since: ISO date lower bound for a manual wide-window fetch.
        lookback_days: Alternative to ``since`` — days back from today.
        api_key: Optional explicit Fireflies API key.

    Returns:
        :class:`GatedMeeting` entries — unsorted (the orchestrator, spec
        Module 6, sorts the whole batch oldest→newest by ``meeting_date``).
    """
    await _ensure_fireflies_mcp(agent, api_key=api_key)

    filters = FirefliesFilters(participants=list(conf.WIKI_KB_PARTICIPANTS))
    filter_args: dict[str, Any] = {}
    if filters.participants:
        filter_args["participants"] = [str(p) for p in filters.participants]

    suggested = await registry.suggest_from_date(overlap_days=conf.FIREFLIES_SYNC_OVERLAP_DAYS)
    from_date = _resolve_from_date(
        since=since,
        lookback_days=lookback_days,
        suggested=suggested,
        max_catchup_days=conf.WIKI_KB_MAX_CATCHUP_DAYS,
    )
    if from_date is not None:
        filter_args["fromDate"] = from_date

    effective_limit = limit if limit is not None else conf.WIKI_KB_INGEST_LIMIT

    raw_known_ids = _scan_raw_processed_ids(raw_processed_root) if raw_processed_root is not None else set()

    listing: list[dict[str, Any]] = []
    skip = 0
    while effective_limit is None or len(listing) < effective_limit:
        page_limit = _PAGE_SIZE_CAP if effective_limit is None else min(_PAGE_SIZE_CAP, effective_limit - len(listing))
        if page_limit <= 0:
            break
        tool_result = await _call_fireflies_tool(
            agent, "fireflies_get_transcripts", {**filter_args, "limit": page_limit, "skip": skip}
        )
        if not tool_result or not getattr(tool_result, "success", False):
            break
        page = _parse_fireflies_listing(tool_result.result)
        listing.extend(page)
        if len(page) < page_limit:
            break
        skip += page_limit

    gated: list[GatedMeeting] = []
    for item in listing:
        fireflies_id = item["id"]
        if fireflies_id in raw_known_ids:
            gated.append(
                GatedMeeting(
                    fireflies_id=fireflies_id,
                    source_id=f"fireflies:{fireflies_id}",
                    title=item.get("title", "Untitled Meeting"),
                    meeting_date=item.get("date", ""),
                    meeting_date_iso=item.get("date_iso"),
                    participants=item.get("participants", []),
                    duration_minutes=item.get("duration", 0.0),
                    outcome="skip",
                )
            )
            continue

        gated.append(await _classify_one(agent, registry, item, force_refetch=force_refetch))

    return gated


async def _classify_one(
    agent: Any,
    registry: MeetingRegistry,
    item: dict[str, Any],
    *,
    force_refetch: bool,
) -> GatedMeeting:
    """Run ``MeetingRegistry.classify()`` for one listing item.

    Args:
        agent: The agent instance (for the fetch/fetch_summary callbacks).
        registry: This subsystem's :class:`MeetingRegistry`.
        item: One parsed listing item (see :func:`_parse_fireflies_listing`).
        force_refetch: Bypass the cheap-skip path.

    Returns:
        The resulting :class:`GatedMeeting`.
    """
    fireflies_id = item["id"]
    # MeetingRegistry.classify() returns fetched_text (transcript) but only
    # the summary's *fingerprint* — cache the summary text itself as a
    # side effect of the fetch_summary callback (same pattern
    # FirefliesObsidianAgent._sync_via_registry uses).
    summary_cache: dict[str, str] = {}

    async def _fetch(tid: str) -> str:
        result = await _call_fireflies_tool(agent, "fireflies_get_transcript", {"transcriptId": tid})
        return result.result if hasattr(result, "result") else str(result)

    async def _fetch_summary(tid: str) -> str | None:
        try:
            result = await _call_fireflies_tool(agent, "fireflies_get_summary", {"transcriptId": tid})
            if result and getattr(result, "success", False):
                text = result.result if hasattr(result, "result") else str(result)
                summary_cache[tid] = text
                return text
        except Exception:
            logger.warning("Fireflies summary fetch failed for %s", tid, exc_info=True)
        return None

    classified = await registry.classify(
        item, fetch=_fetch, fetch_summary=_fetch_summary, force_refetch=force_refetch
    )

    if classified.action == "create":
        outcome: Literal["fetch", "skip", "duplicate-skip"] = "fetch"
    elif classified.action == "revise":
        # R3 — no revision workflow: a content change on a known id is a
        # permanent skip, not an update.
        outcome = "duplicate-skip"
    else:
        outcome = "skip"

    return GatedMeeting(
        fireflies_id=fireflies_id,
        source_id=f"fireflies:{fireflies_id}",
        title=item.get("title", "Untitled Meeting"),
        meeting_date=item.get("date", ""),
        meeting_date_iso=item.get("date_iso"),
        participants=item.get("participants", []),
        duration_minutes=item.get("duration", 0.0),
        outcome=outcome,
        transcript_text=classified.fetched_text if outcome == "fetch" else None,
        summary_text=summary_cache.get(fireflies_id) if outcome == "fetch" else None,
        fingerprint=classified.fingerprint,
        summary_fingerprint=classified.summary_fingerprint,
    )
