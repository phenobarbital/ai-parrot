"""Direct-filesystem Obsidian vault backend.

All blocking file I/O runs in ``asyncio.to_thread``. Every user-supplied
path passes the :meth:`LocalVaultBackend._resolve` sandbox guard — the
resolved path must stay under the vault root (same discipline as
``FileManagerToolkit``'s sandboxed local manager).
"""
import asyncio
import os
from pathlib import Path
from typing import Iterable, Optional

from .abstract import ObsidianVaultInterface
from .models import (
    CANVAS_SUFFIX,
    NOTE_SUFFIX,
    VaultFileInfo,
    VaultSearchHit,
)


class LocalVaultBackend(ObsidianVaultInterface):
    """Filesystem access to an Obsidian vault directory."""

    def __init__(
        self,
        vault_path: str | Path,
        vault_name: Optional[str] = None,
        extra_skip_patterns: Optional[Iterable[str]] = None,
    ) -> None:
        """Initialize the backend.

        Args:
            vault_path: Directory of the vault (must exist).
            vault_name: Logical vault name; defaults to the directory name.
            extra_skip_patterns: Extra directory names to exclude from
                discovery, unioned with the defaults (see
                :class:`~parrot.interfaces.obsidian.abstract.ObsidianVaultInterface`).

        Raises:
            ValueError: If ``vault_path`` is not an existing directory.
        """
        root = Path(vault_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Vault path is not a directory: {vault_path}")
        super().__init__(vault_name=vault_name or root.name, extra_skip_patterns=extra_skip_patterns)
        self.vault_path = root

    # ------------------------------------------------------------------ #
    # Path safety
    # ------------------------------------------------------------------ #
    def _resolve(self, path: str) -> Path:
        """Resolve a vault-relative path, rejecting escapes from the root.

        Raises:
            ValueError: If the resolved path leaves the vault directory.
        """
        candidate = (self.vault_path / path.lstrip("/")).resolve()
        if (
            candidate != self.vault_path
            and self.vault_path not in candidate.parents
        ):
            raise ValueError(f"Path escapes the vault root: {path}")
        return candidate

    def _relative(self, full: Path) -> str:
        return full.relative_to(self.vault_path).as_posix()

    def _skipped(self, full: Path) -> bool:
        parts = full.relative_to(self.vault_path).parts
        return any(part in self.skip_patterns for part in parts)

    def _info(self, full: Path, stat: Optional[os.stat_result] = None) -> VaultFileInfo:
        stat = stat or full.stat()
        suffix = full.suffix.lower()
        return VaultFileInfo(
            path=self._relative(full),
            name=full.name,
            size=stat.st_size,
            mtime=stat.st_mtime,
            is_note=suffix == NOTE_SUFFIX,
            is_canvas=suffix == CANVAS_SUFFIX,
        )

    # ------------------------------------------------------------------ #
    # Primitives
    # ------------------------------------------------------------------ #
    async def list_files(
        self,
        folder: Optional[str] = None,
        recursive: bool = True,
        suffixes: Optional[frozenset[str]] = None,
    ) -> list[VaultFileInfo]:
        base = self._resolve(folder) if folder else self.vault_path
        wanted = suffixes or frozenset({NOTE_SUFFIX, CANVAS_SUFFIX})

        def _scan() -> list[VaultFileInfo]:
            if not base.is_dir():
                raise FileNotFoundError(f"Folder not found: {folder}")
            pattern = "**/*" if recursive else "*"
            found = [
                self._info(item)
                for item in sorted(base.glob(pattern))
                if item.is_file()
                and item.suffix.lower() in wanted
                and not self._skipped(item)
            ]
            return found

        return await asyncio.to_thread(_scan)

    async def read_note(self, path: str) -> str:
        full = self._resolve(self.normalize_note_path(path))

        def _read() -> str:
            if not full.is_file():
                raise FileNotFoundError(f"Note not found: {path}")
            return full.read_text(encoding="utf-8")

        return await asyncio.to_thread(_read)

    async def write_note(
        self, path: str, content: str, *, overwrite: bool = True
    ) -> VaultFileInfo:
        full = self._resolve(self.normalize_note_path(path))

        def _write() -> VaultFileInfo:
            if full.exists() and not overwrite:
                raise FileExistsError(f"Note already exists: {path}")
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            return self._info(full)

        info = await asyncio.to_thread(_write)
        self.invalidate_index()
        return info

    async def delete_note(self, path: str) -> bool:
        full = self._resolve(self.normalize_note_path(path))

        def _delete() -> bool:
            if not full.is_file():
                return False
            full.unlink()
            return True

        removed = await asyncio.to_thread(_delete)
        if removed:
            self.invalidate_index()
        return removed

    async def note_exists(self, path: str) -> bool:
        full = self._resolve(self.normalize_note_path(path))
        return await asyncio.to_thread(full.is_file)

    async def stat(self, path: str) -> VaultFileInfo:
        full = self._resolve(self.normalize_note_path(path))

        def _stat() -> VaultFileInfo:
            if not full.is_file():
                raise FileNotFoundError(f"Note not found: {path}")
            return self._info(full)

        return await asyncio.to_thread(_stat)

    async def search(self, query: str, limit: int = 20) -> list[VaultSearchHit]:
        """Keyword scan over titles, aliases, tags and bodies.

        Deliberately simple (linear scan, Semaphore-bounded reads): the
        FTS5-backed wikitoolkit vault plane is the scalable search path.
        """
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []
        index = await self.build_index()
        semaphore = asyncio.Semaphore(16)
        hits: list[VaultSearchHit] = []

        async def _score(path: str) -> None:
            note = index.note(path)
            if note is None:
                return
            async with semaphore:
                haystacks = {
                    "title": note.title.lower(),
                    "tag": " ".join(note.tags).lower(),
                    "alias": " ".join(note.aliases).lower(),
                    "body": note.content.lower(),
                }
                score = 0.0
                matched: list[str] = []
                snippet: Optional[str] = None
                weights = {"title": 4.0, "tag": 3.0, "alias": 3.0, "body": 1.0}
                for field, text in haystacks.items():
                    field_hits = sum(text.count(term) for term in terms)
                    if field_hits:
                        matched.append(field)
                        score += weights[field] * field_hits
                        if field == "body" and snippet is None:
                            pos = min(
                                (text.find(t) for t in terms if t in text),
                                default=0,
                            )
                            start = max(0, pos - 60)
                            snippet = note.content[start:pos + 120].strip()
                if score > 0:
                    hits.append(
                        VaultSearchHit(
                            path=path, score=score,
                            snippet=snippet, matches=matched,
                        )
                    )

        await asyncio.gather(*(_score(path) for path in index.paths()))
        hits.sort(key=lambda hit: (-hit.score, hit.path))
        return hits[:limit]
