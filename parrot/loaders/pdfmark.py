from typing import Any, Union, List
from collections.abc import Callable
from pathlib import PurePath
import fitz
from pdf4llm import to_markdown
from langchain.docstore.document import Document
from langchain.text_splitter import MarkdownTextSplitter
from .basepdf import BasePDF

class PDFMarkdownLoader(BasePDF):
    """
    Loader for PDF files converted content to markdown.
    """

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
        self._splitter = MarkdownTextSplitter(chunk_size = 1024, chunk_overlap=10)

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """
        Load a PDF file using the PDFMiner library.

        Args:
            path (Path): The path to the PDF file.

        Returns:
            list: A list of Langchain Documents.
        """
        self.logger.info(f"Loading PDF file: {path}")
        docs = []
        pdf = fitz.open(str(path))
        md_text = to_markdown(pdf, use_glyphs=True, show_progress=True) # get markdown for all pages
        try:
            summary = self.summary_from_text(md_text)
        except Exception:
            summary = ''
        metadata = {
            "url": '',
            "filename": path.name,
            "source": str(path.name),
            "type": 'pdf',
            "data": {},
            "category": self.category,
            "source_type": self._source_type,
            "document_meta": {
                "title": pdf.metadata.get("title", ""),
                # "subject": pdf.metadata.get("subject", ""),
                # "keywords": pdf.metadata.get("keywords", ""),
                "creationDate": pdf.metadata.get("creationDate", ""),
                # "modDate": pdf.metadata.get("modDate", ""),
                # "producer": pdf.metadata.get("producer", ""),
                # "creator": pdf.metadata.get("creator", ""),
                "author": pdf.metadata.get("author", ""),
            }
        }
        if summary:
            # create a document from summarization:
            self.create_document(
                content=summary,
                path=path,
                metadata={
                    **metadata,
                }
            )
        for _, chunk in enumerate(self._splitter.split_text(md_text)):
            _info = {
                **metadata
            }
            docs.append(
                Document(
                    page_content=chunk,
                    metadata=_info
                )
            )
        return docs
