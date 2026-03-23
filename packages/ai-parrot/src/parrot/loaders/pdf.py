from collections.abc import Callable
from typing import List, Optional, Union
import re
from pathlib import Path, PurePath
import fitz
import pymupdf4llm
from ..stores.models import Document
from .abstract import AbstractLoader

class PDFLoader(AbstractLoader):
    """
    Advanced PDF Loader using PyMuPDF (fitz).
    - Skips image-only pages.
    - Combines title-only pages with next content page.
    - Preserves tables as text for chatbot/RAG KB usage.
    - Returns a Parrot Document per logical page.
    - Supports chapter-based splitting for markdown output.
    """

    extensions: List[str] = {'.pdf'}

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
        self.doctype = 'pdf'
        self._source_type = source_type
        self.as_markdown = as_markdown
        self.use_chapters = use_chapters
        self.use_pages = use_pages

    def is_title_only(self, text: str, min_len: int = 5, max_len: int = 50) -> bool:
        """Check if text looks like a title (short, single line, large font)."""
        lines = [l for l in text.strip().split('\n') if l.strip()]
        if len(lines) == 1 and min_len <= len(lines[0]) <= max_len:
            return True
        return False

    def is_image_only(self, page: fitz.Page) -> bool:
        """Return True if the page only contains images (no visible text)."""
        text = page.get_text("text").strip()
        if text:
            return False
        # Has no text, check if images exist
        img_list = page.get_images(full=True)
        return len(img_list) > 0

    def is_table_like(self, text: str) -> bool:
        """Naive check: Table if lines have multiple columns (lots of |, tab, or spaces)."""
        lines = [l for l in text.split('\n') if l.strip()]
        if not lines:
            return False
        count_table_lines = sum(1 for l in lines if ('|' in l or '\t' in l or (len(l.split()) > 3)))
        return (count_table_lines > len(lines) // 2) and len(lines) > 2

    def extract_table(self, page: fitz.Page) -> Optional[str]:
        """Attempt to extract table structure, return as markdown if detected, else None."""
        # PyMuPDF can't extract structured tables, so fallback to plain text with basic cleanup
        text = page.get_text("text")
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        # Try to join lines with | if possible
        if not lines:
            return None
        # Heuristic: If tab separated or lots of spaces, format as a markdown table
        table_lines = []
        for l in lines:
            if '\t' in l:
                cells = [c.strip() for c in l.split('\t')]
                table_lines.append("| " + " | ".join(cells) + " |")
            elif '|' in l:
                table_lines.append(l)
            else:
                # Split by multiple spaces
                cells = [c.strip() for c in l.split("  ") if c.strip()]
                if len(cells) > 2:
                    table_lines.append("| " + " | ".join(cells) + " |")
                else:
                    table_lines.append(l)
        if table_lines:
            # Add markdown header if more than 2 columns
            if len(table_lines) > 1 and table_lines[0].count('|') == table_lines[1].count('|'):
                ncols = table_lines[0].count('|') - 1
                if ncols > 1:
                    header_sep = "| " + " | ".join(['---'] * ncols) + " |"
                    table_lines.insert(1, header_sep)
            return "\n".join(table_lines)
        return None

    def extract_chapters_from_markdown(self, md_text: str) -> List[dict]:
        """
        Extract chapters from markdown text based on headers.
        Returns list of dicts with 'title' and 'content' keys.
        """
        chapters = []

        # Split by horizontal rules and headers
        # Look for patterns like: -----\n**TITLE**\n or # Title

        # First, let's handle the horizontal rule + bold title pattern
        sections = re.split(r'\n-----+\n', md_text)

        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue

            # Look for bold titles at the beginning of sections
            title_match = re.match(r'^\*\*([^*]+)\*\*', section)
            if title_match:
                title = title_match.group(1).strip()
                # Get content after the title
                content = re.sub(r'^\*\*[^*]+\*\*\s*', '', section, count=1).strip()
            else:
                # Look for markdown headers (# ## ###)
                header_match = re.match(r'^(#{1,6})\s*(.+?)$', section, re.MULTILINE)
                if header_match:
                    title = header_match.group(2).strip()
                    # Get content after the header
                    content = re.sub(r'^#{1,6}\s*.+?$', '', section, count=1, flags=re.MULTILINE).strip()
                else:
                    # No clear title found, use section number or first line
                    lines = section.split('\n')
                    if lines:
                        title = f"Section {i+1}" if not lines[0].strip() else lines[0][:50] + "..."
                        content = section
                    else:
                        continue

            # Skip if content is too short (less than 10 characters)
            if len(content.strip()) < 10:
                self.logger.info(f"Skipping chapter '{title}' - content too short")
                continue

            chapters.append({
                'title': title,
                'content': content,
                'chapter_number': len(chapters) + 1
            })

        return chapters

    def extract_pages_from_markdown(self, md_text: str) -> List[dict]:
        """
        Extract pages from markdown text based on page separators.
        Returns list of dicts with 'title' and 'content' keys.
        """
        pages = []

        # Split by page indicators (common patterns)
        page_patterns = [
            r'\n-----+\n',  # Horizontal rules
            r'Slide \d+',   # Slide indicators
            r'Page \d+',    # Page indicators
        ]

        # Try to split by the most common pattern first
        sections = re.split(r'\n-----+\n', md_text)

        for i, section in enumerate(sections):
            section = section.strip()
            if not section or len(section) < 10:
                continue

            # Extract title from the beginning of the page
            lines = section.split('\n')
            title = None
            content_start = 0

            # Look for bold title or header at the beginning
            for j, line in enumerate(lines[:3]):  # Check first 3 lines
                line = line.strip()
                if re.match(r'^\*\*([^*]+)\*\*$', line):
                    title = re.match(r'^\*\*([^*]+)\*\*$', line).group(1)
                    content_start = j + 1
                    break
                elif re.match(r'^#{1,6}\s*(.+?)$', line):
                    title = re.match(r'^#{1,6}\s*(.+?)$', line).group(1)
                    content_start = j + 1
                    break

            if not title:
                title = f"Page {i+1}"

            # Get content after title
            content = '\n'.join(lines[content_start:]).strip()

            if len(content) < 10:
                continue

            pages.append({
                'title': title,
                'content': content,
                'page_number': i + 1
            })

        return pages

    async def _load(self, path: PurePath, **kwargs) -> List[Document]:
        self.logger.info(f"Loading PDF file: {path}")
        docs = []
        all_text = []   # ← For summary collection
        doc = fitz.open(str(path))
        if self.as_markdown:
            md_text = pymupdf4llm.to_markdown(path)
            if self.use_chapters:
                # Split by chapters
                chapters = self.extract_chapters_from_markdown(md_text)
                self.logger.info(f"Found {len(chapters)} chapters")
                for chapter in chapters:
                    document_meta = {
                        "filename": path.name,
                        "file_path": str(path),
                        "chapter_title": chapter['title'],
                        "chapter_number": chapter['chapter_number'],
                        "content_type": "chapter"
                    }
                    meta = self.create_metadata(
                        path=path,
                        doctype="pdf",
                        source_type="pdf_chapter",
                        doc_metadata=document_meta,
                    )
                    # Combine title and content
                    full_content = f"# {chapter['title']}\n\n{chapter['content']}"
                    docs.append(
                        self.create_document(
                            content=full_content,
                            path=path,
                            metadata=meta
                        )
                    )
            elif self.use_pages:
                # Split by pages
                pages = self.extract_pages_from_markdown(md_text)
                self.logger.info(f"Found {len(pages)} pages")

                for page in pages:
                    document_meta = {
                        "filename": path.name,
                        "file_path": str(path),
                        "page_title": page['title'],
                        "page_number": page['page_number'],
                        "content_type": "page"
                    }

                    meta = self.create_metadata(
                        path=path,
                        doctype="pdf",
                        source_type="pdf_page",
                        doc_metadata=document_meta,
                    )

                    # Combine title and content
                    full_content = f"## {page['title']}\n\n{page['content']}"

                    docs.append(
                        self.create_document(
                            content=full_content,
                            path=path,
                            metadata=meta
                        )
                    )
            else:
                # Return whole markdown as single document
                document_meta = {
                    "filename": path.name,
                    "file_path": str(path),
                    "content_type": "full_document"
                }
                meta = self.create_metadata(
                    path=path,
                    doctype="pdf",
                    source_type="pdf_markdown",
                    doc_metadata=document_meta,
                )
                docs.append(
                    self.create_document(
                        content=md_text,
                        path=path,
                        metadata=meta
                    )
                )
        else:
            # Use the default text extraction page-based
            pending_title = None
            for i, page in enumerate(doc):
                page_text = page.get_text("text").strip()
                if self.is_image_only(page):
                    self.logger.info(f"Page {i+1}: image-only, skipping.")
                    continue

                # Title-only page: store to prepend to next content
                if self.is_title_only(page_text):
                    self.logger.info(f"Page {i+1}: title-only, saving for next page.")
                    pending_title = page_text
                    continue

                # Table page: try to preserve structure
                if self.is_table_like(page_text):
                    table_md = self.extract_table(page)
                    if table_md:
                        content = (pending_title + '\n\n' if pending_title else '') + table_md
                        pending_title = None
                    else:
                        content = (pending_title + '\n\n' if pending_title else '') + page_text
                        pending_title = None
                else:
                    content = (pending_title + '\n\n' if pending_title else '') + page_text
                    pending_title = None

                document_meta = {
                    "filename": path.name,
                    "file_path": str(path),
                    "page_number": i + 1,
                    # "title": doc.metadata.get("title", ""),
                    # "creationDate": doc.metadata.get("creationDate", ""),
                    # "author": doc.metadata.get("author", ""),
                }
                meta = self.create_metadata(
                    path=path,
                    doctype="pdf",
                    source_type="pdf",
                    doc_metadata=document_meta,
                )
                if len(content) < 10:
                    self.logger.warning(
                        f"Page {i+1} content too short, skipping."
                    )
                    continue
                docs.append(
                    self.create_document(
                        content=content,
                        path=path,
                        metadata=meta
                    )
                )
                all_text.append(content)
            doc.close()
            # --- Summarization step ---
            full_text = "\n\n".join(all_text)
            summary = await self.summary_from_text(full_text)
            if summary:
                summary_meta = self.create_metadata(
                    path=path,
                    doctype=self.doctype,
                    source_type=self._source_type,
                    doc_metadata={
                        "summary_for_pages": len(docs),
                    }
                )
                docs.append(
                    self.create_document(
                        content=f"SUMMARY:\n\n{summary}",
                        path=path,
                        metadata=summary_meta
                    )
                )
        return docs
