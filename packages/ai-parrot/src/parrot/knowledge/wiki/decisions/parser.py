"""Bounded ADR Markdown subset parser (FEAT-578 Module 3).

Accepts UTF-8 Markdown with ATX headings and an optional flat frontmatter
block carrying only ``id``, ``title``, ``status`` and ``supersedes``. Nested
YAML is unsupported by design — the parser reads scalars with a regex and
never evaluates the document (spec §2).

Every returned record is ``origin='documented'``. Inferred candidates are
produced elsewhere (``decisions/generation.py``).
"""

from __future__ import annotations

import hashlib
import re

from parrot.knowledge.wiki.decisions.codec import documented_decision_id, normalize_rel_path
from parrot.knowledge.wiki.decisions.models import (
    ADR_PARSE_FAILED,
    ADR_STATUS_CONFLICT,
    DecisionDiagnostic,
    DecisionLink,
    DecisionRecord,
    EvidenceRef,
)

#: The only frontmatter keys read. Anything else is ignored, not an error.
FRONTMATTER_KEYS = ("id", "title", "status", "supersedes")

#: Section names recognised, matched case-insensitively.
SECTION_NAMES = ("context", "decision", "consequences", "status")

#: Lifecycle values recognised; anything else stays ``unknown`` with the raw
#: text preserved in ``source_status_raw``.
KNOWN_STATUSES = ("accepted", "proposed", "rejected", "deprecated", "superseded")

#: ``ADR-42`` / ``ADR/042`` / ``ADR 42`` -> canonical ``ADR-42``.
#: The separator class and digit bound are copied VERBATIM from GraphIndex's
#: citation regex (verified: graphindex/extractors/code.py:35,
#: ``\b(ADR|RFC)[\s\-/]?(\d{1,5})\b``) so the two planes agree on what is a
#: reference; only the RFC alternative is dropped, and leading zeros are
#: stripped here to form the canonical alias. Do NOT widen the separator
#: class (no ``_``) — that would make the wiki see references GraphIndex does
#: not, which spec §2 forbids ("consistently with GraphIndex").
ADR_REFERENCE_RE = re.compile(r"\bADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)

#: A leading ``0042-`` style filename prefix.
FILENAME_ID_RE = re.compile(r"^0*(\d+)[-_]")

_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_FRONTMATTER_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


def normalize_adr_alias(text: str) -> str | None:
    """Return the canonical ``ADR-<n>`` alias in ``text``, or ``None``."""
    match = ADR_REFERENCE_RE.search(text)
    return f"ADR-{int(match.group(1))}" if match else None


def split_sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map lowercase section name -> ``(start_line, end_line)``, 1-based inclusive.

    Headings inside fenced code blocks are ignored (spec §2), so a fenced
    example ADR cannot fabricate sections in the document that quotes it.
    """
    # Collect (level, name_or_None, line_no) for every heading line outside a
    # fence. `name` is the lowercase heading text when it matches one of the
    # recognised SECTION_NAMES, else None (still needed to bound the span of
    # the previous recognised heading).
    headings: list[tuple[int, str | None, int]] = []
    in_fence = False
    fence_marker: str | None = None
    for idx, raw_line in enumerate(lines, start=1):
        fence_match = _FENCE_RE.match(raw_line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            continue
        if in_fence:
            continue
        atx_match = _ATX_RE.match(raw_line)
        if not atx_match:
            continue
        level = len(atx_match.group(1))
        heading_text = atx_match.group(2).strip().lower()
        name = heading_text if heading_text in SECTION_NAMES else None
        headings.append((level, name, idx))

    sections: dict[str, tuple[int, int]] = {}
    total_lines = len(lines)
    for pos, (level, name, line_no) in enumerate(headings):
        if name is None:
            continue
        end_line = total_lines
        for next_level, _, next_line_no in headings[pos + 1 :]:
            # Any subsequent heading of the same or higher level (i.e. a
            # lower or equal heading number) closes this section's span.
            if next_level <= level:
                end_line = next_line_no - 1
                break
        start_line = line_no + 1
        if start_line > end_line:
            # Empty section body — collapse to an empty span right after
            # the heading rather than bleeding into the next section.
            end_line = start_line - 1
        sections[name] = (start_line, end_line)
    return sections


def parse_frontmatter(lines: list[str]) -> tuple[dict[str, str], int, list[DecisionDiagnostic]]:
    """Read the flat ``---`` block at the top of the file.

    Returns:
        ``(fields, body_start_index, diagnostics)``. Only
        :data:`FRONTMATTER_KEYS` are kept. A block that never closes, or a
        line that is not a flat ``key: value`` scalar, yields an
        ``ADR_PARSE_FAILED`` diagnostic and is skipped — it is never fatal,
        because an ADR with a bad header is still an ADR.
    """
    diagnostics: list[DecisionDiagnostic] = []
    if not lines or lines[0].strip() != "---":
        return {}, 0, diagnostics

    fields: dict[str, str] = {}
    closing_index: int | None = None
    malformed = False
    for idx in range(1, len(lines)):
        line = lines[idx]
        if line.strip() == "---":
            closing_index = idx
            break
        if not line.strip():
            continue
        # A nested structure shows up as an indented continuation line —
        # not a flat scalar. Flag and skip rather than fail the whole file.
        if line[:1] in (" ", "\t"):
            malformed = True
            continue
        scalar_match = _FRONTMATTER_SCALAR_RE.match(line)
        if not scalar_match:
            malformed = True
            continue
        key = scalar_match.group(1).lower()
        value = scalar_match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key in FRONTMATTER_KEYS:
            fields[key] = value

    if closing_index is None:
        diagnostics.append(
            DecisionDiagnostic(code=ADR_PARSE_FAILED, message="frontmatter block never closed with '---'")
        )
        return {}, 0, diagnostics

    if malformed:
        diagnostics.append(
            DecisionDiagnostic(code=ADR_PARSE_FAILED, message="frontmatter contained a non-flat-scalar line")
        )

    return fields, closing_index + 1, diagnostics


def resolve_status(frontmatter_status: str, section_status: str) -> tuple[str, str, list[DecisionDiagnostic]]:
    """Resolve the declared lifecycle status.

    Returns:
        ``(status, status_raw, diagnostics)``. Frontmatter is consulted
        first, then the ``Status`` section. When both are present and
        disagree, the result is ``('unknown', <raw>, [ADR_STATUS_CONFLICT])``
        — a conflict is never silently resolved by precedence (spec §2).
        Unrecognised text yields ``'unknown'`` with the original preserved.
    """

    def _normalize(raw: str) -> str | None:
        raw = raw.strip()
        if not raw:
            return None
        first_word = raw.split()[0].strip(".,;:-—").lower()
        return first_word if first_word in KNOWN_STATUSES else "unknown"

    fm_raw = frontmatter_status.strip()
    section_raw = section_status.strip()
    fm_norm = _normalize(fm_raw) if fm_raw else None
    section_norm = _normalize(section_raw) if section_raw else None

    if fm_norm is not None and section_norm is not None:
        if fm_norm != section_norm:
            raw = fm_raw or section_raw
            return "unknown", raw, [DecisionDiagnostic(code=ADR_STATUS_CONFLICT, message="conflicting status")]
        return fm_norm, fm_raw, []

    if fm_norm is not None:
        return fm_norm, fm_raw, []

    if section_norm is not None:
        return section_norm, section_raw, []

    return "unknown", "", []


def _sha1(text: str) -> str:
    """SHA-1 hex digest of ``text`` as UTF-8 — identity, not authenticity."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324


def _extract_h1(lines: list[str]) -> str | None:
    """Return the first top-level ATX heading's text, or ``None``."""
    in_fence = False
    fence_marker: str | None = None
    for line in lines:
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            continue
        if in_fence:
            continue
        atx_match = _ATX_RE.match(line)
        if atx_match and len(atx_match.group(1)) == 1:
            return atx_match.group(2).strip()
    return None


def parse_adr(rel_path: str, text: str) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]:
    """Parse one ADR document.

    Args:
        rel_path: Repository-relative POSIX path, used for identity.
        text: The COMPLETE file text. Callers must not pass a truncated
            page body — AC1 requires a ``Decision`` past the ordinary
            16000-character body head to be extracted with correct spans.

    Returns:
        ``(record, diagnostics)``. ``record`` is ``None`` when the document
        has no ``Decision`` section: that is an ordinary document plus a
        diagnostic, never a fabricated ADR (spec §2).
    """
    diagnostics: list[DecisionDiagnostic] = []
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    # splitlines(), not split("\n"): a file ending in a newline would otherwise
    # gain a phantom trailing line, pushing the LAST section's end_line one past
    # the file and hashing a span that `evidence._read_span_sync` (which reads
    # with splitlines()) can never reproduce -- freshness then reported `stale`
    # for every untouched final section.
    lines = normalized_text.splitlines()

    fields, body_start, fm_diagnostics = parse_frontmatter(lines)
    diagnostics.extend(fm_diagnostics)

    body_lines = lines[body_start:]
    sections = split_sections(body_lines)
    # Shift spans from body-relative to whole-file line numbers.
    sections = {name: (start + body_start, end + body_start) for name, (start, end) in sections.items()}

    if "decision" not in sections:
        diagnostics.append(
            DecisionDiagnostic(code=ADR_PARSE_FAILED, message="no 'Decision' section found", path=rel_path)
        )
        return None, diagnostics

    def _section_text(name: str) -> str:
        if name not in sections:
            return ""
        start, end = sections[name]
        if end < start:
            return ""
        return "\n".join(lines[start - 1 : end]).strip()

    context_text = _section_text("context")
    decision_text = _section_text("decision")
    consequences_text = _section_text("consequences")
    status_section_text = _section_text("status")

    source_status, source_status_raw, status_diagnostics = resolve_status(fields.get("status", ""), status_section_text)
    diagnostics.extend(status_diagnostics)

    # Identity: frontmatter id -> H1 heading -> filename, in that order.
    fm_id = normalize_adr_alias(fields["id"]) if fields.get("id") else None
    h1_text = _extract_h1(lines)
    h1_id = normalize_adr_alias(h1_text) if h1_text else None
    filename = rel_path.rsplit("/", 1)[-1]
    filename_match = FILENAME_ID_RE.match(filename)
    filename_id = f"ADR-{int(filename_match.group(1))}" if filename_match else None

    candidate_ids = [candidate for candidate in (fm_id, h1_id, filename_id) if candidate is not None]
    external_id = candidate_ids[0] if candidate_ids else None
    distinct_ids = set(candidate_ids)
    if len(distinct_ids) > 1:
        diagnostics.append(
            DecisionDiagnostic(
                code=ADR_PARSE_FAILED,
                message=f"conflicting ADR identifiers: {sorted(distinct_ids)}",
                path=rel_path,
            )
        )

    title = fields.get("title") or h1_text or ""

    evidence: list[EvidenceRef] = []
    for name in SECTION_NAMES:
        if name not in sections:
            continue
        start, end = sections[name]
        if end < start:
            continue
        span_text = "\n".join(lines[start - 1 : end])
        evidence.append(
            EvidenceRef(
                page_id=documented_decision_id(rel_path),
                rel_path=normalize_rel_path(rel_path),
                start_line=start,
                end_line=end,
                source_sha1=_sha1(span_text),
                excerpt=span_text[:500],
                kind="adr",
            )
        )

    links = []
    supersedes_raw = fields.get("supersedes", "")
    if supersedes_raw:
        for token in re.split(r"[,\s]+", supersedes_raw.strip()):
            if not token:
                continue
            alias = normalize_adr_alias(token)
            if alias:
                links.append(alias)

    decision_links = [
        DecisionLink(target_id=alias, relation="supersedes", provenance="extracted", evidence_indexes=[])
        for alias in links
    ]

    record = DecisionRecord(
        decision_id=documented_decision_id(rel_path),
        title=title,
        context=context_text,
        decision=decision_text,
        consequences=consequences_text,
        source_status=source_status,
        source_status_raw=source_status_raw,
        origin="documented",
        source_path=normalize_rel_path(rel_path),
        external_id=external_id,
        evidence=evidence,
        links=decision_links,
    )
    return record, diagnostics
