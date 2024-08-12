from collections.abc import Callable
from typing import Any
from abc import abstractmethod
from pathlib import Path, PurePath
from PIL import Image
from .abstract import AbstractLoader
from ..conf import STATIC_DIR


class BasePDF(AbstractLoader):
    """
    Base Abstract loader for all PDF files.
    """
    _extension = ['.pdf']

    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'pdf',
        language: str = "eng",
        **kwargs
    ):
        super().__init__(tokenizer, text_splitter, source_type=source_type, **kwargs)
        self.path = path
        if isinstance(path, str):
            self.path = Path(path).resolve()
        self.save_images: bool = bool(kwargs.get('save_images', False))
        self._imgdir = STATIC_DIR.joinpath('images')
        if self.save_images is True:
            if self._imgdir.exists() is False:
                self._imgdir.mkdir(parents=True, exist_ok=True)
        if language == 'en':
            language = 'eng'
        self._lang = language

    def save_image(self, img_stream: Image, image_name: str, save_path: Path):
        # Create the image directory if it does not exist
        if save_path.exists() is False:
            save_path.mkdir(parents=True, exist_ok=True)
        img_path = save_path.joinpath(image_name)
        self.logger.notice(
            f"Saving Image Page on {img_path}"
        )
        if not img_path.exists():
            # Save the image
            img_stream.save(img_path, format="PNG", optimize=True)
        return img_path

    @abstractmethod
    def _load_pdf(self, path: Path) -> list:
        """
        Load a PDF file using Fitz.

        Args:
            path (Path): The path to the PDF file.

        Returns:
            list: A list of Langchain Documents.
        """
        pass

    def load(self) -> list:
        """
        Load data from a PDF file.

        Args:
            source (str): The path to the PDF file.

        Returns:
            list: A list of Langchain Documents.
        """
        if isinstance(self.path, list):
            # list of files:
            documents = []
            for p in self.path:
                if self._check_path(p):
                    documents.extend(self._load_pdf(p))
        if not self.path.exists():
            raise FileNotFoundError(
                f"PDF file/directory not found: {self.path}"
            )
        if self.path.is_dir():
            documents = []
            # iterate over the files in the directory
            for ext in self._extension:
                for item in self.path.glob(f'*{ext}'):
                    if set(item.parts).isdisjoint(self.skip_directories):
                        documents.extend(self._load_pdf(item))
        elif self.path.is_file():
            documents = self._load_pdf(self.path)
        else:
            raise ValueError(
                f"PDF Loader: Invalid path: {self.path}"
            )
        return self.split_documents(documents)

    def parse(self, source):
        raise NotImplementedError(
            "Parser method is not implemented for PDFLoader."
        )
