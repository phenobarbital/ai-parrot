"""Obsidian vault scanning for the wikitoolkit build pipeline (Phase E).

Turns an Obsidian vault directory into a ready-to-use LLM Wiki knowledge
base with **zero LLM calls and zero embeddings**: pages land in the
existing SQLite retrieval plane (FTS5 keyword search), the hand-curated
``[[wikilink]]`` graph lands in the ``edges`` table (backlinks come free
from directional edge queries), and ``#tags`` become first-class tag
pages.

The scanner mirrors :mod:`parrot.knowledge.wiki.repo_scan`'s conventions
exactly — same :class:`RepoScan` result shape, same ``file:<relpath>``
concept ids, same ``contains`` directory pages — so the whole build
pipeline (incremental staleness, pruning, OKF export, graph.html) works
unchanged; ``wikitoolkit build`` auto-detects vaults and routes here.

Edge relations produced (open-string ``rel`` column):

* resolved ``[[wikilink]]`` → ``references``
* resolved ``![[embed]]`` → ``embeds``
* note → tag page → ``tagged``
* folder containment → ``contains`` (via ``build_dir_pages``)

Unresolved wikilinks are dropped from the edge list (same discipline as
``build_import_edges``) but counted in the scan's ``skipped`` telemetry
via the returned :class:`VaultScanStats`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from parrot.interfaces.obsidian.index import VaultIndex
from parrot.interfaces.obsidian.models import ObsidianNote
from parrot.interfaces.obsidian.parser import ObsidianNoteParser

from .repo_scan import (
    DEFAULT_BODY_MAX_CHARS,
    DEFAULT_MAX_FILE_BYTES,
    FileSlice,
    RepoScan,
    build_dir_pages,
    file_concept_id,
)
from .store import WikiPageRecord, estimate_tokens

logger = logging.getLogger(__name__)

#: Directories never scanned inside a vault.
VAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {".obsidian", ".trash", ".git", ".hg", ".svn"}
)


def is_obsidian_vault(root: Path) -> bool:
    """Whether a directory is an Obsidian vault (has an ``.obsidian/`` dir).

    Args:
        root: Directory to test.

    Returns:
        True when ``root/.obsidian`` exists as a directory.
    """
    return (Path(root) / ".obsidian").is_dir()


def tag_concept_id(tag: str) -> str:
    """Stable concept id for a tag page."""
    return f"tag:{tag}"


@dataclass
class VaultScanStats:
    """Vault-specific telemetry for the build summary line."""

    notes: int = 0
    tags: int = 0
    wikilink_edges: int = 0
    embed_edges: int = 0
    unresolved_links: list[tuple[str, str]] = field(default_factory=list)


def _note_summary(note: ObsidianNote) -> str:
    """Summary for a note page: frontmatter summary > first body line."""
    for key in ("summary", "description"):
        value = note.frontmatter.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for line in note.content.splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            return text[:300]
    return note.title


def _note_body(note: ObsidianNote, body_max_chars: int) -> str:
    """Page body: deterministic header block + the note's markdown.

    Tags and aliases are rendered into the header so FTS5 finds notes by
    tag or alias without any schema change.
    """
    header: list[str] = [f"# {note.title}"]
    if note.tags:
        header.append(f"Tags: {' '.join(sorted(f'#{t}' for t in note.tags))}")
    if note.aliases:
        header.append(f"Aliases: {', '.join(note.aliases)}")
    body = "\n".join(header) + "\n\n" + note.content
    return body[:body_max_chars]


def scan_vault(
    root: Path,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> tuple[RepoScan, VaultScanStats]:
    """Scan an Obsidian vault into wiki page records and edges.

    Args:
        root: Vault root directory.
        body_max_chars: Cap on stored page body length.
        max_file_bytes: Skip notes larger than this.

    Returns:
        ``(scan, stats)`` — a :class:`RepoScan` shaped exactly like
        ``scan_repository``'s result (so the build pipeline consumes it
        unchanged) plus vault-specific :class:`VaultScanStats`.
    """
    root = Path(root).resolve()
    parser = ObsidianNoteParser()
    scan = RepoScan(root=root)
    stats = VaultScanStats()
    notes: list[ObsidianNote] = []

    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        parts = PurePosixPath(rel).parts
        if any(part in VAULT_EXCLUDE_DIRS for part in parts):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                scan.skipped.append(rel)
                continue
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Skipping %s: %s", rel, exc)
            scan.skipped.append(rel)
            continue
        notes.append(parser.parse(raw, rel))

    index = VaultIndex.build(notes)

    # --- Note pages -----------------------------------------------------
    for note in notes:
        rel = note.path.as_posix()
        body = _note_body(note, body_max_chars)
        record = WikiPageRecord(
            concept_id=file_concept_id(rel),
            title=note.title,
            category="document",
            summary=_note_summary(note),
            body=body,
            token_count=estimate_tokens(body),
        )
        scan.files.append(FileSlice(rel_path=rel, record=record))
        stats.notes += 1

    # --- Wikilink / embed edges ----------------------------------------
    seen_edges: set[tuple[str, str, str]] = set()
    for note in notes:
        rel = note.path.as_posix()
        norm = rel[:-3] if rel.lower().endswith(".md") else rel
        source_cid = file_concept_id(rel)
        for link in note.links:
            resolved = index.resolve(link.target, from_path=norm)
            if resolved is None:
                stats.unresolved_links.append((rel, link.target))
                continue
            target_cid = file_concept_id(f"{resolved}.md")
            relation = "embeds" if link.is_embed else "references"
            edge = (source_cid, target_cid, relation)
            if edge not in seen_edges and source_cid != target_cid:
                seen_edges.add(edge)
                scan.import_edges.append(edge)
                if link.is_embed:
                    stats.embed_edges += 1
                else:
                    stats.wikilink_edges += 1

    # --- Directory pages (same convention as repo scans) ----------------
    scan.dir_records, scan.dir_edges = build_dir_pages(scan.files)

    # --- Tag pages + tagged edges ---------------------------------------
    for tag, count in index.tags().items():
        note_paths = index.notes_by_tag(tag)
        lines = [f"- [file:{p}.md]" for p in note_paths]
        body = (
            f"# Tag #{tag}\n\n{count} tagged note(s):\n\n" + "\n".join(lines)
        )
        scan.dir_records.append(
            WikiPageRecord(
                concept_id=tag_concept_id(tag),
                title=f"#{tag}",
                category="tag",
                summary=f"Obsidian tag #{tag} ({count} notes)",
                body=body,
                token_count=estimate_tokens(body),
            )
        )
        for note_path in note_paths:
            scan.dir_edges.append(
                (file_concept_id(f"{note_path}.md"), tag_concept_id(tag), "tagged")
            )
        stats.tags += 1

    logger.info(
        "Scanned vault %s: %d notes, %d tags, %d wikilink edges, "
        "%d embed edges, %d unresolved links, %d skipped",
        root, stats.notes, stats.tags, stats.wikilink_edges,
        stats.embed_edges, len(stats.unresolved_links), len(scan.skipped),
    )
    return scan, stats


__all__ = [
    "VAULT_EXCLUDE_DIRS",
    "VaultScanStats",
    "is_obsidian_vault",
    "scan_vault",
    "tag_concept_id",
]
