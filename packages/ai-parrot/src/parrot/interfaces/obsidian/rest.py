"""Obsidian *Local REST API* community-plugin backend (aiohttp).

Talks to a running Obsidian instance with the `Local REST API
<https://github.com/coddingtonbear/obsidian-local-rest-api>`_ plugin
enabled. Route mapping:

* ``GET /vault/`` and ``GET /vault/{folder}/`` — directory listings
* ``GET/PUT/DELETE /vault/{path}`` — note read/write/delete
* ``POST /search/simple/?query=…`` — plugin-side simple search

The plugin serves HTTPS with a self-signed certificate on
``https://127.0.0.1:27124`` by default, hence ``verify_ssl=False`` as the
default for this localhost-only integration. Listings carry no
size/mtime, so :meth:`stat` degrades to existence + name (``mtime=None``).
"""
import asyncio
from typing import Any, Optional

import aiohttp

from .abstract import ObsidianVaultInterface, VaultAccessError
from .models import (
    CANVAS_SUFFIX,
    NOTE_SUFFIX,
    VaultFileInfo,
    VaultSearchHit,
)


class RestVaultBackend(ObsidianVaultInterface):
    """Vault access through the Obsidian Local REST API plugin."""

    def __init__(
        self,
        base_url: str = "https://127.0.0.1:27124",
        api_key: str = "",
        vault_name: Optional[str] = None,
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the backend.

        Args:
            base_url: Root URL of the Local REST API plugin.
            api_key: Bearer token configured in the plugin settings.
            vault_name: Logical vault name for node IDs and reports.
            verify_ssl: Verify the plugin's TLS certificate (it ships
                self-signed, so this defaults to False; localhost only).
            timeout: Total request timeout in seconds.
        """
        super().__init__(vault_name=vault_name)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def open(self) -> None:
        """Create the aiohttp session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self.verify_ssl or False)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )

    async def close(self) -> None:
        """Close the aiohttp session and drop the cached index."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        await super().close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expect_json: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Perform one API request, mapping HTTP errors to exceptions."""
        await self.open()
        assert self._session is not None
        url = f"{self.base_url}{path}"
        try:
            async with self._session.request(method, url, **kwargs) as response:
                if response.status == 404:
                    raise FileNotFoundError(f"Not found in vault: {path}")
                if response.status >= 400:
                    detail = (await response.text())[:200]
                    raise VaultAccessError(
                        f"Local REST API {method} {path} -> "
                        f"{response.status}: {detail}"
                    )
                if expect_json:
                    return await response.json(content_type=None)
                return await response.text()
        except aiohttp.ClientError as exc:
            raise VaultAccessError(
                f"Cannot reach Obsidian Local REST API at {self.base_url}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Primitives
    # ------------------------------------------------------------------ #
    async def list_files(
        self,
        folder: Optional[str] = None,
        recursive: bool = True,
        suffixes: Optional[frozenset[str]] = None,
    ) -> list[VaultFileInfo]:
        wanted = suffixes or frozenset({NOTE_SUFFIX, CANVAS_SUFFIX})
        found: list[VaultFileInfo] = []

        async def _walk(prefix: str) -> None:
            route = f"/vault/{prefix}" if prefix else "/vault/"
            if prefix and not route.endswith("/"):
                route += "/"
            payload = await self._request("GET", route, expect_json=True)
            entries = payload.get("files", []) if isinstance(payload, dict) else []
            subfolders: list[str] = []
            for entry in entries:
                name = str(entry)
                rel = f"{prefix}{name}"
                if name.endswith("/"):
                    if name.rstrip("/") not in self.skip_patterns:
                        subfolders.append(rel)
                    continue
                suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if suffix in wanted:
                    found.append(
                        VaultFileInfo(
                            path=rel,
                            name=name,
                            size=None,
                            mtime=None,
                            is_note=suffix == NOTE_SUFFIX,
                            is_canvas=suffix == CANVAS_SUFFIX,
                        )
                    )
            if recursive:
                for sub in subfolders:
                    await _walk(sub)

        start = ""
        if folder:
            start = folder.strip("/") + "/"
        await _walk(start)
        found.sort(key=lambda info: info.path)
        return found

    async def read_note(self, path: str) -> str:
        rel = self.normalize_note_path(path)
        return await self._request("GET", f"/vault/{rel}")

    async def write_note(
        self, path: str, content: str, *, overwrite: bool = True
    ) -> VaultFileInfo:
        rel = self.normalize_note_path(path)
        if not overwrite and await self.note_exists(rel):
            raise FileExistsError(f"Note already exists: {path}")
        await self._request(
            "PUT",
            f"/vault/{rel}",
            data=content.encode("utf-8"),
            headers={"Content-Type": "text/markdown"},
        )
        self.invalidate_index()
        return VaultFileInfo(
            path=rel,
            name=rel.rsplit("/", 1)[-1],
            size=len(content.encode("utf-8")),
            mtime=None,
            is_note=rel.endswith(NOTE_SUFFIX),
            is_canvas=rel.endswith(CANVAS_SUFFIX),
        )

    async def delete_note(self, path: str) -> bool:
        rel = self.normalize_note_path(path)
        try:
            await self._request("DELETE", f"/vault/{rel}")
        except FileNotFoundError:
            return False
        self.invalidate_index()
        return True

    async def note_exists(self, path: str) -> bool:
        try:
            await self.stat(path)
            return True
        except FileNotFoundError:
            return False

    async def stat(self, path: str) -> VaultFileInfo:
        rel = self.normalize_note_path(path)
        # The plugin has no metadata route for arbitrary files; a HEAD-style
        # GET both proves existence and yields the size. mtime is unknown.
        content = await self._request("GET", f"/vault/{rel}")
        return VaultFileInfo(
            path=rel,
            name=rel.rsplit("/", 1)[-1],
            size=len(str(content).encode("utf-8")),
            mtime=None,
            is_note=rel.endswith(NOTE_SUFFIX),
            is_canvas=rel.endswith(CANVAS_SUFFIX),
        )

    async def search(self, query: str, limit: int = 20) -> list[VaultSearchHit]:
        payload = await self._request(
            "POST",
            "/search/simple/",
            params={"query": query, "contextLength": 120},
            expect_json=True,
        )
        hits: list[VaultSearchHit] = []
        if isinstance(payload, list):
            for row in payload[:limit]:
                if not isinstance(row, dict):
                    continue
                matches = row.get("matches") or []
                snippet = None
                if matches and isinstance(matches[0], dict):
                    snippet = matches[0].get("context")
                hits.append(
                    VaultSearchHit(
                        path=str(row.get("filename", "")),
                        score=float(row.get("score", 0.0)),
                        snippet=snippet,
                        matches=["body"] if matches else [],
                    )
                )
        return hits
