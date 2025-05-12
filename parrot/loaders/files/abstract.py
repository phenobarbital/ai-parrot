from typing import Optional, Any
from abc import ABC, abstractmethod
from navconfig.logging import logging


class FilePlugin(ABC):
    """
    FilePlugin is a base class for Open Files.
    It provides a common interface for all opening all kind of iles.
    Subclasses should implement the `open` method to define
    the specific file processing logic.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the ImagePlugin with an optional image path.

        :param image: Path to the image file.
        """
        self.logger = logging.getLogger(
            f'parrot.FileLoader.{self.__class__.__name__}'
        )

    async def __aenter__(self):
        if hasattr(self, "open"):
            await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "close"):
            await self.close()
        return True

    @abstractmethod
    async def read(self):
        """
        Return the content of the file, need to be implemented in the subclass.
        """
        pass
