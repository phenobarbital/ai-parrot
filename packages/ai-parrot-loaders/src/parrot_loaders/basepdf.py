from abc import abstractmethod
from typing import List, Union, Callable, Optional
from pathlib import Path
from pathlib import PurePath
from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document


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
        self._lang = 'eng'   # OCR language code — NOT the document language
        self.doctype = 'pdf'
        self._source_type = source_type
        self.as_markdown = as_markdown
        self.use_chapters = use_chapters
        self.use_pages = use_pages

    def build_default_meta(
        self,
        path: Union[str, PurePath],
        *,
        language: Optional[str] = None,
        title: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Return canonical metadata for a PDF source.

        A convenience wrapper around :meth:`create_metadata` that pre-sets
        ``doctype`` and ``source_type`` to the PDF defaults.  Subclasses that
        override ``_load`` can call this instead of assembling raw dicts.

        Args:
            path: Filesystem path to the PDF file.
            language: Document language ISO code.  Falls back to
                ``self.language`` when not provided.
            title: Human-readable title.  Falls back to
                :meth:`_derive_title` when not provided.
            **kwargs: Loader-specific extras that become top-level metadata
                keys (e.g. ``page_index``, ``section``).

        Returns:
            A metadata dict with canonical top-level keys and a
            closed-shape ``document_meta`` sub-dict.
        """
        return self.create_metadata(
            path,
            doctype=self.doctype,
            source_type=self._source_type,
            language=language,
            title=title,
            **kwargs,
        )

    @abstractmethod
    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """Load data from a source and return it as a Parrot Document.

        Args:
            path (Union[str, PurePath, List[PurePath]]): The source of the data.

        Returns:
            List[Document]: A list of Parrot Documents.
        """
        self.logger.info(
            f"Loading file: {path}"
        )
