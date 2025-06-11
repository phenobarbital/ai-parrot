from typing import List, Optional
from pathlib import PurePath
import fitz
from langchain.docstore.document import Document
from .abstract import AbstractLoader


class PDFLoader(AbstractLoader):
    """
    Advanced PDF Loader using PyMuPDF (fitz).
    - Skips image-only pages.
    - Combines title-only pages with next content page.
    - Preserves tables as text for chatbot/RAG KB usage.
    - Returns a LangChain Document per logical page.
    """

    extensions: List[str] = ['.pdf']

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

    async def _load(self, path: PurePath, **kwargs) -> List[Document]:
        self.logger.info(f"Loading PDF file: {path}")
        docs = []
        all_text = []   # ← For summary collection
        doc = fitz.open(str(path))
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
                "title": doc.metadata.get("title", ""),
                "creationDate": doc.metadata.get("creationDate", ""),
                "author": doc.metadata.get("author", ""),
            }
            meta = self.create_metadata(
                path=path,
                doctype="pdf",
                source_type="pdf",
                doc_metadata=document_meta,
            )
            if len(content) < 10:
                self.logger.warning(f"Page {i+1} content too short, skipping.")
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
        summary = self.summary_from_text(full_text)
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
