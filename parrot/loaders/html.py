from typing import Union, List, Callable, Any
from datetime import datetime
from pathlib import PurePath
from markdownify import markdownify as md
from ..stores.models import Document
from .abstract import AbstractLoader
from .files.html import HTMLFile


class HTMLLoader(AbstractLoader):
    """
    Loader for HTML files to convert into Parrot Documents.

    Processes HTML files, extracts relevant content, converts to Markdown,
    and associates metadata with each document.
    """

    extensions: List[str] = ['.html', '.htm']

    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'html',
        language: str = "eng",
        chunk_size: int = 1024,
        chunk_overlap: int = 10,
        **kwargs
    ):
        """Initialize the HTMLLoader."""
        self.elements: list = kwargs.pop('elements', [])
        super().__init__(
            path=path,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            language=language,
            **kwargs
        )
        # Initialize markdown splitter
        self._splitter = self._get_markdown_splitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """
        Load a TXT file.

        Args:
            path (Path): The path to the TXT file.

        Returns:
            list: A list of Parrot Documents.
        """
        docs = []
        async with HTMLFile(path) as file:
            soup, content = await file.read()
            # Extract the entire <body> content or
            # Determine the top-level element to process
            top_element = soup.body or soup
            if not top_element:
                raise ValueError(
                    "The HTML file does not contain a <body> or Top element tag."
                )

            extracted_elements = []
            if self.elements:
                # Extract content from specific elements
                for element in self.elements:
                    for tag, selector in element.items():
                        extracted_elements.extend(
                            top_element.find_all(tag, class_=selector.lstrip('.'))
                        )
            if not extracted_elements:
                extracted_elements = [top_element]

            # Process each extracted element
            for elem in extracted_elements:
                # Get the plain text content
                text = elem.get_text(separator="\n", strip=True)

                # Generate a summary for the extracted text
                try:
                    summary = self.summary_from_text(text)
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error generating summary: {e}")
                    summary = None

            # Create document-level context
            document_context = f"File Name: {path.name}\n"
            document_context += f"Document Type: {self.doctype}\n"
            document_context += f"Source Type: {self._source_type}\n"
            document_context += f"Element: {elem.name}\n"

            # Convert the entire <body> to Markdown for better structure
            markdown_content = md(str(elem))

            # Metadata preparation
            document_meta = self.create_metadata(
                path=path,
                doctype=self.doctype,
                source_type=self._source_type,
                doc_metadata={
                    "type": "html",
                    "category": self.category,
                }
            )

            # Create a single Langchain Document with the full body content
            document = Document(
                page_content=document_context + markdown_content,
                metadata=document_meta
            )
            docs.append(document)

            # Create a document from summary (if any):
            if summary:
                document = Document(
                    page_content=summary,
                    metadata={
                        **document_meta,
                        "source": str(path),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                docs.append(document)

            # splitting the content:
            try:
                chunks = self._splitter.split_text(text)
                self.logger.info(f"Split document into {len(chunks)} chunks")
            except Exception as e:
                self.logger.error(
                    f"Failed to split text: {e}"
                )
                # Fallback: use the entire text as one chunk
                chunks = [text]
            for chunk in chunks:
                _idx = {
                    **document_meta
                }
                # Create a Langchain Document
                docs.append(
                    Document(
                        page_content=document_context + chunk,
                        metadata=_idx
                    )
                )
        return []
