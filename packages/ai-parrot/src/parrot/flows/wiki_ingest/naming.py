"""Obsidian-safe filename helpers (FEAT-481, spec Module 4, contract §8.2).

Every filename this subsystem writes goes through one of these helpers —
never ad-hoc string formatting — so the §8.2 rules (Title Case project
pages, canonical entity/concept names, ``YYYY-MM-DD.md`` daily notes, the
meeting-page pattern, and unsafe-punctuation sanitization) are enforced in
exactly one place.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from .models import UNSAFE_FILENAME_CHARS

#: §8.2 — collapse runs of whitespace produced by stripping unsafe chars.
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_filename(name: str) -> str:
    """Strip Obsidian-unsafe punctuation from a candidate filename.

    Removes ``/ \\ : * ? " < > |`` (contract §8.2) and collapses the
    whitespace left behind, without altering casing or word order — so
    alternate/former spellings still belong in ``aliases``, not here.

    Args:
        name: The candidate name (no extension).

    Returns:
        The sanitized name, stripped of unsafe punctuation and leading/
        trailing whitespace.
    """
    cleaned = "".join(ch for ch in name if ch not in UNSAFE_FILENAME_CHARS)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def title_case_name(name: str) -> str:
    """Human-readable Title Case with spaces (§8.2 — project folders/pages).

    Args:
        name: The raw candidate name.

    Returns:
        The sanitized name in Title Case.
    """
    sanitized = sanitize_filename(name)
    return " ".join(word[:1].upper() + word[1:] if word else word for word in sanitized.split(" "))


def daily_note_filename(day: date) -> str:
    """§10.6 / §8.2 — a daily note's filename: ``YYYY-MM-DD.md``.

    Args:
        day: The daily note's date.

    Returns:
        ``"YYYY-MM-DD.md"``.
    """
    return f"{day.isoformat()}.md"


def short_source_id(source_id: str, *, length: int = 8) -> str:
    """A short, filename-friendly suffix derived from a full ``source_id``.

    Args:
        source_id: The full ``"fireflies:<id>"`` identity (D4).
        length: Number of characters of the Fireflies id to keep
            (default 8 — enough to disambiguate within one meeting date
            without producing an unwieldy filename).

    Returns:
        The first ``length`` characters of the Fireflies id (the part
        after the ``"fireflies:"`` prefix), sanitized for filenames.
    """
    raw_id = source_id.split(":", 1)[1] if ":" in source_id else source_id
    return sanitize_filename(raw_id)[:length]


def meeting_source_filename(
    *,
    meeting_date_local: date,
    title: str,
    source_id: str,
) -> str:
    """§8.2 / §17 — the canonical meeting source page filename.

    ``YYYY-MM-DD - <Meeting Title> - <short-source-id>.md``, where the
    date is the meeting's date in its **original timezone** — the caller
    must pass a date already converted to that timezone; this helper
    never substitutes the ingestion date (§8.4).

    Args:
        meeting_date_local: The meeting's date in its original timezone.
        title: The meeting title.
        source_id: The full ``"fireflies:<id>"`` identity (D4).

    Returns:
        The sanitized filename, including the ``.md`` extension.
    """
    sanitized_title = sanitize_filename(title)
    suffix = short_source_id(source_id)
    return f"{meeting_date_local.isoformat()} - {sanitized_title} - {suffix}.md"


def now_iso(*, tz_offset: str = "+00:00") -> str:
    """§8.4 — an ISO-8601 timestamp with a preserved offset.

    Args:
        tz_offset: The offset to report (default UTC). Callers with a
            known original timezone should format it themselves and pass
            the already-offset-aware string instead of relying on this
            default.

    Returns:
        ``"YYYY-MM-DDTHH:mm:ss<tz_offset>"``.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S") + tz_offset
