from collections.abc import Callable
from typing import List, Optional, Union
import re
from pathlib import Path, PurePath
from markitdown import MarkItDown
from ..stores.models import Document
from .abstract import AbstractLoader


class MarkdownLoader(AbstractLoader):
    """
    Universal Document Loader using MarkItDown library.

    Converts various document formats to markdown and returns Document objects.
    Supports:
    - PDF files
    - PowerPoint presentations (.pptx, .ppt)
    - Word documents (.docx, .doc)
    - Excel spreadsheets (.xlsx, .xls, .csv)
    - HTML files
    - Text-based formats (CSV, JSON, XML)
    - Images with OCR (if enabled)
    - Audio files (if enabled)
    """

    # Supported extensions based on MarkItDown capabilities
    extensions: List[str] = {
        '.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls',
        '.csv', '.html', '.htm', '.xml', '.json', '.txt', '.md',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff',  # Images (with OCR)
        '.mp3', '.wav', '.m4a', '.flac'  # Audio (with transcription)
    }

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        enable_plugins: bool = True,
        enable_ocr: bool = False,
        enable_audio: bool = False,
        use_chapters: bool = False,
        use_sections: bool = False,
        merge_consecutive_headers: bool = True,
        min_section_length: int = 50,
        **kwargs
    ):
        """
        Initialize the MarkdownLoader.

        Args:
            source: Path or list of paths to load from
            tokenizer: Tokenizer to use for text processing
            text_splitter: Text splitter to use
            source_type: Type of source ('file', 'url', etc.)
            enable_plugins: Enable MarkItDown plugins for enhanced processing
            enable_ocr: Enable OCR for image processing
            enable_audio: Enable audio transcription
            use_chapters: Split by chapters/major sections
            use_sections: Split by all sections
            merge_consecutive_headers: Merge consecutive headers with their content
            min_section_length: Minimum length for a section to be considered valid
            **kwargs: Additional arguments passed to AbstractLoader
        """
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )

        self.doctype = 'markdown'
        self._source_type = source_type
        self.enable_plugins = enable_plugins
        self.enable_ocr = enable_ocr
        self.enable_audio = enable_audio
        self.use_chapters = use_chapters
        self.use_sections = use_sections
        self.merge_consecutive_headers = merge_consecutive_headers
        self.min_section_length = min_section_length

        # Initialize MarkItDown
        self._setup_markitdown()

    def _setup_markitdown(self):
        """Initialize the MarkItDown converter with appropriate settings."""
        try:
            self.md_converter = MarkItDown(enable_plugins=self.enable_plugins)
            self.logger.info("MarkItDown converter initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize MarkItDown: {e}")
            raise

    def _detect_document_type(self, path: PurePath) -> str:
        """Detect the type of document based on file extension."""
        suffix = path.suffix.lower()

        type_mapping = {
            '.pdf': 'pdf',
            '.docx': 'word', '.doc': 'word',
            '.pptx': 'powerpoint', '.ppt': 'powerpoint',
            '.xlsx': 'excel', '.xls': 'excel',
            '.csv': 'csv',
            '.html': 'html', '.htm': 'html',
            '.xml': 'xml',
            '.json': 'json',
            '.txt': 'text', '.md': 'markdown',
            '.png': 'image', '.jpg': 'image', '.jpeg': 'image',
            '.gif': 'image', '.bmp': 'image', '.tiff': 'image',
            '.mp3': 'audio', '.wav': 'audio', '.m4a': 'audio', '.flac': 'audio'
        }

        return type_mapping.get(suffix, 'unknown')

    def _extract_sections_from_markdown(self, md_text: str) -> List[dict]:
        """
        Extract sections from markdown text based on headers.

        Args:
            md_text: Markdown text content

        Returns:
            List of section dictionaries with 'title', 'content', 'level', and 'section_number'
        """
        sections = []
        lines = md_text.split('\n')
        current_section = None
        current_content = []
        section_counter = 0

        for line in lines:
            # Check if line is a header
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())

            if header_match:
                # Save previous section if it exists
                if current_section and current_content:
                    content = '\n'.join(current_content).strip()
                    if len(content) >= self.min_section_length:
                        current_section['content'] = content
                        sections.append(current_section)

                # Start new section
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                section_counter += 1

                # Determine if this should be included based on settings
                include_section = False
                if self.use_chapters and level <= 2:  # H1 and H2 for chapters
                    include_section = True
                elif self.use_sections and level <= 4:  # H1-H4 for sections
                    include_section = True
                elif not self.use_chapters and not self.use_sections:
                    include_section = True  # Include all if no specific setting

                if include_section:
                    current_section = {
                        'title': title,
                        'level': level,
                        'section_number': section_counter,
                        'header_line': line
                    }
                    current_content = []

                    # Include the header in content if merging
                    if self.merge_consecutive_headers:
                        current_content.append(line)
                else:
                    current_section = None
                    current_content = []
            else:
                # Add line to current section content
                if current_section is not None:
                    current_content.append(line)

        # Handle the last section
        if current_section and current_content:
            content = '\n'.join(current_content).strip()
            if len(content) >= self.min_section_length:
                current_section['content'] = content
                sections.append(current_section)

        return sections

    def _clean_markdown_content(self, content: str) -> str:
        """
        Clean and normalize markdown content.

        Args:
            content: Raw markdown content

        Returns:
            Cleaned markdown content
        """
        if not content:
            return ""

        # Remove excessive blank lines
        content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)

        # Remove trailing whitespace from lines
        lines = [line.rstrip() for line in content.split('\n')]
        content = '\n'.join(lines)

        # Ensure proper spacing around headers
        content = re.sub(r'(^|\n)(#{1,6}\s+[^\n]+)(\n)', r'\1\n\2\n\n', content)

        return content.strip()

    def _extract_metadata_from_markdown(self, md_text: str, file_path: PurePath) -> dict:
        """
        Extract metadata from markdown content and file.

        Args:
            md_text: Markdown text content
            file_path: Path to the source file

        Returns:
            Dictionary containing extracted metadata
        """
        metadata = {}

        # Extract frontmatter if present
        frontmatter_match = re.match(r'^---\n(.*?)\n---\n', md_text, re.DOTALL)
        if frontmatter_match:
            try:
                import yaml
                frontmatter = yaml.safe_load(frontmatter_match.group(1))
                if isinstance(frontmatter, dict):
                    metadata.update(frontmatter)
            except (ImportError, yaml.YAMLError):
                self.logger.warning("Could not parse frontmatter metadata")

        # Extract title from first header if not in frontmatter
        if 'title' not in metadata:
            title_match = re.search(r'^#\s+(.+)$', md_text, re.MULTILINE)
            if title_match:
                metadata['title'] = title_match.group(1).strip()

        # Count various elements
        metadata.update({
            'word_count': len(md_text.split()),
            'header_count': len(re.findall(r'^#{1,6}\s+', md_text, re.MULTILINE)),
            'table_count': len(re.findall(r'^\|.*\|$', md_text, re.MULTILINE)),
            'code_block_count': len(re.findall(r'```', md_text)) // 2,
            'link_count': len(re.findall(r'\[.*?\]\(.*?\)', md_text)),
            'image_count': len(re.findall(r'!\[.*?\]\(.*?\)', md_text))
        })

        return metadata

    async def _load(self, path: PurePath, **kwargs) -> List[Document]:
        """
        Load a single file using MarkItDown and return Document objects.

        Args:
            path: Path to the file to load
            **kwargs: Additional arguments

        Returns:
            List of Document objects
        """
        self.logger.info(f"Loading file with MarkItDown: {path}")
        docs = []

        try:
            # Convert file to markdown using MarkItDown
            result = self.md_converter.convert(str(path))

            if not result or not result.text_content:
                self.logger.warning(f"No content extracted from {path}")
                return docs

            md_text = result.text_content
            md_text = self._clean_markdown_content(md_text)

            # Extract additional metadata
            doc_type = self._detect_document_type(path)
            extracted_metadata = self._extract_metadata_from_markdown(md_text, path)

            # Determine how to split the content
            if self.use_chapters or self.use_sections:
                # Split by sections/chapters
                sections = self._extract_sections_from_markdown(md_text)
                self.logger.info(f"Extracted {len(sections)} sections from {path}")

                if sections:
                    for section in sections:
                        section_type = "chapter" if self.use_chapters else "section"

                        document_meta = {
                            "filename": path.name,
                            "file_path": str(path),
                            "document_type": doc_type,
                            "section_title": section['title'],
                            "section_number": section['section_number'],
                            "header_level": section['level'],
                            "content_type": section_type,
                            "extracted_metadata": extracted_metadata,
                            **extracted_metadata
                        }

                        meta = self.create_metadata(
                            path=path,
                            doctype="markdown",
                            source_type=f"markitdown_{section_type}",
                            doc_metadata=document_meta,
                        )

                        docs.append(
                            self.create_document(
                                content=section['content'],
                                path=path,
                                metadata=meta
                            )
                        )
                else:
                    # No sections found, treat as single document
                    self.logger.info(f"No sections found in {path}, treating as single document")
                    self._create_single_document(docs, md_text, path, doc_type, extracted_metadata)
            else:
                # Return whole markdown as single document
                self._create_single_document(docs, md_text, path, doc_type, extracted_metadata)

            # Generate summary if enabled
            if self._summarization and docs:
                full_text = "\n\n".join([doc.page_content for doc in docs])
                summary = await self.summary_from_text(full_text)

                if summary:
                    summary_meta = self.create_metadata(
                        path=path,
                        doctype="markdown",
                        source_type="markitdown_summary",
                        doc_metadata={
                            "summary_for_sections": len(docs),
                            "document_type": doc_type,
                            **extracted_metadata
                        }
                    )

                    docs.append(
                        self.create_document(
                            content=f"SUMMARY:\n\n{summary}",
                            path=path,
                            metadata=summary_meta
                        )
                    )

        except Exception as e:
            self.logger.error(f"Error processing {path} with MarkItDown: {e}")
            # Could optionally fall back to reading as plain text
            raise

        return docs

    def _create_single_document(
        self,
        docs: List[Document],
        md_text: str,
        path: PurePath,
        doc_type: str,
        extracted_metadata: dict
    ):
        """Helper method to create a single document from markdown text."""
        document_meta = {
            "filename": path.name,
            "file_path": str(path),
            "document_type": doc_type,
            "content_type": "full_document",
            "extracted_metadata": extracted_metadata,
            **extracted_metadata
        }

        meta = self.create_metadata(
            path=path,
            doctype="markdown",
            source_type="markitdown_full",
            doc_metadata=document_meta,
        )

        docs.append(
            self.create_document(
                content=md_text,
                path=path,
                metadata=meta
            )
        )

    def get_supported_formats(self) -> dict:
        """
        Get information about supported file formats.

        Returns:
            Dictionary mapping format categories to file extensions
        """
        return {
            'documents': ['.pdf', '.docx', '.doc'],
            'presentations': ['.pptx', '.ppt'],
            'spreadsheets': ['.xlsx', '.xls', '.csv'],
            'web': ['.html', '.htm'],
            'data': ['.xml', '.json'],
            'text': ['.txt', '.md'],
            'images': ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'],
            'audio': ['.mp3', '.wav', '.m4a', '.flac']
        }

    def validate_file_support(self, path: Union[str, Path]) -> bool:
        """
        Check if a file is supported by MarkItDown.

        Args:
            path: File path to check

        Returns:
            True if file is supported, False otherwise
        """
        if isinstance(path, str):
            path = Path(path)

        return path.suffix.lower() in self.extensions

    async def convert_to_markdown(self, path: Union[str, Path]) -> str:
        """
        Convert a single file to markdown and return the content.

        Args:
            path: Path to file to convert

        Returns:
            Markdown content as string
        """
        try:
            result = self.md_converter.convert(str(path))
            return self._clean_markdown_content(result.text_content) if result else ""
        except Exception as e:
            self.logger.error(f"Error converting {path} to markdown: {e}")
            return ""
