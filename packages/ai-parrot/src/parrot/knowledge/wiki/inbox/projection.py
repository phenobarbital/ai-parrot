"""Write-only deterministic OKF projection of inbox document pages."""

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.wiki.export import category_dir, generate_index, page_frontmatter

_MACHINE_KEYS = ("category", "node_id", "source_id", "token_count", "created_at", "content_hash")


def doc_markdown_path(markdown_dir: Path, page: dict[str, Any]) -> Path:
    """Resolve the category directory and flattened concept filename."""
    return (
        Path(markdown_dir)
        / category_dir(str(page.get("category") or "concept"))
        / (f"{flatten_concept_id_for_filename(page['concept_id'])}.md")
    )


def render_doc_markdown(page: dict[str, Any], relates_to: list[dict[str, str]], tags: list[str]) -> str:
    """Render frontmatter, machine fields and body without modifying the input.

    Mirrors the file-store page renderer: OKF frontmatter, machine fields appended
    inside the same block, one newline, then the body.

    Args:
        page: Page row (not mutated).
        relates_to: Outgoing relation entries.
        tags: Custom tags; the page category is always the first tag.

    Returns:
        The full markdown file content.
    """
    category = str(page.get("category") or "concept")
    front = page_frontmatter(page, relates_to, tags=[category, *tags])
    machine: dict[str, Any] = {key: page[key] for key in _MACHINE_KEYS if page.get(key) not in (None, "")}
    if machine:
        extra = yaml.dump(machine, sort_keys=False, allow_unicode=True, default_flow_style=False)
        front = front[: -len("---\n")] + extra + "---\n"
    return front + "\n" + (page.get("body") or "")


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` through a sibling temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def write_doc_markdown(
    markdown_dir: Path,
    page: dict[str, Any],
    relates_to: list[dict[str, str]],
    tags: list[str],
) -> Path:
    """Atomically replace one markdown projection; synchronous by design.

    Call via ``asyncio.to_thread`` from async code. Failures propagate.

    Returns:
        The destination path.
    """
    path = doc_markdown_path(markdown_dir, page)
    _atomic_write(path, render_doc_markdown(page, relates_to, tags))
    return path


def write_inbox_index(markdown_dir: Path, store_pages: list[dict[str, Any]]) -> Path:
    """Atomically regenerate index.md from the supplied inbox doc pages.

    Returns:
        The index path.
    """
    markdown_dir = Path(markdown_dir)
    entries = [
        (
            str(page.get("title") or page["concept_id"]),
            doc_markdown_path(markdown_dir, page).relative_to(markdown_dir).as_posix(),
            str(page.get("summary") or ""),
        )
        for page in sorted(store_pages, key=lambda p: p["concept_id"])
    ]
    index_path = markdown_dir / "index.md"
    _atomic_write(index_path, generate_index("inbox", entries))
    return index_path
