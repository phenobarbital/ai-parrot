from typing import List
from pathlib import Path
from .abstract import AbstractLoader
from .files.text import TextFile


class TextLoader(AbstractLoader):
    """
    Loader for Text-based Files.
    """
    extensions: List[str] = ['.txt', '.text', '.md', '.markdown', '.rd']

    async def _load(self, path: Path, **kwargs) -> list:
        """
        Load a TXT file.

        Args:
            path (Path): The path to the TXT file.

        Returns:
            list: A list of Langchain Documents.
        """
        async with TextFile(path) as file:
            content = await file.read()
            return self.create_document(content, path)
        return []
