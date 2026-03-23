from typing import Any
from abc import ABC, abstractmethod
from PIL import Image
from navconfig.logging import logging


class ImagePlugin(ABC):
    """
    ImagePlugin is a base class for image processing plugins.
    It provides a common interface for image processing tasks.
    Subclasses should implement the `analyze` method to define
    the specific image processing logic.
    """
    column_name: str = "image_info"

    def __init__(self, *args, **kwargs):
        """
        Initialize the ImagePlugin with an optional image path.

        :param image: Path to the image file.
        """
        self.column_name = kwargs.get("column_name", self.column_name)
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    async def analyze(self, image: Image.Image, **kwargs) -> Any:
        """
        Analyze the image and perform the desired processing.

        :param image: Image Bytes opened with PIL Image.open
        """
        raise NotImplementedError(
            "Image Plugin must implement analyze() method."
        )

    async def __aenter__(self):
        if hasattr(self, "open"):
            await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "close"):
            await self.close()
        return True

    async def start(self):
        """
        Start the plugin. This method can be overridden by subclasses
        to perform any initialization or setup tasks.
        """
        pass
        return self

    async def dispose(self):
        """
        Dispose of the plugin resources.
        """
        return self
