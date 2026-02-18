"""DocumentConverterLoader - Load documents via Docling into Document objects."""
import asyncio
import re
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Union

from ..stores.models import Document
from .abstract import AbstractLoader


class DocumentConverterLoader(AbstractLoader):
    """Load PDF, DOCX, and PPTX files using Docling and return Document objects.

    Converts documents to markdown internally, then builds ``Document`` objects
    using the same helpers as :class:`AbstractLoader`.

    Supports local paths and URLs — Docling handles both natively.
    """

    extensions: List[str] = ['.pdf', '.docx', '.pptx']

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        do_ocr: bool = False,
        use_tesseract: bool = False,
        do_table_structure: bool = True,
        do_cell_matching: bool = True,
        max_num_pages: int = 100,
        max_file_size: int = 20971520,
        artifacts_path: Optional[str] = None,
        use_sections: bool = False,
        min_section_length: int = 50,
        **kwargs,
    ):
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs,
        )

        self.doctype = 'docling'
        self._source_type = source_type

        # Docling-specific options
        self.do_ocr = do_ocr
        self.use_tesseract = use_tesseract
        self.do_table_structure = do_table_structure
        self.do_cell_matching = do_cell_matching
        self.max_num_pages = max_num_pages
        self.max_file_size = max_file_size
        self.artifacts_path = artifacts_path

        # Section splitting
        self.use_sections = use_sections
        self.min_section_length = min_section_length

        # Lazy converter
        self._converter = None

    def _get_converter(self):
        """Lazy-initialise the Docling DocumentConverter."""
        if self._converter is not None:
            return self._converter
        from ..interfaces.doc_converter import DocumentConverterInterface
        self._converter = DocumentConverterInterface(
            do_ocr=self.do_ocr,
            use_tesseract=self.use_tesseract,
            do_table_structure=self.do_table_structure,
            do_cell_matching=self.do_cell_matching,
            max_num_pages=self.max_num_pages,
            max_file_size=self.max_file_size,
            artifacts_path=self.artifacts_path,
        )
        return self._converter

    def _detect_document_type(self, path: PurePath) -> str:
        """Detect document type based on file extension."""
        suffix = path.suffix.lower() if isinstance(path, PurePath) else ''
        mapping = {
            '.pdf': 'pdf',
            '.docx': 'word',
            '.pptx': 'powerpoint',
        }
        return mapping.get(suffix, 'unknown')

    @staticmethod
    def _clean_content(text: str) -> str:
        """Strip excessive whitespace from converted markdown."""
        if not text:
            return ""
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        lines = [line.rstrip() for line in text.split('\n')]
        return '\n'.join(lines).strip()

    def _extract_title(self, md_text: str) -> Optional[str]:
        """Extract first H1/H2 title from markdown."""
        match = re.search(r'^#{1,2}\s+(.+)$', md_text, re.MULTILINE)
        return match.group(1).strip() if match else None

    def _extract_sections(self, md_text: str) -> List[Dict[str, Any]]:
        """Split markdown by headers into sections."""
        sections: List[Dict[str, Any]] = []
        lines = md_text.split('\n')
        current_section = None
        current_content: List[str] = []
        counter = 0

        for line in lines:
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
            if header_match:
                if current_section and current_content:
                    content = '\n'.join(current_content).strip()
                    if len(content) >= self.min_section_length:
                        current_section['content'] = content
                        sections.append(current_section)

                level = len(header_match.group(1))
                counter += 1
                current_section = {
                    'title': header_match.group(2).strip(),
                    'level': level,
                    'section_number': counter,
                }
                current_content = [line]
            else:
                if current_section is not None:
                    current_content.append(line)

        # Last section
        if current_section and current_content:
            content = '\n'.join(current_content).strip()
            if len(content) >= self.min_section_length:
                current_section['content'] = content
                sections.append(current_section)

        return sections

    async def _load(self, path: Union[str, PurePath], **kwargs) -> List[Document]:
        """Load a single file via Docling and return Document objects."""
        self.logger.info(f"Loading file with Docling: {path}")
        docs: List[Document] = []

        try:
            converter = self._get_converter()
            md_text = await converter.convert_to_markdown(path)

            if not md_text:
                self.logger.warning(f"No content extracted from {path}")
                return docs

            md_text = self._clean_content(md_text)

            # Determine doc type from path
            if isinstance(path, PurePath):
                doc_type = self._detect_document_type(path)
            else:
                doc_type = 'url'

            title = self._extract_title(md_text) or ''
            base_meta = {
                'filename': path.name if isinstance(path, PurePath) else str(path),
                'file_path': str(path),
                'document_type': doc_type,
                'title': title,
                'word_count': len(md_text.split()),
            }

            if self.use_sections:
                sections = self._extract_sections(md_text)
                self.logger.info(
                    f"Extracted {len(sections)} sections from {path}"
                )
                if sections:
                    for section in sections:
                        section_meta = {
                            **base_meta,
                            'section_title': section['title'],
                            'section_number': section['section_number'],
                            'header_level': section['level'],
                            'content_type': 'section',
                        }
                        meta = self.create_metadata(
                            path=path,
                            doctype='docling',
                            source_type='docling_section',
                            doc_metadata=section_meta,
                        )
                        docs.append(
                            self.create_document(
                                content=section['content'],
                                path=path,
                                metadata=meta,
                            )
                        )
                else:
                    self._append_full_document(docs, md_text, path, base_meta)
            else:
                self._append_full_document(docs, md_text, path, base_meta)

        except Exception as e:
            self.logger.error(f"Error processing {path} with Docling: {e}")
            raise

        return docs

    def _append_full_document(
        self,
        docs: List[Document],
        md_text: str,
        path: Union[str, PurePath],
        base_meta: Dict[str, Any],
    ) -> None:
        """Append a single whole-document Document."""
        doc_meta = {**base_meta, 'content_type': 'full_document'}
        meta = self.create_metadata(
            path=path,
            doctype='docling',
            source_type='docling_full',
            doc_metadata=doc_meta,
        )
        docs.append(
            self.create_document(
                content=md_text,
                path=path,
                metadata=meta,
            )
        )
