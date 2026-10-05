"""Backend-neutral file-manager models shared by Graph and Google Drive managers (FEAT-608 M5).

Moved verbatim from ``graph.py``; imports neither msgraph nor aiogoogle.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from aiohttp import web
from navigator.utils.file.web import FileServingExtension
from pydantic import BaseModel, ConfigDict

__all__ = ("DriveEntry", "GuardedFileServingExtension")


class GuardedFileServingExtension(FileServingExtension):
    """FileServingExtension that refuses (413) files larger than ``max_bytes`` before buffering them (S7, AC22)."""

    def __init__(self, *args: Any, max_bytes: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_bytes = max_bytes

    async def handle_file(self, request: web.Request) -> web.StreamResponse:
        filepath = request.match_info.get("filepath", "")
        try:
            meta = await self.manager.get_file_metadata(filepath)
            if meta.size > self.max_bytes:
                return web.Response(status=413, text=f"File exceeds the serving limit of {self.max_bytes} bytes")
        except FileNotFoundError:
            # Expected: let the base extension's own 404 handling take over.
            pass
        except Exception as exc:
            # Unexpected (auth failure, transient Graph error, ...): the size guard degrades
            # fail-open by design (never blocks serving on a metadata-lookup error), but a
            # silent `except Exception: pass` here previously hid genuine problems. Log and
            # still fall through to the base extension.
            self.logger.warning("Size-guard metadata lookup failed for %r, serving unguarded: %s", filepath, exc)
        return await super().handle_file(request)


class DriveEntry(BaseModel):
    """One child of a folder, including folders returned by ``list_entries``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    path: str
    is_folder: bool
    size: int = 0
    modified_at: Optional[datetime] = None
    web_url: Optional[str] = None
    content_type: Optional[str] = None
