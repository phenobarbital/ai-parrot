"""Locked local-plane persistence and atomic Markdown output."""

import asyncio
import json
import os
import uuid
from contextlib import AbstractContextManager
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.project import wiki_write_lock
from parrot.knowledge.wiki.standup.models import BriefDocument
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord


class WriteResult(BaseModel):
    """Independent page/file receipts plus nonfatal write diagnostics."""

    written_page: bool = False
    written_file: str | None = None
    diagnostics: list[str] = Field(default_factory=list)


def _brief_filename(brief_id: str) -> str:
    """Return a stable filename for a stable brief page identity."""
    return f"{brief_id.replace(':', '-')}.md"


def _vault_markers(target: Path, vault_dir: Path | None, brief_id: str) -> str:
    """Return managed-note markers only when the target is inside the vault."""
    if vault_dir is None:
        return ""
    try:
        target.resolve().relative_to(vault_dir.resolve())
    except ValueError:
        return ""
    return f"---\nwiki_sync: local\nwiki_scope: local\nwiki_id: {brief_id}\n---\n\n"


def _write_markdown(target: Path, content: str, vault_dir: Path | None, brief_id: str) -> None:
    """Write a brief through a unique sibling temporary file then replace it."""
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target_content = _vault_markers(target, vault_dir, brief_id) + content
        temporary.write_text(target_content, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _close_lock(lock: AbstractContextManager[bool]) -> None:
    """Close a previously entered wiki lock in the worker thread."""
    lock.__exit__(None, None, None)


async def _write_page(record: WikiPageRecord, store: BaseWikiStore, storage_dir: Path) -> str | None:
    """Write one page while holding the local wiki lock without blocking asyncio."""
    lock: AbstractContextManager[bool] = wiki_write_lock(storage_dir)
    acquired = await asyncio.to_thread(lock.__enter__)
    if not acquired:
        await asyncio.to_thread(_close_lock, lock)
        return "Wiki write lock is held by another writer"
    try:
        await store.upsert_pages([record])
    except Exception as exc:  # noqa: BLE001 -- receipt reports independent output failures
        return f"Page write failed: {exc}"
    finally:
        await asyncio.to_thread(_close_lock, lock)
    return None


async def write(
    doc: BriefDocument,
    rendered: str,
    *,
    store: BaseWikiStore,
    storage_dir: Path,
    out_dir: Path,
    write_page: bool,
    write_file: bool,
    vault_dir: Path | None,
) -> WriteResult:
    """Persist requested outputs independently without writing foreign namespaces.

    Args:
        doc: Fully assembled brief and its stable identity.
        rendered: Markdown body produced by the renderer.
        store: Local writable wiki store.
        storage_dir: Local store directory used by the write lock and bookkeeper.
        out_dir: Directory for the optional Markdown projection.
        write_page: Whether to persist the local wiki page.
        write_file: Whether to persist the Markdown file.
        vault_dir: Configured Obsidian vault root, if any.

    Returns:
        Explicit receipts for the independently requested outputs.
    """
    result = WriteResult()
    if not write_page and not write_file:
        return result

    brief_id = doc.window.brief_id
    if write_page:
        attrs = {
            "type": "deliverable",
            "status": "draft",
            "date": doc.window.anchor.isoformat(),
            "owner": doc.identity.wiki,
            "period": doc.window.period,
            "items": json.dumps(sorted(set(doc.item_ids))),
            "source": "brief",
            "language": doc.language,
        }
        record = WikiPageRecord(
            concept_id=brief_id,
            title=f"{doc.window.period.title()} brief — {doc.window.anchor.isoformat()}",
            category="brief",
            summary=f"{doc.window.period.title()} brief for {doc.window.anchor.isoformat()}",
            body=rendered,
            origin="authored",
            asserted_by=doc.identity.wiki,
            attrs=attrs,
        )
        diagnostic = await _write_page(record, store, storage_dir)
        if diagnostic is None:
            result.written_page = True
        else:
            result.diagnostics.append(diagnostic)

    if write_file:
        target = out_dir / _brief_filename(brief_id)
        try:
            await asyncio.to_thread(_write_markdown, target, rendered, vault_dir, brief_id)
        except OSError as exc:
            result.diagnostics.append(f"File write failed: {exc}")
        else:
            result.written_file = str(target)

    if result.written_page or result.written_file is not None:
        details = f"brief: {brief_id}, page: {result.written_page}, file: {result.written_file or 'none'}"
        try:
            await asyncio.to_thread(WikiBookkeeper().log_operation, storage_dir, "STANDUP", details)
        except OSError as exc:
            result.diagnostics.append(f"STANDUP bookkeeping failed: {exc}")
    return result
