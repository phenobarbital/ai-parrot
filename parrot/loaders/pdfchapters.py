from collections.abc import Callable
from typing import Any, Optional, List, Union
from pathlib import PurePath, Path
from io import StringIO
import fitz  # PyMuPDF
from langchain.docstore.document import Document
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter
)
from .basepdf import BasePDF


class PDFChapterLoader(BasePDF):
    """
    Preserving Chapter Structure from PDF files.
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
        # Which Font is used for titles (Chapter separation)
        self.title_font: list = kwargs.get('title_font', 'Calibri-Bold')
        if not text_splitter:
            self.text_splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
                self.tokenizer,
                chunk_size=2000,
                chunk_overlap=100,
                add_start_index=True,  # If `True`, includes chunk's start index in metadata
                strip_whitespace=True,  # strips whitespace from the start and end
                separators=["\n\n", "\n", "\r\n", "\r", "\f", "\v", "\x0b", "\x0c"],
            )

    def eval_title(self, title_font: str) -> bool:
        """
        Check if the font is a title font.

        Args:
            title_font (str): The font to check.

        Returns:
            bool: True if the font is a title font.
        """
        return 'Bold' in title_font or title_font == self.title_font

    def _load_pdf(self, path: PurePath, **kwargs):
        """
        Open a PDF file.

        Args:
            path (PurePath): The path to the PDF file.

        Returns:
            pdfplumber.PDF: The PDF object.
        """
        pdf = fitz.open(path)
        self.logger.info(f"Loading PDF file: {path}")
        chapters = []
        current_chapter_text = ''
        current_chapter_title = ''
        current_chapter_page = None
        chapter_titles = set()  # Keep track of unique chapter titles
        for page_num in range(len(pdf)):
            page = pdf.load_page(page_num)
            blocks = page.get_text("dict")["blocks"]
            page_number = page_num + 1
            metadata = {
                "url": '',
                "index": f"{path.name} #{page_number}",
                "source": f"{path.name} #{page_number}",
                "filename": path.name,
                "source_type": self._source_type,
                "type": "pdf",
                "question": "",
                "answer": "",
                "summary": '',
                "document_meta": {
                    "page_number": page_num,
                    # **pdf.metadata
                }
            }
            for b in blocks:
                if b['type'] == 0:  # Text block
                    block_text = ''
                    for line in b["lines"]:
                        for span in line["spans"]:
                            block_text += span['text']  # Accumulate text within the block

                    # Check if the block text is a title by examining the font
                    if any(self.eval_title(span['font']) for line in b["lines"] for span in line["spans"]):
                        title = block_text.strip()
                        if title not in chapter_titles:
                            # Save the current chapter if it's not empty and start a new one
                            if current_chapter_text.strip() and current_chapter_text.strip() != current_chapter_title.strip():
                                chapters.append({
                                    'chapter': current_chapter_title,
                                    'content': current_chapter_text.strip(),
                                    'page': current_chapter_page,
                                    'meta': metadata
                                })
                            current_chapter_title = f"**{title}**: "
                            current_chapter_page = page_num + 1
                            current_chapter_text = current_chapter_title
                            chapter_titles.add(title)
                        else:
                            # Continue appending to the existing chapter
                            current_chapter_text += block_text
                    else:
                        # Continue appending text to the current chapter
                        current_chapter_text += block_text

            # Add a newline after processing each block, if not a chapter title
            if not block_text.strip().startswith(current_chapter_title):
                current_chapter_text += "\n"

        # Save the last chapter if it exists and it's not just the title
        if current_chapter_text.strip() and current_chapter_text.strip() != current_chapter_title.strip():
            chapters.append({
                'chapter': current_chapter_title,
                'content': current_chapter_text.strip(),
                'page': current_chapter_page,
                'meta': metadata
            })
        documents = []
        for chapter in chapters:
            documents.append(Document(
                page_content=chapter['content'],
                metadata=chapter['meta']
            ))
        return documents
