"""
ActionCatalog — disk-backed store of sites and their catalogued actions.

Layout (one folder per site, one JSON file per action)::

    {catalog_dir}/
        hooba-es/
            _site.json          <- SiteInfo
            login.json          <- SiteAction
            goto-dashboard.json
            create-invoice-draft.json

All I/O is async: file contents go through aiofiles and filesystem
metadata operations run in a worker thread (``asyncio.to_thread``), so
the event loop is never blocked. Mutating operations are serialized by a
write lock, so concurrent tool calls cannot interleave a check-then-write
(e.g. two ``save_action(overwrite=False)`` for the same action).

Site and action names are slugified before touching the filesystem, so
catalog entries can never escape the catalog directory.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Union

import aiofiles

from .models import SiteAction, SiteInfo, slugify

logger = logging.getLogger(__name__)

_SITE_FILE = "_site.json"


class ActionCatalog:
    """Disk-backed catalog of sites and their deterministic actions.

    Args:
        catalog_dir: Root directory of the catalog. Created lazily on the
            first write.
    """

    def __init__(self, catalog_dir: Union[str, Path]) -> None:
        self._dir = Path(catalog_dir)
        self._sites: Dict[str, SiteInfo] = {}
        self._loaded = False
        self._load_lock = asyncio.Lock()
        #: Serializes every mutating operation (register/save/delete) so
        #: check-then-write sequences cannot interleave across coroutines.
        self._write_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    @property
    def catalog_dir(self) -> Path:
        """Root directory of the catalog."""
        return self._dir

    # ── Loading ───────────────────────────────────────────────────────

    async def load(self, *, force: bool = False) -> None:
        """Scan the catalog directory and load every site's metadata.

        Args:
            force: Re-scan even when already loaded.
        """
        async with self._load_lock:
            if self._loaded and not force:
                return
            sites: Dict[str, SiteInfo] = {}
            site_files = await asyncio.to_thread(self._scan_site_files)
            for site_file in site_files:
                try:
                    async with aiofiles.open(site_file, "r") as f:
                        content = await f.read()
                    info = SiteInfo.model_validate_json(content)
                    sites[info.site] = info
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "Skipping unreadable site metadata %s: %s",
                        site_file, exc,
                    )
            self._sites = sites
            self._loaded = True
            self.logger.info(
                "ActionCatalog loaded: %d site(s) from %s",
                len(self._sites), self._dir,
            )

    def _scan_site_files(self) -> List[Path]:
        """Blocking helper: list every ``_site.json`` (worker thread)."""
        if not self._dir.is_dir():
            return []
        return [
            site_dir / _SITE_FILE
            for site_dir in sorted(self._dir.iterdir())
            if site_dir.is_dir() and (site_dir / _SITE_FILE).is_file()
        ]

    # ── Sites ─────────────────────────────────────────────────────────

    async def register_site(
        self,
        info: SiteInfo,
        *,
        overwrite: bool = True,
    ) -> SiteInfo:
        """Create or update a site's metadata file.

        Args:
            info: Site metadata (slug auto-derived from its base URL).
            overwrite: Replace existing metadata. When ``False`` and the
                site exists, raises ``ValueError``.

        Returns:
            The stored :class:`SiteInfo`.
        """
        await self.load()
        async with self._write_lock:
            existing = self._sites.get(info.site)
            if existing is not None and not overwrite:
                raise ValueError(f"Site {info.site!r} already exists")
            if existing is not None:
                info = info.model_copy(
                    update={
                        "created_at": existing.created_at,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            site_dir = self._site_dir(info.site)
            await asyncio.to_thread(site_dir.mkdir, parents=True, exist_ok=True)
            async with aiofiles.open(site_dir / _SITE_FILE, "w") as f:
                await f.write(info.model_dump_json(indent=2))
            self._sites[info.site] = info
            self.logger.info("Registered site %r at %s", info.site, site_dir)
            return info

    async def list_sites(self) -> List[SiteInfo]:
        """Return every registered site's metadata."""
        await self.load()
        return sorted(self._sites.values(), key=lambda s: s.site)

    async def resolve_site(self, query: str) -> SiteInfo:
        """Resolve a natural reference ("hooba", "hooba.es") to a site.

        Args:
            query: Site slug, alias, domain, base URL, or title.

        Returns:
            The matching :class:`SiteInfo`.

        Raises:
            KeyError: No registered site matches *query*.
            ValueError: More than one site matches *query*.
        """
        await self.load()
        q = query.strip().lower()
        if q in self._sites:
            return self._sites[q]
        matches = [s for s in self._sites.values() if s.matches(q)]
        if not matches:
            # Last resort: substring against slug/title/domain.
            matches = [
                s for s in self._sites.values()
                if q and (q in s.site or q in s.title.lower() or q in s.domain)
            ]
        if not matches:
            known = ", ".join(sorted(self._sites)) or "(catalog is empty)"
            raise KeyError(
                f"No catalogued site matches {query!r}. Known sites: {known}"
            )
        if len(matches) > 1:
            names = ", ".join(sorted(s.site for s in matches))
            raise ValueError(
                f"Site reference {query!r} is ambiguous: {names}"
            )
        return matches[0]

    async def delete_site(self, query: str) -> bool:
        """Remove a site and every action file inside its folder.

        Args:
            query: Site reference (see :meth:`resolve_site`).

        Returns:
            ``True`` when the site existed and was removed.
        """
        await self.load()
        try:
            info = await self.resolve_site(query)
        except KeyError:
            return False
        async with self._write_lock:
            site_dir = self._site_dir(info.site)
            await asyncio.to_thread(self._remove_site_dir, site_dir)
            self._sites.pop(info.site, None)
            return True

    def _remove_site_dir(self, site_dir: Path) -> None:
        """Blocking helper: delete a site folder's JSON files + folder."""
        for path in sorted(site_dir.glob("*.json")):
            path.unlink(missing_ok=True)
        try:
            site_dir.rmdir()
        except OSError:
            self.logger.warning(
                "Site folder %s not empty after delete; leaving it", site_dir
            )

    # ── Actions ───────────────────────────────────────────────────────

    async def save_action(
        self,
        site_query: str,
        action: SiteAction,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Validate and persist an action script for a site.

        Steps are type-checked against the BrowserAction DSL before
        anything touches disk, so an invalid script never enters the
        catalog.

        Args:
            site_query: Site reference (see :meth:`resolve_site`).
            action: The action to store (``site`` is overwritten with the
                resolved slug).
            overwrite: Replace an existing action file.

        Returns:
            Path of the stored JSON file.

        Raises:
            FileExistsError: The action exists and *overwrite* is False.
            ValueError: The action's steps fail DSL validation.
        """
        info = await self.resolve_site(site_query)
        action.validate_steps()
        async with self._write_lock:
            path = self._action_path(info.site, action.name)
            if await asyncio.to_thread(path.exists):
                if not overwrite:
                    raise FileExistsError(
                        f"Action {action.name!r} already exists for site "
                        f"{info.site!r}. Pass overwrite=True to replace it."
                    )
                action = action.model_copy(
                    update={"updated_at": datetime.now(timezone.utc)}
                )
            stored = action.model_copy(update={"site": info.site})
            async with aiofiles.open(path, "w") as f:
                await f.write(stored.model_dump_json(indent=2))
            self.logger.info(
                "Saved action %s/%s -> %s", info.site, action.name, path
            )
            return path

    async def get_action(self, site_query: str, name: str) -> SiteAction:
        """Load one action script.

        Args:
            site_query: Site reference (see :meth:`resolve_site`).
            name: Action name (slugified before lookup).

        Returns:
            The stored :class:`SiteAction`.

        Raises:
            KeyError: The action does not exist for that site.
        """
        info = await self.resolve_site(site_query)
        path = self._action_path(info.site, name)
        if not await asyncio.to_thread(path.is_file):
            available = ", ".join(
                a.name for a in await self.list_actions(info.site)
            ) or "(none)"
            raise KeyError(
                f"Action {name!r} not found for site {info.site!r}. "
                f"Available: {available}"
            )
        async with aiofiles.open(path, "r") as f:
            content = await f.read()
        return SiteAction.model_validate_json(content)

    async def list_actions(self, site_query: str) -> List[SiteAction]:
        """Load every action of a site, sorted by name.

        Args:
            site_query: Site reference (see :meth:`resolve_site`).

        Returns:
            All parseable actions of the site.
        """
        info = await self.resolve_site(site_query)
        site_dir = self._site_dir(info.site)
        action_files = await asyncio.to_thread(
            self._scan_action_files, site_dir
        )
        actions: List[SiteAction] = []
        for path in action_files:
            try:
                async with aiofiles.open(path, "r") as f:
                    content = await f.read()
                actions.append(SiteAction.model_validate_json(content))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Skipping unreadable action file %s: %s", path, exc
                )
        return actions

    @staticmethod
    def _scan_action_files(site_dir: Path) -> List[Path]:
        """Blocking helper: list a site's action JSONs (worker thread)."""
        return [
            path
            for path in sorted(site_dir.glob("*.json"))
            if path.name != _SITE_FILE
        ]

    async def delete_action(self, site_query: str, name: str) -> bool:
        """Remove one action script from disk.

        Args:
            site_query: Site reference (see :meth:`resolve_site`).
            name: Action name.

        Returns:
            ``True`` when the file existed and was removed.
        """
        info = await self.resolve_site(site_query)
        async with self._write_lock:
            path = self._action_path(info.site, name)
            if not await asyncio.to_thread(path.is_file):
                return False
            await asyncio.to_thread(path.unlink)
            self.logger.info("Deleted action %s/%s", info.site, name)
            return True

    # ── Internal ──────────────────────────────────────────────────────

    def _site_dir(self, site_slug: str) -> Path:
        """Resolve a site folder, guarding against path escape."""
        site_dir = (self._dir / slugify(site_slug)).resolve()
        root = self._dir.resolve()
        if root not in site_dir.parents:
            raise ValueError(f"Invalid site slug {site_slug!r}")
        return site_dir

    def _action_path(self, site_slug: str, action_name: str) -> Path:
        """Resolve an action file path inside its site folder."""
        return self._site_dir(site_slug) / f"{slugify(action_name)}.json"
