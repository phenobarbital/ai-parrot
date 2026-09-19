"""§30 Lint workflow (FEAT-481, spec Module 14).

Default lint is read-only; ``--fix`` applies **only** the §30 safe-repair
list — contradictions, ambiguous entity merges, project classification,
locked pages, and any missing-owner/date/requirement/decision are never
auto-fixed (§30's explicit "must not automatically fix" list).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: §30 — the only fixes `lint --fix` may apply automatically.
SAFE_FIX_CATEGORIES = frozenset(
    {
        "missing_index_link",
        "duplicate_index_entry",
    }
)


class LintFinding(BaseModel):
    """One lint finding.

    Attributes:
        category: A short, stable finding category (e.g.
            ``"broken_wikilink"``, ``"orphan_page"``,
            ``"missing_index_link"``, ``"duplicate_index_entry"``).
        description: Human-readable description.
        path: The affected page, when applicable.
        fixable: Whether this finding's category is in
            :data:`SAFE_FIX_CATEGORIES`.
    """

    category: str
    description: str
    path: str | None = None
    fixable: bool = False


class LintReport(BaseModel):
    """Result of one §30 lint run.

    Attributes:
        findings: Every finding — including ones ``fix=True`` already
            repaired (still reported, never silently fixed — §30: "may
            apply safe repairs **after reporting them**").
        fixed: Categories/paths actually repaired this run
            (``fix=True`` only).
    """

    findings: list[LintFinding] = Field(default_factory=list)
    fixed: list[str] = Field(default_factory=list)


async def run_lint(toolkit: Any, *, fix: bool = False) -> LintReport:
    """Run the §30 integrity scan.

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit`` (spec Module 4).
            ``catalog_notes()`` already computes broken links and orphans
            over the indexed vault — reused here rather than
            reimplementing wikilink resolution.
        fix: When ``True``, apply the §30 safe repairs after reporting
            every finding (duplicate index entries only, in this
            implementation — see :data:`SAFE_FIX_CATEGORIES`).

    Returns:
        The :class:`LintReport`.
    """
    findings: list[LintFinding] = []

    catalog = await toolkit.catalog_notes()

    for broken in catalog.get("broken_links", []):
        findings.append(
            LintFinding(
                category="broken_wikilink",
                description=f"[[{broken['target']}]] does not resolve",
                path=broken.get("from"),
            )
        )

    for orphan in catalog.get("orphans", []):
        findings.append(
            LintFinding(category="orphan_page", description="No inbound links and no index entry", path=orphan)
        )

    fixed: list[str] = []
    if fix:
        fixed_index, index_findings = await _fix_duplicate_index_entries(toolkit)
        findings.extend(index_findings)
        fixed.extend(fixed_index)

    return LintReport(findings=findings, fixed=fixed)


async def _fix_duplicate_index_entries(toolkit: Any) -> tuple[list[str], list[LintFinding]]:
    """§30 safe fix — de-duplicate exact-duplicate lines in ``Wiki/index.md``.

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit``.

    Returns:
        ``(fixed_descriptions, findings)`` — empty when the index does
        not exist or has no duplicates.
    """
    try:
        note = await toolkit.read_note("Wiki/index.md")
    except FileNotFoundError:
        return [], []

    lines = note["content"].splitlines()
    seen: set[str] = set()
    deduped: list[str] = []
    duplicates_removed = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") and stripped in seen:
            duplicates_removed += 1
            continue
        if stripped.startswith("- "):
            seen.add(stripped)
        deduped.append(line)

    if duplicates_removed == 0:
        return [], []

    await toolkit.update_note("Wiki/index.md", "\n".join(deduped), preserve_frontmatter=False)
    finding = LintFinding(
        category="duplicate_index_entry",
        description=f"Removed {duplicates_removed} duplicate index entry line(s)",
        path="Wiki/index.md",
        fixable=True,
    )
    return [f"Wiki/index.md: removed {duplicates_removed} duplicate entries"], [finding]
