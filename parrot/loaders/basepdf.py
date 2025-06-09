from abc import abstractmethod
from typing import List, Union, Any, Callable
from pathlib import Path, PurePath
from langchain.docstore.document import Document
from .abstract import AbstractLoader


class BasePDF(AbstractLoader):
    """
    Base Abstract loader for all PDF-file Loaders.
    """
    extensions: List[str] = ['.pdf']

    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'pdf',
        language: str = "eng",
        **kwargs
    ):
        super().__init__(
            path=path,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            language=language,
            **kwargs
        )
        self._lang = 'eng'

    @abstractmethod
    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """Load data from a source and return it as a Langchain Document.

        Args:
            path (Union[str, PurePath, List[PurePath]]): The source of the data.

        Returns:
            List[Document]: A list of Langchain Documents.
        """
        self.logger.info(
            f"Loading file: {path}"
        )
