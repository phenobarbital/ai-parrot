from typing import Any
from collections.abc import Callable
from pathlib import Path, PurePath
from langchain_community.document_loaders import TextLoader
from langchain.docstore.document import Document
from .abstract import AbstractLoader


class TXTLoader(AbstractLoader):
    """
    Loader for PDF files.
    """
    _extension = ['.txt']

    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'text',
        **kwargs
    ):
        super().__init__(tokenizer, text_splitter, source_type=source_type, **kwargs)
        self.path = path
        if isinstance(path, str):
            self.path = Path(path).resolve()

    def _load_document(self, path: Path) -> list:
        """
        Load a TXT file.

        Args:
            path (Path): The path to the TXT file.

        Returns:
            list: A list of Langchain Documents.
        """
        if self._check_path(path):
            self.logger.info(f"Loading TXT file: {path}")
            with open(path, 'r') as file:
                text = file.read()
            return [
                Document(
                    page_content=text,
                    metadata={
                        "url": '',
                        "index": str(path.name),
                        "source": str(path),
                        "filename": str(path.name),
                        "summary": '',
                        "question": '',
                        "answer": '',
                        'type': 'text',
                        "source_type": self._source_type,
                        "document_meta": {}
                    }
                )
            ]
        return []

    def load(self) -> list:
        """
        Load data from a TXT file.

        Args:
            source (str): The path to the TXT file.

        Returns:
            list: A list of Langchain Documents.
        """
        if not self.path.exists():
            raise FileNotFoundError(
                f"File/directory not found: {self.path}"
            )
        if self.path.is_dir():
            documents = []
            # iterate over the files in the directory
            for ext in self._extension:
                for item in self.path.glob(f'*{ext}'):
                    documents.extend(self._load_document(item))
        elif self.path.is_file():
            documents = self._load_document(self.path)
        else:
            raise ValueError(
                f"TXT Loader: Invalid path: {self.path}"
            )
        return self.split_documents(documents)

    def parse(self, source):
        raise NotImplementedError(
            "Parser method is not implemented for TXTLoader."
        )
