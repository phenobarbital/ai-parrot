"""Configuration constants for the Obsidian / Fireflies agent family.

Every setting the :class:`~parrot.agents.obsidian.FirefliesObsidianAgent`
family reads from the environment is resolved here, once, at import time.
Two reasons for import-time resolution rather than lazy lookups:

- ``@schedule`` evaluates its arguments at *decoration* time, so the cron
  trigger values must already be plain module-level constants.
- A single module makes the deployment surface of these agents greppable —
  every knob is one ``rtk grep FIREFLIES_WIKI`` away.

All values go through ``navconfig.config``'s typed accessors
(``getint`` / ``getboolean`` / ``getlist``), which already handle the
missing-value fallback and the string→type coercion, so no hand-rolled
``_int_env``-style helpers are needed.

Note on ``getboolean``: navconfig raises ``ValueError`` on a value that is
not a recognised truth string. That is deliberate here — a typo in a
boolean flag is a deployment error worth failing loudly on, not something
to silently paper over with the default.
"""

from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from navconfig import config

logger = logging.getLogger(__name__)

__all__ = (
    "schedule_tzinfo",
    "FIREFLIES_WIKI_TZ",
    "FIREFLIES_WIKI_SYNC_HOUR",
    "FIREFLIES_WIKI_SYNC_MINUTE",
    "FIREFLIES_WIKI_DIGEST_HOUR",
    "FIREFLIES_WIKI_DIGEST_MINUTE",
    "FIREFLIES_WIKI_WEEKLY_DAY",
    "FIREFLIES_WIKI_WEEKLY_HOUR",
    "FIREFLIES_WIKI_WEEKLY_MINUTE",
    "FIREFLIES_WIKI_DEFAULT_LLM",
    "FIREFLIES_WIKI_LLM",
    "WIKI_MODEL",
    "FIREFLIES_WIKI_NAME",
    "FIREFLIES_WIKI_STORAGE_DIR",
    "FIREFLIES_WIKI_EXTRACT_ENTITIES",
    "FIREFLIES_WIKI_DAILY_RECIPIENTS",
    "FIREFLIES_WIKI_WEEKLY_RECIPIENTS",
    "FIREFLIES_WIKI_SYNC_LIMIT",
    "FIREFLIES_WIKI_ANALYSIS_LIMIT",
    "FIREFLIES_WIKI_DAILY_WINDOW_DAYS",
    "FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS",
    "FIREFLIES_REGISTRY_DIR",
    "FIREFLIES_SYNC_OVERLAP_DAYS",
    "FIREFLIES_RECHECK_DAYS",
    "AUDIO_NOTES_WIKI_NAME",
    "AUDIO_NOTES_WIKI_STORAGE_DIR",
    "AUDIO_NOTES_FOLDER",
)


def _recipients(key: str) -> List[str]:
    """Read a comma-separated recipient list, tolerating padding whitespace.

    ``config.getlist`` splits on ``","`` but does not strip the parts, so
    ``"a@x.com, b@y.com"`` would otherwise yield a second address with a
    leading space — which most SMTP providers reject.

    Args:
        key: navconfig / environment variable name.

    Returns:
        Stripped, non-empty entries (empty list when the key is unset).
    """
    return [item.strip() for item in config.getlist(key) if item.strip()]


# ---------------------------------------------------------------------------
# Schedule triggers
# ---------------------------------------------------------------------------

#: Timezone applied to all of the family's cron triggers. The digest windows
#: are computed in this same zone (see ``schedule_tzinfo``) — computing
#: "today" in UTC while the job fires at 08:00 Asia/Tokyo would silently
#: select the previous day's meetings.
FIREFLIES_WIKI_TZ: str = config.get("FIREFLIES_WIKI_TZ", fallback="UTC")


def schedule_tzinfo() -> timezone | ZoneInfo:
    """Resolve :data:`FIREFLIES_WIKI_TZ` to a tzinfo, falling back to UTC.

    The digest windows must be computed in the SAME timezone the cron
    triggers fire in. Computing "today" in UTC while the job fires at
    08:00 Asia/Tokyo would select the previous day's meetings — the
    window would be silently shifted by one day.

    Returns:
        A ``ZoneInfo`` for :data:`FIREFLIES_WIKI_TZ`, or ``timezone.utc``
        when the name is unknown (missing tzdata, typo).
    """
    try:
        return ZoneInfo(FIREFLIES_WIKI_TZ)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning(
            "FIREFLIES_WIKI_TZ=%r is not a known timezone — using UTC.",
            FIREFLIES_WIKI_TZ,
        )
        return timezone.utc

#: Daily sync (Fireflies → Obsidian → wiki).
FIREFLIES_WIKI_SYNC_HOUR: int = config.getint("FIREFLIES_WIKI_SYNC_HOUR", fallback=7)
FIREFLIES_WIKI_SYNC_MINUTE: int = config.getint("FIREFLIES_WIKI_SYNC_MINUTE", fallback=0)

#: Daily digest email.
FIREFLIES_WIKI_DIGEST_HOUR: int = config.getint("FIREFLIES_WIKI_DIGEST_HOUR", fallback=8)
FIREFLIES_WIKI_DIGEST_MINUTE: int = config.getint("FIREFLIES_WIKI_DIGEST_MINUTE", fallback=0)

#: Weekly insights email.
FIREFLIES_WIKI_WEEKLY_DAY: str = config.get("FIREFLIES_WIKI_WEEKLY_DAY", fallback="mon")
FIREFLIES_WIKI_WEEKLY_HOUR: int = config.getint("FIREFLIES_WIKI_WEEKLY_HOUR", fallback=9)
FIREFLIES_WIKI_WEEKLY_MINUTE: int = config.getint("FIREFLIES_WIKI_WEEKLY_MINUTE", fallback=0)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

#: Claude Haiku 4.5 — cheap and fast, ample 200K context for a week of
#: meeting analyses. Resolved through LLMFactory ("anthropic" →
#: AnthropicClient), never the Anthropic SDK directly.
FIREFLIES_WIKI_DEFAULT_LLM: str = "anthropic:claude-haiku-4-5"
FIREFLIES_WIKI_LLM: str = config.get("FIREFLIES_WIKI_LLM", fallback=FIREFLIES_WIKI_DEFAULT_LLM)

#: Authoring model for the PageIndex plane — the same knob ``wikitoolkit
#: ingest`` uses. Falls back to the agent's own LLM so a deployment that
#: configures only ``FIREFLIES_WIKI_LLM`` still gets an authoring plane
#: instead of degrading to retrieval-only.
#:
#: ``or`` rather than ``fallback=``: navconfig honours a key that is *set
#: but empty* (``WIKI_MODEL=``) and hands back ``""``, which would reach
#: ``LLMFactory.parse_llm_string`` as an unusable model spec. An empty
#: value means "unset" for this knob.
WIKI_MODEL: str = config.get("WIKI_MODEL") or FIREFLIES_WIKI_LLM


# ---------------------------------------------------------------------------
# Meetings wiki plane
# ---------------------------------------------------------------------------

FIREFLIES_WIKI_NAME: str = config.get("FIREFLIES_WIKI_NAME", fallback="meetings")
FIREFLIES_WIKI_STORAGE_DIR: str = config.get(
    "FIREFLIES_WIKI_STORAGE_DIR",
    fallback=str(Path.home() / ".parrot" / "wikis" / "meetings"),
)
FIREFLIES_WIKI_EXTRACT_ENTITIES: bool = config.getboolean(
    "FIREFLIES_WIKI_EXTRACT_ENTITIES",
    fallback=False,
)


# ---------------------------------------------------------------------------
# Meeting registry (FEAT-472) — id-keyed dedup for the Fireflies sync
# ---------------------------------------------------------------------------

#: Directory whose ``wiki.db`` backs the `MeetingRegistry` facade. Defaults
#: to the same storage dir as the meetings wiki plane so the parent agent's
#: standalone registry and the wiki toolkit's manager share one file
#: (spec §2 G5) once the wiki toolkit opens on the same path.
FIREFLIES_REGISTRY_DIR: str = config.get(
    "FIREFLIES_REGISTRY_DIR",
    fallback=FIREFLIES_WIKI_STORAGE_DIR,
)

#: Days subtracted from the registry's `max(synced_at)` to compute the
#: sync window's `from_date` (spec §2 G9). Default 2 — the user observes
#: no Fireflies changes later than ~2 days after a meeting.
FIREFLIES_SYNC_OVERLAP_DAYS: int = config.getint("FIREFLIES_SYNC_OVERLAP_DAYS", fallback=2)

#: A row younger than this many days (by `synced_at`) is eligible for the
#: classify() cheap-skip path (no transcript fetch) when the listing's
#: title/date/duration are unchanged (spec §2 G9). Default 7 — a generous
#: ceiling on top of the sync overlap.
FIREFLIES_RECHECK_DAYS: int = config.getint("FIREFLIES_RECHECK_DAYS", fallback=7)


# ---------------------------------------------------------------------------
# Audio-notes wiki plane (FEAT-452)
#
# Deliberately a SEPARATE plane from the meetings wiki so personal captures
# don't dilute meeting retrieval; see the spec §2 "Two separate wiki toolkit
# instances".
# ---------------------------------------------------------------------------

AUDIO_NOTES_WIKI_NAME: str = config.get("AUDIO_NOTES_WIKI_NAME", fallback="notes")
AUDIO_NOTES_WIKI_STORAGE_DIR: str = config.get(
    "AUDIO_NOTES_WIKI_STORAGE_DIR",
    fallback=str(Path.home() / ".parrot" / "wikis" / "notes"),
)
AUDIO_NOTES_FOLDER: str = config.get("AUDIO_NOTES_FOLDER", fallback="audio-notes")


# ---------------------------------------------------------------------------
# Digest recipients and run bounds
# ---------------------------------------------------------------------------

FIREFLIES_WIKI_DAILY_RECIPIENTS: List[str] = _recipients("FIREFLIES_WIKI_DAILY_RECIPIENTS")
FIREFLIES_WIKI_WEEKLY_RECIPIENTS: List[str] = _recipients("FIREFLIES_WIKI_WEEKLY_RECIPIENTS")

FIREFLIES_WIKI_SYNC_LIMIT: int = config.getint("FIREFLIES_WIKI_SYNC_LIMIT", fallback=20)
FIREFLIES_WIKI_ANALYSIS_LIMIT: int = config.getint("FIREFLIES_WIKI_ANALYSIS_LIMIT", fallback=20)
FIREFLIES_WIKI_DAILY_WINDOW_DAYS: int = config.getint("FIREFLIES_WIKI_DAILY_WINDOW_DAYS", fallback=1)
FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS: int = config.getint("FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS", fallback=7)
