from typing import Union
from pathlib import Path, PurePath
from pydantic import PrivateAttr
from crewai_tools import BaseTool


class SaveFile(BaseTool):
    """Save a file to a directory."""
    name: str = "Save File"
    description: str = "Save a file to a directory."
    _directory: PrivateAttr

    def __init__(self, directory: Union[str, PurePath], **kwargs):
        super().__init__(**kwargs)
        if isinstance(directory, str):
            self._directory = Path(directory).resolve()
        self._directory = directory

    def _run(self, file: str, **kwargs) -> dict:
        """Run the Save File Tool."""
        filename = self._directory.joinpath(file)
        with open(filename, "w") as f:
            f.write(kwargs.get("content", ""))
        return {"file": file}
