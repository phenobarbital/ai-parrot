"""Review Queue node (FEAT-481, spec Module 12, contract §26).

Deterministic — no LLM calls. Renders/appends/resolves
``Wiki/Review Queue.md`` entries. **``source-revision`` is deliberately
NOT in :data:`ALLOWED_REVIEW_TYPES`** — R3 removed the revision workflow
entirely; this module must never emit it.
"""

from __future__ import annotations

import re

#: §26 — allowed review types, MINUS `source-revision` (removed by R3 —
#: transcripts are immutable, there is no revision workflow).
ALLOWED_REVIEW_TYPES = frozenset(
    {
        "source-pairing",
        "classification",
        "new-project",
        "entity-ambiguity",
        "probable-duplicate",
        "contradiction",
        "locked-page-update",
        "unsupported-format",
        "missing-source",
        # Module 17 (failure quarantine / bounded reprocess):
        "failed-processing",  # LLM could not compile; quarantined, will auto-retry
        "reprocess-exhausted",  # auto-retry cap reached; needs a human
    }
)


def render_review_item(
    *,
    review_type: str,
    timestamp: str,
    title: str,
    source_id: str,
    related_pages: list[str],
    issue: str,
    evidence: str,
    recommended_action: str,
) -> str:
    """§26 — render one Review Queue entry, verbatim format.

    Args:
        review_type: Must be a member of :data:`ALLOWED_REVIEW_TYPES`.
        timestamp: ``YYYY-MM-DDTHH:mm:ss+00:00``.
        title: Short title.
        source_id: The related source id (``"fireflies:<id>"`` or a page
            path for a non-source-triggered item).
        related_pages: Wikilink targets.
        issue: Clear description.
        evidence: What was found.
        recommended_action: Specific next step.

    Returns:
        The rendered entry Markdown.

    Raises:
        ValueError: If ``review_type`` is not allowed (notably
            ``"source-revision"`` — R3).
    """
    if review_type not in ALLOWED_REVIEW_TYPES:
        raise ValueError(f"review_type {review_type!r} is not allowed (§26); allowed: {sorted(ALLOWED_REVIEW_TYPES)}")

    related = ", ".join(f"[[{p}]]" for p in related_pages) if related_pages else "None"
    return (
        f"## [{timestamp}] {review_type} | {title}\n\n"
        f"- Status: Open\n"
        f"- Source ID: `{source_id}`\n"
        f"- Related pages: {related}\n"
        f"- Issue: {issue}\n"
        f"- Evidence: {evidence}\n"
        f"- Recommended action: {recommended_action}\n"
    )


def append_review_item(existing_content: str, entry_markdown: str) -> str:
    """Append one rendered entry to ``Wiki/Review Queue.md``.

    Args:
        existing_content: The current file content.
        entry_markdown: One entry, from :func:`render_review_item`.

    Returns:
        The updated file content.
    """
    base = existing_content.rstrip("\n")
    return f"{base}\n\n{entry_markdown.rstrip()}\n" if base else f"{entry_markdown.rstrip()}\n"


def resolve_review_item(existing_content: str, title: str, *, resolution: str, resolved_at: str) -> str:
    """Mark a Review Queue entry ``Resolved``, preserving the original issue.

    Args:
        existing_content: The current ``Wiki/Review Queue.md`` content.
        title: The entry's title (matched against the ``| <title>``
            suffix of its heading).
        resolution: The resolution text to record.
        resolved_at: ``YYYY-MM-DDTHH:mm:ss+00:00``.

    Returns:
        The updated file content — the matching entry's ``Status`` line
        becomes ``Resolved`` and a ``Resolution``/``Resolved at`` pair is
        appended to it; every other entry (and the original issue text)
        is untouched.
    """
    pattern = re.compile(
        rf"(^## \[[^\]]+\] [a-z-]+ \| {re.escape(title)}\n\n(?:(?!\n## ).)*)", re.MULTILINE | re.DOTALL
    )

    def _resolve(match: re.Match[str]) -> str:
        block = match.group(1)
        block = re.sub(r"- Status: Open", "- Status: Resolved", block, count=1)
        block = block.rstrip("\n") + f"\n- Resolution: {resolution}\n- Resolved at: {resolved_at}\n"
        return block

    return pattern.sub(_resolve, existing_content)


def resolve_items_for_source(
    existing_content: str,
    source_id: str,
    *,
    resolution: str,
    resolved_at: str,
    only_types: frozenset[str] | None = None,
) -> str:
    """Mark every ``Open`` Review Queue entry for ``source_id`` as ``Resolved``.

    Used by Module 17 when a previously-quarantined meeting is successfully
    reprocessed — its ``failed-processing`` / ``reprocess-exhausted`` items are
    cleared. Matches entries by their ``- Source ID: `<source_id>``` line, only
    flipping ones still ``Open`` (idempotent); when ``only_types`` is given, only
    entries whose heading review-type is in that set are resolved.

    Args:
        existing_content: The current ``Wiki/Review Queue.md`` content.
        source_id: The source id to match (``"fireflies:<id>"``).
        resolution: The resolution text to record.
        resolved_at: ``YYYY-MM-DDTHH:mm:ss+00:00``.
        only_types: Optional review-type allowlist to restrict which entries clear.

    Returns:
        The updated content — matching open entries become ``Resolved`` with a
        ``Resolution``/``Resolved at`` pair; everything else is untouched.
    """
    block_re = re.compile(r"(^## \[[^\]]+\] ([a-z-]+) \| .*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    needle = f"- Source ID: `{source_id}`"

    def _maybe_resolve(match: re.Match[str]) -> str:
        block, review_type = match.group(1), match.group(2)
        if needle not in block or "- Status: Open" not in block:
            return block
        if only_types is not None and review_type not in only_types:
            return block
        block = re.sub(r"- Status: Open", "- Status: Resolved", block, count=1)
        return block.rstrip("\n") + f"\n- Resolution: {resolution}\n- Resolved at: {resolved_at}\n\n"

    return block_re.sub(_maybe_resolve, existing_content)
