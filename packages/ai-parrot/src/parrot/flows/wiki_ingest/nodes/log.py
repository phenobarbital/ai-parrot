"""Append-only operation log node (FEAT-481, spec Module 12, contract §33).

Deterministic — no LLM calls. ``Wiki/log.md`` is append-only: entries are
never rewritten or reordered. **``revision-detected`` is deliberately NOT
in :data:`ALLOWED_LOG_OPS`** — R3 removed the revision workflow entirely.
"""

from __future__ import annotations

#: §33 — allowed log operations, MINUS `revision-detected` (removed by
#: R3 — there is no revision workflow).
ALLOWED_LOG_OPS = frozenset(
    {
        "initialize",
        "ingest",
        "duplicate-skip",
        "query-save",
        "health",
        "lint",
        "archive",
        "graph",
    }
)


def render_ingest_log_entry(
    *,
    timestamp: str,
    meeting_title: str,
    source_id: str,
    source_page: str,
    projects: list[str],
    processing_mode: str,
    created: list[str] | None = None,
    updated: list[str] | None = None,
    contradictions: list[str] | None = None,
    review_items: list[str] | None = None,
    validation: str = "Passed",
) -> str:
    """§33 — render one ``ingest`` log entry, verbatim format.

    Never called for an operation whose §34 validation failed (§33: "Do
    not add a successful ``ingest`` log entry until post-ingest
    validation succeeds") — the orchestrator (spec Module 6) is
    responsible for only calling this after validation passes.

    Args:
        timestamp: ``YYYY-MM-DDTHH:mm:ss+00:00``.
        meeting_title: The meeting's title.
        source_id: ``"fireflies:<id>"``.
        source_page: Wikilink target of the canonical meeting source page.
        projects: Wikilink targets of the affected project(s).
        processing_mode: ``"summary-only"`` or ``"summary-and-transcript"``.
        created: Paths created this operation.
        updated: Paths updated this operation.
        contradictions: Contradiction page links, if any.
        review_items: Review Queue links, if any.
        validation: ``"Passed"``, ``"Passed with warnings"``, or
            ``"Failed"``.

    Returns:
        The rendered entry Markdown.
    """
    return render_log_entry(
        op="ingest",
        timestamp=timestamp,
        title=meeting_title,
        fields={
            "Source ID": f"`{source_id}`",
            "Source page": f"[[{source_page}]]",
            "Projects": ", ".join(f"[[{p}]]" for p in projects) if projects else "None",
            "Processing mode": processing_mode,
            "Created": ", ".join(created) if created else "None",
            "Updated": ", ".join(updated) if updated else "None",
            "Contradictions": ", ".join(f"[[{c}]]" for c in contradictions) if contradictions else "None",
            "Review items": ", ".join(f"[[{r}]]" for r in review_items) if review_items else "None",
            "Validation": validation,
        },
    )


def render_log_entry(*, op: str, timestamp: str, title: str, fields: dict[str, str]) -> str:
    """§33 — render one generic log entry, verbatim heading format.

    Args:
        op: Must be a member of :data:`ALLOWED_LOG_OPS`.
        timestamp: ``YYYY-MM-DDTHH:mm:ss+00:00``.
        title: The entry's title (meeting title, or a short operation
            description for non-ingest ops).
        fields: Ordered ``label: value`` bullet lines.

    Returns:
        The rendered entry Markdown.

    Raises:
        ValueError: If ``op`` is not allowed (notably
            ``"revision-detected"`` — R3).
    """
    if op not in ALLOWED_LOG_OPS:
        raise ValueError(f"log operation {op!r} is not allowed (§33); allowed: {sorted(ALLOWED_LOG_OPS)}")

    lines = "\n".join(f"- {label}: {value}" for label, value in fields.items())
    return f"## [{timestamp}] {op} | {title}\n\n{lines}\n"


def append_log_entry(existing_content: str, entry_markdown: str) -> str:
    """Append one entry to ``Wiki/log.md`` — never rewrites/reorders (§33).

    Args:
        existing_content: The current ``Wiki/log.md`` content.
        entry_markdown: One entry, from :func:`render_log_entry` /
            :func:`render_ingest_log_entry`.

    Returns:
        The updated file content, with the new entry appended after
        every existing entry.
    """
    base = existing_content.rstrip("\n")
    return f"{base}\n\n{entry_markdown.rstrip()}\n" if base else f"{entry_markdown.rstrip()}\n"
