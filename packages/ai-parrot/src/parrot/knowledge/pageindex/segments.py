"""Segments: the addressable substrate of imported PageIndex documents (FEAT-840)."""

from __future__ import annotations

import hashlib
import re
from typing import Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex import utils as _utils  # count_tokens via the module (test stub)

SegmentKind = Literal["heading", "paragraph", "list", "table", "code", "caption", "other"]

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CURSOR_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})@([0-9a-f]{16})#(\d+)\+(\d+)$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_KNOWN_EXT_RE = re.compile(r"\.(pdf|md|markdown|epub|txt|html?)$", re.IGNORECASE)
_RS = "\x1e"


class InjectionMark(BaseModel):
    """Why a segment was flagged as a possible prompt injection."""

    engine: str
    score: Optional[float] = None
    threats: list[str] = Field(default_factory=list)


class Segment(BaseModel):
    """One block of an imported document; ``text`` is verbatim and every offset indexes it."""

    seq: int
    kind: SegmentKind
    page: Optional[int] = None
    ordinal: int
    section: Optional[list[str]] = None
    level: Optional[int] = None
    text: str
    tokens: int
    sha16: str
    flags: list[str] = Field(default_factory=list)
    injection: Optional[InjectionMark] = None


class SourceInfo(BaseModel):
    """Where a document revision came from."""

    name: str
    kind: Literal["pdf", "markdown", "ebook", "legacy"]
    path: Optional[str] = None
    sha256: Optional[str] = None
    pages: Optional[int] = None


class DocumentRevision(BaseModel):
    """Immutable, content-hashed list of segments of one imported document."""

    doc_id: str
    revision: str
    source: SourceInfo
    segmenter: str = "v1"
    scored_by: Optional[str] = None
    created_at: str
    segments: list[Segment]


class SegmentAddress(BaseModel):
    """Stable address of one segment inside a document revision."""

    doc_id: str
    revision: str
    seq: int
    page: Optional[int] = None
    ordinal: int
    section: Optional[list[str]] = None

    @property
    def label(self) -> str:
        """Human label: ``p. 12 ¶3`` (paged) or ``Setup > Install ¶2`` (unpaged)."""
        para = f"¶{self.ordinal + 1}"
        if self.page is not None:
            return f"p. {self.page} {para}"
        if self.section:
            return f"{' > '.join(self.section)} {para}"
        return para

    @property
    def key(self) -> str:
        """Unique key ``<doc_id>@<revision>#<seq>``."""
        return f"{self.doc_id}@{self.revision}#{self.seq}"


class SegmentRead(BaseModel):
    """A (possibly partial) read of one segment; ``start``/``end`` are half-open offsets in its text."""

    address: SegmentAddress
    seq: int
    kind: SegmentKind
    text: str
    start: int
    end: int
    truncated: bool = False
    flags: list[str] = Field(default_factory=list)


class ReadResult(BaseModel):
    """Result of a read tool, pinned to one generation and one revision."""

    tree_name: str
    doc_id: str
    revision: str
    generation: Optional[int] = None
    segments: list[SegmentRead]
    truncated: bool = False
    next_cursor: Optional[str] = None
    framed: str


class RevisionMismatchError(ValueError):
    """A cursor or address names a different revision than the document being read."""


class RevisionUnavailableError(ValueError):
    """The named revision file no longer exists (swept after the grace period)."""


def _fence_marker(line: str) -> Optional[tuple[str, int]]:
    """``(char, run length)`` when ``line`` opens/closes a fenced code block (md_builder rule)."""
    match = _FENCE_RE.match(line)
    if not match:
        return None
    run = match.group(1)
    return run[0], len(run)


def _trim_blank_edges(lines: list[str]) -> str:
    """Join ``lines`` after removing leading/trailing blank lines (inner lines untouched)."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def split_blocks(markdown: str) -> list[tuple[SegmentKind, str, Optional[int]]]:
    """Split markdown into ``(kind, text, heading_level)`` blocks following spec §7 v1 rules."""
    lines = (markdown or "").split("\n")
    blocks: list[tuple[SegmentKind, str, Optional[int]]] = []
    para: list[str] = []

    def flush_para() -> None:
        text = _trim_blank_edges(para)
        para.clear()
        if text.strip():
            blocks.append(("paragraph", text, None))

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            flush_para()
            i += 1
            continue
        header = _HEADER_RE.match(line.strip())
        if header:
            flush_para()
            blocks.append(("heading", line.rstrip("\r"), len(header.group(1))))
            i += 1
            continue
        marker = _fence_marker(line)
        if marker is not None:
            flush_para()
            block = [line]
            i += 1
            while i < n:
                cur = lines[i]
                block.append(cur)
                i += 1
                closer = _fence_marker(cur)
                stripped = cur.strip()
                if (
                    closer is not None
                    and closer[0] == marker[0]
                    and closer[1] >= marker[1]
                    and stripped == closer[0] * len(stripped)
                ):
                    break
            blocks.append(("code", _trim_blank_edges(block), None))
            continue
        if line.lstrip().startswith("|"):
            flush_para()
            block = []
            while i < n and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            blocks.append(("table", _trim_blank_edges(block), None))
            continue
        if _LIST_RE.match(line):
            flush_para()
            block = [line]
            i += 1
            while i < n and lines[i].strip() and (
                _LIST_RE.match(lines[i]) or lines[i][:1] in (" ", "\t")
            ):
                block.append(lines[i])
                i += 1
            blocks.append(("list", _trim_blank_edges(block), None))
            continue
        if line.strip().startswith("!["):
            flush_para()
            blocks.append(("caption", line.rstrip("\r"), None))
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para()
    return blocks


def _make(seq: int, kind: SegmentKind, text: str, level: Optional[int], *, page: Optional[int],
          ordinal: int, section: Optional[list[str]]) -> Segment:
    return Segment(seq=seq, kind=kind, page=page, ordinal=ordinal, section=section, level=level, text=text,
                   tokens=_utils.count_tokens(text), sha16=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])


def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]:
    """Segments of a paged source in page order; ``seq`` is global, ``ordinal`` restarts per page."""
    segments: list[Segment] = []
    for page_no, markdown in pages:
        for ordinal, (kind, text, level) in enumerate(split_blocks(markdown)):
            segments.append(_make(len(segments), kind, text, level, page=page_no, ordinal=ordinal, section=None))
    return segments


def segment_text(text: str, section: list[str], *, seq_start: int = 0) -> list[Segment]:
    """Segments of one section of an unpaged source; ``ordinal`` restarts per section."""
    segments: list[Segment] = []
    for ordinal, (kind, body, level) in enumerate(split_blocks(text)):
        segments.append(_make(seq_start + ordinal, kind, body, level, page=None, ordinal=ordinal,
                              section=list(section)))
    return segments


def revision_id(segments: Sequence[Segment]) -> str:
    """sha256 over the segment texts joined by U+001E, first 16 hex chars."""
    return hashlib.sha256(_RS.join(s.text for s in segments).encode("utf-8")).hexdigest()[:16]


def derive_doc_id(name: str, *, taken: Mapping[str, Optional[str]], source_sha256: Optional[str]) -> str:
    """Slug of ``name``; suffixed with 6 hex only when ``taken[slug]`` holds a different source hash."""
    base = _KNOWN_EXT_RE.sub("", (name or "").strip())
    slug = _SLUG_STRIP_RE.sub("-", base.lower()).strip("-")[:48].strip("-") or "doc"
    if slug in taken and taken[slug] != source_sha256:
        digest = hashlib.sha256((source_sha256 or name or "").encode("utf-8")).hexdigest()[:6]
        slug = f"{slug}-{digest}"
    return slug


def parse_page_spec(spec: str, *, max_page: int) -> list[int]:
    """``"5-7,12"`` → ``[5, 6, 7, 12]`` (sorted, unique); ValueError on empty/malformed/out of range."""
    if spec is None or not str(spec).strip():
        raise ValueError("empty page spec")
    pages: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if match is None:
            raise ValueError(f"malformed page spec {part!r}")
        lo = int(match.group(1))
        hi = int(match.group(2)) if match.group(2) is not None else lo
        if lo < 1 or hi < lo or hi > max_page:
            raise ValueError(f"page spec {part!r} outside 1..{max_page}")
        pages.update(range(lo, hi + 1))
    return sorted(pages)


def format_cursor(doc_id: str, revision: str, seq: int, offset: int) -> str:
    """Inverse of :func:`parse_cursor`."""
    return f"{doc_id}@{revision}#{seq}+{offset}"


def parse_cursor(cursor: str) -> tuple[str, str, int, int]:
    """``(doc_id, revision, seq, offset)``; ValueError on a malformed cursor."""
    match = _CURSOR_RE.fullmatch(cursor or "")
    if match is None:
        raise ValueError(f"malformed cursor {cursor!r}")
    return match.group(1), match.group(2), int(match.group(3)), int(match.group(4))


# ---------------------------------------------------------------------------
# Ownership: spans, owned ranges, body views (TASK-5301)
# ---------------------------------------------------------------------------

_NUM_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s*")
_TRAILING_PUNCT = " \t.:;,-–—)"

Range = tuple[int, int]


def normalize_title(title: str) -> str:
    """Casefold, collapse whitespace, strip leading numbering and trailing punctuation."""
    text = " ".join((title or "").casefold().split())
    text = _NUM_PREFIX_RE.sub("", text)
    return text.rstrip(_TRAILING_PUNCT)


def _titles_match(a: str, b: str) -> bool:
    """Equality, or containment of the shorter in the longer when the shorter has >= 3 characters."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(short) >= 3 and short in long_


def _subtract(span: Range, holes: Sequence[Range]) -> list[Range]:
    """``span`` minus ``holes`` as sorted, maximal, non-empty half-open ranges."""
    start, end = span
    out: list[Range] = []
    cursor = start
    for h_start, h_end in sorted(holes):
        h_start, h_end = max(h_start, start), min(h_end, end)
        if h_end <= h_start:
            continue
        if h_start > cursor:
            out.append((cursor, h_start))
        cursor = max(cursor, h_end)
    if cursor < end:
        out.append((cursor, end))
    return out


def _heading_text(text: str) -> str:
    match = _HEADER_RE.match(text.strip())
    return match.group(2) if match else text


def _stamp(node: dict, revision: DocumentRevision) -> None:
    node["doc_id"] = revision.doc_id
    node["revision"] = revision.revision


def _clear_subtree(nodes: Sequence[dict], revision: DocumentRevision) -> None:
    for node in nodes:
        _stamp(node, revision)
        node["span"] = None
        node["owned"] = []
        _clear_subtree(node.get("nodes") or [], revision)


def attach_pdf_document(structure: list[dict], revision: DocumentRevision) -> None:
    """Set ``doc_id``, ``revision``, ``span`` and ``owned`` on every node of ``structure`` (PDF source).

    Span start is the first segment of ``start_index`` or the heading segment on that page matching the node
    title; span end is ``min(first segment after end_index, next sibling's start)`` widened to the children's
    ends. Top-level siblings additionally absorb the gap before the next one, the first starts at 0 and the last
    ends at ``len(segments)``, so the owned ranges partition the revision. A node whose pages hold no segment
    owns nothing.
    """
    from bisect import bisect_left, bisect_right

    segments = revision.segments
    total = len(segments)
    pages = [s.page if s.page is not None else 0 for s in segments]

    def start_of(node: dict) -> Optional[int]:
        page = node.get("start_index")
        if page is None:
            return None
        first = bisect_left(pages, page)
        last = bisect_right(pages, page)
        if first >= last:
            return None
        for seq in range(first, last):
            seg = segments[seq]
            if seg.kind == "heading" and _titles_match(_heading_text(seg.text), node.get("title", "")):
                return seq
        return first

    def attach_level(nodes: Sequence[dict], lo: int, hi: int, top: bool) -> None:
        starts: list[Optional[int]] = []
        previous = lo
        for node in nodes:
            s = start_of(node)
            if s is not None:
                s = min(max(s, previous, lo), hi)
                previous = s
            starts.append(s)
        valid = [i for i, s in enumerate(starts) if s is not None]
        if top and valid:
            starts[valid[0]] = lo
        for pos, idx in enumerate(valid):
            node = nodes[idx]
            _stamp(node, revision)
            s = starts[idx]
            nxt = starts[valid[pos + 1]] if pos + 1 < len(valid) else None
            bound = nxt if nxt is not None else hi
            end_idx = node.get("end_index")
            page_end = bisect_right(pages, end_idx) if end_idx is not None else bound
            e_page = bound if top else min(page_end, bound)
            children = node.get("nodes") or []
            attach_level(children, s, bound, False)
            child_spans = [tuple(c["span"]) for c in children if c.get("span")]
            e = max([e_page] + [c_end for _, c_end in child_spans])
            e = min(e, bound)
            if e <= s:
                node["span"] = None
                node["owned"] = []
                _clear_subtree(children, revision)
                continue
            node["span"] = [s, e]
            node["owned"] = [list(r) for r in _subtract((s, e), child_spans)]
        for idx, node in enumerate(nodes):
            if starts[idx] is None:
                _stamp(node, revision)
                node["span"] = None
                node["owned"] = []
                _clear_subtree(node.get("nodes") or [], revision)

    attach_level(structure, 0, total, True)


def attach_section_document(structure: list[dict], revision: DocumentRevision,
                            by_node: dict[int, tuple[int, int]]) -> None:
    """Same fields for an unpaged source; ``by_node`` maps ``id(node)`` to its own ``[start, end)``."""

    def visit(node: dict) -> Optional[Range]:
        _stamp(node, revision)
        own = by_node.get(id(node))
        spans: list[Range] = []
        owned: list[list[int]] = []
        if own is not None and own[1] > own[0]:
            spans.append((own[0], own[1]))
            owned.append([own[0], own[1]])
        for child in node.get("nodes") or []:
            child_span = visit(child)
            if child_span is not None:
                spans.append(child_span)
        node["owned"] = owned
        if not spans:
            node["span"] = None
            return None
        span = (min(s for s, _ in spans), max(e for _, e in spans))
        node["span"] = [span[0], span[1]]
        return span

    for root in structure:
        visit(root)


def render_body(revision: DocumentRevision, node: dict, children: Sequence[dict]) -> str:
    """Owned segments in document order with one gap marker per interrupting child."""
    segments = revision.segments
    events: list[tuple[int, int, str]] = []
    for rng in node.get("owned") or []:
        for seq in range(max(rng[0], 0), min(rng[1], len(segments))):
            events.append((seq, 1, segments[seq].text))
    for child in children:
        span = child.get("span")
        if span:
            events.append((span[0], 0, f"<!-- continues in: {child.get('title', '')} -->"))
    events.sort(key=lambda e: (e[0], e[1]))
    return "\n\n".join(text for _, _, text in events)


def validate_ownership(nodes: Sequence[dict], revision: DocumentRevision) -> list[str]:
    """Problems with the owned ranges of ``nodes``; empty when they partition ``[0, n)`` exactly once."""
    total = len(revision.segments)
    owner: list[Optional[str]] = [None] * total
    problems: list[str] = []
    overlaps = 0
    for node in nodes:
        label = str(node.get("node_id") or node.get("title") or id(node))
        for rng in node.get("owned") or []:
            start, end = rng[0], rng[1]
            if start < 0 or end > total or end <= start:
                problems.append(f"out of range [{start}, {end}) owned by {label}")
                continue
            for seq in range(start, end):
                if owner[seq] is None:
                    owner[seq] = label
                else:
                    overlaps += 1
                    if overlaps <= 20:
                        problems.append(f"overlap seq {seq} owned by {owner[seq]} and {label}")
    if overlaps > 20:
        problems.append(f"... {overlaps - 20} more overlapping segments")
    seq = 0
    while seq < total:
        if owner[seq] is None:
            begin = seq
            while seq < total and owner[seq] is None:
                seq += 1
            problems.append(f"gap [{begin}, {seq})")
        else:
            seq += 1
    return problems
