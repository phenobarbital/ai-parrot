"""Shared structural contract for ebook loaders and knowledge indexes."""

from __future__ import annotations

from parrot.stores.models import Document
from pydantic import BaseModel, Field


class EbookSection(BaseModel):
    """A source section whose identity and parent do not depend on headings."""

    section_id: str
    title: str
    href: str = ""
    parent_id: str | None = None
    depth: int = Field(default=1, ge=1)
    toc_order: int = Field(default=0, ge=0)
    reading_order: int = Field(default=0, ge=0)
    content: str = ""
    source_uri: str = ""
    target_found: bool = False
    origin: str = "toc"


def ebook_sections(documents: list[Document]) -> list[EbookSection]:
    """Recover structural records from either section or full-book documents."""
    sections: list[EbookSection] = []
    for document in documents:
        metadata = document.metadata
        if metadata.get("content_type") == "toc":
            continue
        if entry := metadata.get("ebook_section"):
            sections.append(EbookSection.model_validate({**entry, "content": document.page_content}))
        elif entries := metadata.get("ebook_sections"):
            sections.extend(EbookSection.model_validate(entry) for entry in entries)
    return sections


def ebook_markdown(sections: list[EbookSection]) -> str:
    """Render readable Markdown while keeping the exact hierarchy in records."""
    by_id = {section.section_id: section for section in sections}
    emitted: set[str] = set()
    parts: list[str] = []

    def emit(section: EbookSection) -> None:
        if section.section_id in emitted:
            return
        emitted.add(section.section_id)
        if section.parent_id in by_id:
            emit(by_id[section.parent_id])
        heading = "#" * min(section.depth, 6)
        parts.append(f"{heading} {section.title}\n\n{section.content}".rstrip())

    for section in sorted(sections, key=lambda section: section.reading_order):
        emit(section)
    return "\n\n".join(parts)
