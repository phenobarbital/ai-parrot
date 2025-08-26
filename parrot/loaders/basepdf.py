from abc import abstractmethod
from typing import List, Union, Callable, Optional
from pathlib import Path
from pathlib import PurePath
from .abstract import AbstractLoader
from ..stores.models import Document


class BasePDF(AbstractLoader):
    """
    Base Abstract loader for all PDF-file Loaders.
    """
    extensions: set[str] = {'.pdf'}

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        as_markdown: bool = False,
        use_chapters: bool = False,
        use_pages: bool = False,
        **kwargs
    ):
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )
        self._lang = 'eng'
        self.doctype = 'pdf'
        self._source_type = source_type
        self.as_markdown = as_markdown
        self.use_chapters = use_chapters
        self.use_pages = use_pages

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
