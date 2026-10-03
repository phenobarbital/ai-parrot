"""Backend-agnostic async access to an Obsidian vault.

``ObsidianVaultInterface`` defines the primitive operations every backend
must provide (list/read/write/delete/stat/search) and layers the shared
conveniences on top: parsed-note access (:meth:`get_note`), async iteration
(:meth:`iter_notes`) and a cached :class:`VaultIndex`
(:meth:`build_index`).

Backends:
    * :class:`parrot.interfaces.obsidian.local.LocalVaultBackend` — direct
      filesystem access to a vault directory (primary).
    * :class:`parrot.interfaces.obsidian.rest.RestVaultBackend` — the
      Obsidian *Local REST API* community plugin over aiohttp (optional,
      requires a running Obsidian instance).
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Iterable, Optional

from .index import VaultIndex
from .models import (
    CANVAS_SUFFIX,
    DEFAULT_SKIP_PATTERNS,
    NOTE_SUFFIX,
    ObsidianCanvas,
    ObsidianNote,
    VaultFileInfo,
    VaultSearchHit,
)
from .parser import ObsidianNoteParser, parse_canvas


class VaultAccessError(RuntimeError):
    """Raised for vault access failures (missing note, backend errors)."""


class ObsidianVaultInterface(ABC):
    """Abstract async interface over an Obsidian vault."""

    def __init__(
        self,
        vault_name: Optional[str] = None,
        extra_skip_patterns: Optional[Iterable[str]] = None,
    ) -> None:
        """Initialize shared backend state.

        Args:
            vault_name: Logical vault name for node IDs and reports.
            extra_skip_patterns: Additional directory names to exclude from
                vault discovery, unioned with :data:`DEFAULT_SKIP_PATTERNS`
                (``.obsidian``/``.trash``/``.git``). Backward-compatible —
                ``None`` keeps the defaults unchanged. Callers with a
                privacy boundary (e.g. the FEAT-481 wiki-KB agent, contract
                §1 "never access ``Private/``") pass their own exclusions
                here so search/catalog/list never traverse them.
        """
        self.vault_name: str = vault_name or "vault"
        self.logger = logging.getLogger(
            f"{type(self).__module__}.{type(self).__name__}"
        )
        self.parser = ObsidianNoteParser()
        self.skip_patterns: frozenset[str] = DEFAULT_SKIP_PATTERNS | frozenset(
            extra_skip_patterns or ()
        )
        self._index: Optional[VaultIndex] = None
        self._index_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def open(self) -> None:
        """Acquire backend resources (sessions, handles). Default: no-op."""

    async def close(self) -> None:
        """Release backend resources. Default: drops the cached index."""
        self._index = None

    # ------------------------------------------------------------------ #
    # Abstract primitives
    # ------------------------------------------------------------------ #
    @abstractmethod
    async def list_files(
        self,
        folder: Optional[str] = None,
        recursive: bool = True,
        suffixes: Optional[frozenset[str]] = None,
    ) -> list[VaultFileInfo]:
        """List vault files.

        Args:
            folder: Vault-relative folder to list; None for the vault root.
            recursive: Descend into subfolders.
            suffixes: Restrict to these suffixes (e.g. ``{".md"}``); None
                lists notes and canvas files.

        Returns:
            File descriptors, skip patterns already applied.
        """

    @abstractmethod
    async def read_note(self, path: str) -> str:
        """Read a note's raw text (frontmatter included).

        Args:
            path: Vault-relative path (``.md`` optional).

        Returns:
            Full file text.

        Raises:
            FileNotFoundError: If the note does not exist.
        """

    @abstractmethod
    async def write_note(
        self, path: str, content: str, *, overwrite: bool = True
    ) -> VaultFileInfo:
        """Create or replace a note.

        Args:
            path: Vault-relative path (``.md`` appended when missing).
            content: Full new file text.
            overwrite: When False, refuse to replace an existing note.

        Returns:
            Descriptor of the written file.

        Raises:
            FileExistsError: If the note exists and ``overwrite`` is False.
        """

    @abstractmethod
    async def delete_note(self, path: str) -> bool:
        """Delete a note. Returns True when a file was removed."""

    @abstractmethod
    async def note_exists(self, path: str) -> bool:
        """Whether a note exists at the vault-relative path."""

    @abstractmethod
    async def stat(self, path: str) -> VaultFileInfo:
        """File descriptor for one vault path.

        Raises:
            FileNotFoundError: If the path does not exist.
        """

    @abstractmethod
    async def search(self, query: str, limit: int = 20) -> list[VaultSearchHit]:
        """Backend-native text search over the vault.

        Args:
            query: Search terms.
            limit: Maximum hits.

        Returns:
            Hits sorted by descending score.
        """

    # ------------------------------------------------------------------ #
    # Shared conveniences
    # ------------------------------------------------------------------ #
    def normalize_note_path(self, path: str) -> str:
        """Normalize a user-supplied path to a POSIX ``.md`` path."""
        clean = path.strip().replace("\\", "/").lstrip("/")
        if not clean.lower().endswith((NOTE_SUFFIX, CANVAS_SUFFIX)):
            clean = f"{clean}{NOTE_SUFFIX}"
        return clean

    async def get_note(self, path: str) -> ObsidianNote:
        """Read and parse one note into an :class:`ObsidianNote`."""
        rel = self.normalize_note_path(path)
        raw = await self.read_note(rel)
        return await asyncio.to_thread(self.parser.parse, raw, rel)

    async def get_canvas(self, path: str) -> ObsidianCanvas:
        """Read and parse one ``.canvas`` file."""
        raw = await self.read_note(path)
        return parse_canvas(raw, path)

    async def iter_notes(
        self, folder: Optional[str] = None
    ) -> AsyncIterator[ObsidianNote]:
        """Iterate parsed notes, skipping unreadable files with a warning."""
        for info in await self.list_files(
            folder=folder, suffixes=frozenset({NOTE_SUFFIX})
        ):
            try:
                yield await self.get_note(info.path)
            except (FileNotFoundError, UnicodeDecodeError, ValueError) as exc:
                self.logger.warning("Skipping %s: %s", info.path, exc)

    async def load_notes(
        self, folder: Optional[str] = None, concurrency: int = 8
    ) -> list[ObsidianNote]:
        """Read and parse all notes concurrently (Semaphore-bounded)."""
        infos = await self.list_files(
            folder=folder, suffixes=frozenset({NOTE_SUFFIX})
        )
        semaphore = asyncio.Semaphore(concurrency)

        async def _one(info: VaultFileInfo) -> Optional[ObsidianNote]:
            async with semaphore:
                try:
                    return await self.get_note(info.path)
                except (FileNotFoundError, UnicodeDecodeError, ValueError) as exc:
                    self.logger.warning("Skipping %s: %s", info.path, exc)
                    return None

        notes = await asyncio.gather(*(_one(info) for info in infos))
        return [note for note in notes if note is not None]

    async def build_index(self, force: bool = False) -> VaultIndex:
        """Build (or return the cached) :class:`VaultIndex`.

        Args:
            force: Rebuild even when a cached index exists.

        Returns:
            The vault-wide link/tag/alias index.
        """
        async with self._index_lock:
            if self._index is None or force:
                notes = await self.load_notes()
                self._index = await asyncio.to_thread(VaultIndex.build, notes)
            return self._index

    def invalidate_index(self) -> None:
        """Drop the cached index (call after any note mutation)."""
        self._index = None
