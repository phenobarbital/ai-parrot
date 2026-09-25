"""FileManagerInterface double for figure and export tests (FEAT-601)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, Union


class FakeFileManager:
    """Store bytes by key and provide deterministic URLs and downloads."""

    def __init__(self, *, scheme: str = "https") -> None:
        self.scheme = scheme
        self.objects: dict[str, bytes] = {}
        self.url_calls: list[tuple[str, int]] = []
        self.missing: set[str] = set()

    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> Any:
        """Store source bytes at a destination key."""
        data = source.read_bytes() if isinstance(source, Path) else source.read()
        self.objects[destination] = data
        return SimpleNamespace(path=destination, size=len(data))

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a deterministic presigned-style URL."""
        self.url_calls.append((path, expiry))
        if self.scheme == "file":
            return f"file:///{path}"
        return f"{self.scheme}://fake/{path}?expiry={expiry}"

    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
        """Write a stored object to a path or binary destination."""
        if source in self.missing or source not in self.objects:
            raise FileNotFoundError(source)
        data = self.objects[source]
        if isinstance(destination, Path):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            return destination
        destination.write(data)
        return Path(getattr(destination, "name", source))
