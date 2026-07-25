"""FileStorage: JSON file source of rule definitions (stdlib only)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePath
from typing import Any, Union

from .abstract import AbstractStorage, StorageError


class FileStorage(AbstractStorage):
    """Loads a JSON list of definition dicts from a file.

    Args:
        path: Path to a JSON file containing a list of spec dicts.
    """

    def __init__(self, path: Union[str, PurePath]) -> None:
        super().__init__()
        self.path = Path(path)
        if not self.path.exists():
            raise StorageError(f"File {self.path} does not exist.")

    async def load(self) -> list[dict[str, Any]]:
        content = await asyncio.to_thread(self.path.read_text, "utf-8")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"Invalid JSON in {self.path}: {exc}"
            ) from exc
        if not isinstance(data, list):
            raise StorageError(
                f"{self.path} must contain a JSON list of definitions"
            )
        return data
