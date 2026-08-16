"""ObsidianToolkit — agent tools for managing an Obsidian vault.

Built on the shared vault interface (``parrot.interfaces.obsidian``):
the same parsing, wikilink-resolution and backlink engine used by the
FEAT-392 vault loader and the wikitoolkit vault scanner. Supports both
vault backends — direct filesystem (``backend="local"``) and the Obsidian
Local REST API community plugin (``backend="rest"``).

Follows the one-tool-per-operation design (see ``FileManagerToolkit``):
every public async method becomes an LLM-callable tool named
``obsidian_<method>``; destructive operations are declared in
``confirming_tools`` for human-in-the-loop confirmation.
"""
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Set

from parrot.interfaces.obsidian import (
    ObsidianNote,
    ObsidianVaultInterface,
    create_vault_backend,
)

from .toolkit import AbstractToolkit

#: Maps allowed_operations keys → method names used in exclude_tools filtering.
_OP_TO_METHOD: Dict[str, str] = {
    "read": "read_note",
    "bulk_read": "read_notes",
    "list": "list_notes",
    "search": "search_notes",
    "search_tag": "search_by_tag",
    "search_backlinks": "search_with_backlinks",
    "backlinks": "get_backlinks",
    "outlinks": "get_outgoing_links",
    "metadata": "get_note_metadata",
    "catalog": "catalog_notes",
    "create": "create_note",
    "update": "update_note",
    "append": "append_note",
    "delete": "delete_note",
    "move": "move_note",
}
_ALL_OPS: frozenset = frozenset(_OP_TO_METHOD)

#: Operations that mutate the vault (invalidate the cached VaultIndex).
_MUTATING_METHODS: frozenset = frozenset(
    {"create_note", "update_note", "append_note", "delete_note", "move_note"}
)


def _note_payload(note: ObsidianNote, include_content: bool = True) -> Dict[str, Any]:
    """JSON-safe dict projection of a parsed note."""
    payload: Dict[str, Any] = {
        "path": note.path.as_posix(),
        "title": note.title,
        "frontmatter": note.frontmatter,
        "tags": sorted(note.tags),
        "aliases": note.aliases,
        "links": [link.model_dump() for link in note.links],
        "dataview_queries": note.dataview_queries,
    }
    if include_content:
        payload["content"] = note.content
    return payload


class ObsidianToolkit(AbstractToolkit):
    """Toolkit for AI agents to manage an Obsidian vault.

    Tool names (with ``tool_prefix="obsidian"``):
      - ``obsidian_read_note``            — read one note (parsed + content)
      - ``obsidian_read_notes``           — bulk-read several notes
      - ``obsidian_list_notes``           — list notes with file info
      - ``obsidian_search_notes``         — keyword search over the vault
      - ``obsidian_search_by_tag``        — notes carrying a tag
      - ``obsidian_search_with_backlinks``— search + link neighborhood
      - ``obsidian_get_backlinks``        — notes linking to a note
      - ``obsidian_get_outgoing_links``   — a note's resolved outlinks
      - ``obsidian_get_note_metadata``    — frontmatter + stat, no body
      - ``obsidian_catalog_notes``        — vault catalog and health report
      - ``obsidian_create_note``          — create a note (confirming)
      - ``obsidian_update_note``          — replace note body (confirming)
      - ``obsidian_append_note``          — append to a note (confirming)
      - ``obsidian_delete_note``          — delete a note (confirming)
      - ``obsidian_move_note``            — move/rename a note (confirming)

    Example::

        toolkit = ObsidianToolkit(vault_path="~/vaults/notes")
        tools = toolkit.get_tools()
        result = await toolkit.search_notes(query="retrieval")
    """

    #: Namespace prefix applied to every auto-generated tool name.
    tool_prefix: Optional[str] = "obsidian"

    #: FEAT-391 lifecycle: open the backend + build the index lazily.
    auto_open: bool = True

    #: Destructive operations requiring human-in-the-loop confirmation.
    confirming_tools: frozenset = frozenset(
        {"create_note", "update_note", "append_note", "delete_note", "move_note"}
    )

    def __init__(
        self,
        vault_path: Optional[str | Path] = None,
        backend: Literal["local", "rest"] = "local",
        vault: Optional[ObsidianVaultInterface] = None,
        allowed_operations: Optional[Set[str]] = None,
        **backend_kwargs: Any,
    ) -> None:
        """Initialize the Obsidian toolkit.

        Args:
            vault_path: Vault directory (local backend). Ignored when a
                prebuilt ``vault`` is injected.
            backend: ``"local"`` (filesystem) or ``"rest"`` (Local REST API
                plugin; pass ``base_url``/``api_key`` via backend_kwargs).
            vault: Optional prebuilt backend instance (overrides
                ``vault_path``/``backend``).
            allowed_operations: Restrict which operations become tools.
                Subset of ``{"read", "bulk_read", "list", "search",
                "search_tag", "search_backlinks", "backlinks", "outlinks",
                "metadata", "catalog", "create", "update", "append",
                "delete", "move"}``. ``None`` exposes all.
            **backend_kwargs: Forwarded to the backend constructor.

        Raises:
            ValueError: For unknown operations or a missing vault source.
        """
        if allowed_operations is not None:
            unknown = set(allowed_operations) - _ALL_OPS
            if unknown:
                raise ValueError(
                    f"ObsidianToolkit: unknown operation(s): {sorted(unknown)!r}. "
                    f"Valid operations are: {sorted(_ALL_OPS)}"
                )
            # Compute exclude_tools BEFORE super().__init__ so that
            # _generate_tools() sees the instance-level override.
            self.exclude_tools = tuple(
                method
                for op, method in _OP_TO_METHOD.items()
                if op not in allowed_operations
            )

        super().__init__()

        if vault is not None:
            self.vault = vault
        else:
            if backend == "local":
                if vault_path is None:
                    raise ValueError(
                        "ObsidianToolkit: vault_path is required for the "
                        "local backend"
                    )
                backend_kwargs.setdefault("vault_path", vault_path)
            self.vault = create_vault_backend(backend=backend, **backend_kwargs)
        self.allowed_operations: Set[str] = (
            set(allowed_operations) if allowed_operations is not None else set(_ALL_OPS)
        )

    # ------------------------------------------------------------------ #
    # Lifecycle (FEAT-391)
    # ------------------------------------------------------------------ #
    async def _open(self) -> None:
        """Open the vault backend and warm the link index."""
        await self.vault.open()
        await self.vault.build_index()

    async def _close(self) -> None:
        """Close the vault backend."""
        await self.vault.close()
        await super()._close()

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Invalidate the cached VaultIndex after mutating operations."""
        method = tool_name
        prefix = f"{self.tool_prefix}{self.prefix_separator}"
        if method.startswith(prefix):
            method = method[len(prefix):]
        if method in _MUTATING_METHODS:
            self.vault.invalidate_index()
        return result

    # ------------------------------------------------------------------ #
    # Read tools
    # ------------------------------------------------------------------ #
    async def read_note(self, path: str, include_content: bool = True) -> Dict[str, Any]:
        """Read one Obsidian note: content plus parsed structure.

        Args:
            path: Vault-relative note path (``.md`` optional).
            include_content: Include the full markdown body (default True).

        Returns:
            Dict with path, title, content, frontmatter, tags, aliases,
            links and dataview_queries.

        Raises:
            FileNotFoundError: If the note does not exist.
        """
        note = await self.vault.get_note(path)
        return _note_payload(note, include_content=include_content)

    async def read_notes(
        self, paths: list[str], include_content: bool = True
    ) -> Dict[str, Any]:
        """Bulk-read several notes in one call.

        Args:
            paths: Vault-relative note paths (max 50 per call).
            include_content: Include full markdown bodies (default True).

        Returns:
            Dict with ``notes`` (successfully read, parsed payloads) and
            ``errors`` (path -> error message for failed reads).
        """
        capped = paths[:50]
        notes: list[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for path in capped:
            try:
                note = await self.vault.get_note(path)
                notes.append(_note_payload(note, include_content=include_content))
            except (FileNotFoundError, UnicodeDecodeError, ValueError) as exc:
                errors[path] = str(exc)
        return {
            "notes": notes,
            "errors": errors,
            "truncated": len(paths) > len(capped),
        }

    async def list_notes(
        self, folder: Optional[str] = None, recursive: bool = True
    ) -> Dict[str, Any]:
        """List markdown notes in the vault (or one folder).

        Args:
            folder: Vault-relative folder; None for the whole vault.
            recursive: Descend into subfolders (default True).

        Returns:
            Dict with ``notes`` (path/name/size/mtime descriptors) and
            ``count``.
        """
        infos = await self.vault.list_files(
            folder=folder, recursive=recursive, suffixes=frozenset({".md"})
        )
        return {
            "notes": [info.model_dump() for info in infos],
            "count": len(infos),
        }

    async def get_note_metadata(self, path: str) -> Dict[str, Any]:
        """Read a note's frontmatter and file info without its body.

        Args:
            path: Vault-relative note path.

        Returns:
            Dict with path, title, frontmatter, tags, aliases and file
            stat info (size, mtime when available).

        Raises:
            FileNotFoundError: If the note does not exist.
        """
        note = await self.vault.get_note(path)
        stat = await self.vault.stat(path)
        payload = _note_payload(note, include_content=False)
        payload["file"] = stat.model_dump()
        return payload

    # ------------------------------------------------------------------ #
    # Search tools
    # ------------------------------------------------------------------ #
    async def search_notes(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """Search notes by keywords over titles, tags, aliases and bodies.

        Args:
            query: Search terms (space-separated keywords).
            limit: Maximum results (default 20).

        Returns:
            Dict with ``hits`` (path, score, snippet, matched fields) and
            ``count``.
        """
        hits = await self.vault.search(query, limit=limit)
        return {"hits": [hit.model_dump() for hit in hits], "count": len(hits)}

    async def search_by_tag(self, tag: str, limit: int = 50) -> Dict[str, Any]:
        """Find notes carrying a tag (inline ``#tag`` or frontmatter).

        Nested tags match by prefix: searching ``project`` also returns
        notes tagged ``project/status``.

        Args:
            tag: Tag name with or without the leading ``#``.
            limit: Maximum results (default 50).

        Returns:
            Dict with ``paths`` of matching notes and ``count``.
        """
        index = await self.vault.build_index()
        paths = index.notes_by_tag(tag)[:limit]
        return {"tag": tag.lstrip("#"), "paths": paths, "count": len(paths)}

    async def search_with_backlinks(
        self, query: str, limit: int = 10, expand: int = 5
    ) -> Dict[str, Any]:
        """Search notes, expanding each hit with its link neighborhood.

        For every search hit, includes up to ``expand`` backlinks (notes
        pointing at the hit) and ``expand`` outgoing links — the
        hand-curated context Obsidian users build via wikilinks.

        Args:
            query: Search terms.
            limit: Maximum primary hits (default 10).
            expand: Maximum backlinks/outlinks listed per hit (default 5).

        Returns:
            Dict with ``hits``; each hit carries path, score, snippet,
            ``backlinks`` and ``outlinks``.
        """
        hits = await self.vault.search(query, limit=limit)
        index = await self.vault.build_index()
        enriched = []
        for hit in hits:
            outlinks = []
            for link in index.outlinks(hit.path)[:expand]:
                resolved = index.resolve(link.target, from_path=hit.path)
                outlinks.append(
                    {
                        "target": link.target,
                        "resolved_path": resolved,
                        "is_embed": link.is_embed,
                    }
                )
            enriched.append(
                {
                    **hit.model_dump(),
                    "backlinks": index.backlinks(hit.path)[:expand],
                    "outlinks": outlinks,
                }
            )
        return {"hits": enriched, "count": len(enriched)}

    async def get_backlinks(self, path: str) -> Dict[str, Any]:
        """List notes whose wikilinks resolve to this note.

        Args:
            path: Vault-relative note path.

        Returns:
            Dict with ``backlinks`` (note paths) and ``count``.
        """
        index = await self.vault.build_index()
        backlinks = index.backlinks(path)
        return {"path": path, "backlinks": backlinks, "count": len(backlinks)}

    async def get_outgoing_links(self, path: str) -> Dict[str, Any]:
        """List a note's outgoing wikilinks/embeds with resolution status.

        Args:
            path: Vault-relative note path.

        Returns:
            Dict with ``links`` (target, alias, heading, is_embed,
            resolved_path or null) and ``unresolved`` targets.
        """
        index = await self.vault.build_index()
        links = []
        unresolved = []
        for link in index.outlinks(path):
            resolved = index.resolve(link.target, from_path=path)
            links.append({**link.model_dump(), "resolved_path": resolved})
            if resolved is None:
                unresolved.append(link.target)
        return {"path": path, "links": links, "unresolved": unresolved}

    async def catalog_notes(self, folder: Optional[str] = None) -> Dict[str, Any]:
        """Catalog the vault: folders, tags, orphans, broken links, aliases.

        Args:
            folder: Restrict the folder statistics to one subtree; the
                link/tag analysis always covers the whole vault.

        Returns:
            Dict with ``note_count``, ``notes_per_folder``, ``tags`` (tag ->
            count), ``orphans``, ``broken_links`` (from_path -> target) and
            ``aliases`` (alias -> path).
        """
        index = await self.vault.build_index()
        infos = await self.vault.list_files(
            folder=folder, suffixes=frozenset({".md"})
        )
        per_folder: Dict[str, int] = {}
        for info in infos:
            parent = info.path.rsplit("/", 1)[0] if "/" in info.path else "."
            per_folder[parent] = per_folder.get(parent, 0) + 1
        return {
            "note_count": len(infos),
            "notes_per_folder": dict(sorted(per_folder.items())),
            "tags": index.tags(),
            "orphans": index.orphans(),
            "broken_links": [
                {"from": src, "target": target} for src, target in index.unresolved()
            ],
            "aliases": index.aliases(),
        }

    # ------------------------------------------------------------------ #
    # Write tools (confirming)
    # ------------------------------------------------------------------ #
    async def create_note(
        self,
        path: str,
        content: str,
        frontmatter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new note (fails if it already exists).

        Args:
            path: Vault-relative path for the new note.
            content: Markdown body.
            frontmatter: Optional YAML frontmatter mapping (tags, aliases,
                custom keys) rendered ahead of the body.

        Returns:
            Descriptor of the created file.

        Raises:
            FileExistsError: If a note already exists at ``path``.
        """
        text = content
        if frontmatter:
            import yaml

            block = yaml.safe_dump(
                frontmatter, default_flow_style=False, sort_keys=False,
                allow_unicode=True,
            )
            text = f"---\n{block}---\n\n{content}"
        info = await self.vault.write_note(path, text, overwrite=False)
        return {"created": True, "file": info.model_dump()}

    async def update_note(
        self, path: str, content: str, preserve_frontmatter: bool = True
    ) -> Dict[str, Any]:
        """Replace a note's markdown body.

        Args:
            path: Vault-relative note path (must exist).
            content: New markdown body.
            preserve_frontmatter: Keep the existing YAML frontmatter block
                (default True); False replaces the whole file with
                ``content``.

        Returns:
            Descriptor of the updated file.

        Raises:
            FileNotFoundError: If the note does not exist.
        """
        raw = await self.vault.read_note(path)  # raises if missing
        text = content
        if preserve_frontmatter:
            import frontmatter as fm

            try:
                post = fm.loads(raw)
                if post.metadata:
                    post.content = content
                    text = fm.dumps(post)
            except Exception:  # noqa: BLE001 — fall back to raw replacement
                text = content
        info = await self.vault.write_note(path, text, overwrite=True)
        return {"updated": True, "file": info.model_dump()}

    async def append_note(self, path: str, content: str) -> Dict[str, Any]:
        """Append markdown to the end of an existing note.

        Args:
            path: Vault-relative note path (must exist).
            content: Markdown to append.

        Returns:
            Descriptor of the updated file.

        Raises:
            FileNotFoundError: If the note does not exist.
        """
        raw = await self.vault.read_note(path)
        joined = raw.rstrip("\n") + "\n\n" + content.lstrip("\n")
        info = await self.vault.write_note(path, joined, overwrite=True)
        return {"appended": True, "file": info.model_dump()}

    async def delete_note(self, path: str) -> Dict[str, Any]:
        """Delete a note from the vault.

        Args:
            path: Vault-relative note path.

        Returns:
            Dict with ``deleted`` (bool) and the affected ``backlinks``
            that now point at a missing note.
        """
        index = await self.vault.build_index()
        norm = path[:-3] if path.lower().endswith(".md") else path
        affected = index.backlinks(norm)
        deleted = await self.vault.delete_note(path)
        return {"deleted": deleted, "path": path, "affected_backlinks": affected}

    async def move_note(self, source: str, destination: str) -> Dict[str, Any]:
        """Move or rename a note within the vault.

        Args:
            source: Current vault-relative path.
            destination: New vault-relative path.

        Returns:
            Dict with the new file descriptor and ``affected_backlinks`` —
            notes whose ``[[wikilinks]]`` referenced the old path/name and
            may now be broken (links are NOT rewritten automatically).

        Raises:
            FileNotFoundError: If the source note does not exist.
            FileExistsError: If a note already exists at the destination.
        """
        raw = await self.vault.read_note(source)
        index = await self.vault.build_index()
        norm = source[:-3] if source.lower().endswith(".md") else source
        affected = index.backlinks(norm)
        info = await self.vault.write_note(destination, raw, overwrite=False)
        await self.vault.delete_note(source)
        return {
            "moved": True,
            "from": source,
            "file": info.model_dump(),
            "affected_backlinks": affected,
        }
