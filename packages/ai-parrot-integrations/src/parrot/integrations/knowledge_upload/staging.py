"""Private staging of uploaded bytes with guaranteed deletion (AC5)."""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_filename(name: str) -> str:
    """Return a safe basename or raise ``ValueError`` when it is empty."""
    normalized = unicodedata.normalize("NFC", name)
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    safe_name = "".join(character for character in basename if not unicodedata.category(character).startswith("C"))
    safe_name = safe_name.strip(" .")
    if not safe_name:
        raise ValueError("Filename is empty after sanitization")
    return safe_name


def _prepare_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)


@asynccontextmanager
async def staged_file(directory: Path, filename: str, data: bytes) -> AsyncIterator[Path]:
    """Write data to a private staging file and remove it when the context exits."""
    path = directory / safe_filename(filename)
    await asyncio.to_thread(_prepare_dir, directory)
    try:
        await asyncio.to_thread(path.write_bytes, data)
        yield path
    finally:
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except asyncio.CancelledError:
            path.unlink(missing_ok=True)
            raise


def sweep_staging(directory: Path) -> int:
    """Delete leftover regular files from a crashed run and return their count."""
    if not directory.exists():
        return 0

    count = 0
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        count += 1

    if count:
        logger.info("Removed %d leftover knowledge upload staging files", count)
    return count
