from typing import List, Dict, Any
import re
from .base import BaseTextSplitter


class MarkdownTextSplitter(BaseTextSplitter):
    """
    Text splitter that respects Markdown structure.

    Features:
    - Splits at markdown headers (maintaining hierarchy)
    - Preserves code blocks
    - Maintains lists and formatting
    - Respects table structures
    """

    def __init__(
        self,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        strip_headers: bool = False,
        return_each_line: bool = False,
        **kwargs
    ):
        """
        Initialize MarkdownTextSplitter.

        Args:
            chunk_size: Maximum size per chunk (in characters)
            chunk_overlap: Overlap between chunks
            strip_headers: Whether to strip headers from chunks
            return_each_line: Whether to return each line as a separate chunk
        """
        super().__init__(chunk_size, chunk_overlap, **kwargs)
        self.strip_headers = strip_headers
        self.return_each_line = return_each_line

        # Markdown parsing patterns
        self.header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        self.code_block_pattern = re.compile(r'```.*?```', re.DOTALL)
        self.list_pattern = re.compile(r'^[\s]*[-*+]\s+', re.MULTILINE)
        self.table_pattern = re.compile(r'^[\s]*\|.*\|[\s]*$', re.MULTILINE)

    def _count_tokens(self, text: str) -> int:
        """Count tokens (approximation using words for markdown)"""
        # Simple word-based counting for markdown
        words = len(text.split())
        return int(words * 1.3)  # Rough token approximation

    def split_text(self, text: str) -> List[str]:
        """Split markdown text respecting structure"""
        if not text:
            return []

        if self.return_each_line:
            return [line for line in text.split('\n') if line.strip()]

        # First, identify markdown sections
        sections = self._parse_markdown_sections(text)

        # Then merge sections respecting chunk size
        chunks = self._merge_markdown_sections(sections)

        return chunks

    def _parse_markdown_sections(self, text: str) -> List[Dict[str, Any]]:
        """Parse markdown into hierarchical sections"""
        lines = text.split('\n')
        sections = []
        current_section = {
            'type': 'content',
            'level': 0,
            'header': '',
            'content': [],
            'start_line': 0
        }

        in_code_block = False
        code_block_lang = ''

        for i, line in enumerate(lines):
            # Handle code blocks
            if line.strip().startswith('```'):
                if not in_code_block:
                    # Starting code block
                    in_code_block = True
                    code_block_lang = line.strip()[3:]
                    if current_section['content']:
                        sections.append(current_section)
                    current_section = {
                        'type': 'code_block',
                        'level': 0,
                        'header': f'Code ({code_block_lang})',
                        'content': [line],
                        'start_line': i
                    }
                else:
                    # Ending code block
                    current_section['content'].append(line)
                    sections.append(current_section)
                    in_code_block = False
                    current_section = {
                        'type': 'content',
                        'level': 0,
                        'header': '',
                        'content': [],
                        'start_line': i + 1
                    }
                continue

            if in_code_block:
                current_section['content'].append(line)
                continue

            # Handle headers
            header_match = self.header_pattern.match(line)
            if header_match:
                # Save current section if it has content
                if current_section['content']:
                    sections.append(current_section)

                # Start new section
                level = len(header_match.group(1))
                header_text = header_match.group(2).strip()

                current_section = {
                    'type': 'section',
                    'level': level,
                    'header': header_text,
                    'content': [] if self.strip_headers else [line],
                    'start_line': i
                }
            else:
                current_section['content'].append(line)

        # Add final section
        if current_section['content']:
            sections.append(current_section)

        return sections

    def _merge_markdown_sections(self, sections: List[Dict[str, Any]]) -> List[str]:
        """Merge sections respecting chunk size limits"""
        if not sections:
            return []

        chunks = []
        current_chunk_parts = []
        current_size = 0

        for section in sections:
            section_text = '\n'.join(section['content'])
            section_size = len(section_text)

            # If section alone exceeds chunk size, split it
            if section_size > self.chunk_size:
                # Save current chunk if exists
                if current_chunk_parts:
                    chunks.append('\n\n'.join(current_chunk_parts))
                    current_chunk_parts = []
                    current_size = 0

                # Split large section
                split_sections = self._split_large_section(section_text)
                chunks.extend(split_sections)
                continue

            # Check if adding this section exceeds chunk size
            if current_size + section_size > self.chunk_size and current_chunk_parts:
                # Save current chunk
                chunks.append('\n\n'.join(current_chunk_parts))

                # Start new chunk with overlap
                overlap_parts = self._get_overlap_content(current_chunk_parts)
                current_chunk_parts = overlap_parts + [section_text]
                current_size = sum(len(part) for part in current_chunk_parts)
            else:
                current_chunk_parts.append(section_text)
                current_size += section_size

        # Add final chunk
        if current_chunk_parts:
            chunks.append('\n\n'.join(current_chunk_parts))

        return [chunk for chunk in chunks if chunk.strip()]

    def _split_large_section(self, text: str) -> List[str]:
        """Split a large section that exceeds chunk size"""
        # For very large sections, fall back to paragraph-based splitting
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        chunks = []
        current_chunk = []
        current_size = 0

        for paragraph in paragraphs:
            para_size = len(paragraph)

            if current_size + para_size > self.chunk_size and current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [paragraph]
                current_size = para_size
            else:
                current_chunk.append(paragraph)
                current_size += para_size

        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks

    def _get_overlap_content(self, parts: List[str]) -> List[str]:
        """Get content for overlap between chunks"""
        if not parts or self.chunk_overlap == 0:
            return []

        # Take last parts that fit in overlap size
        overlap_parts = []
        overlap_size = 0

        for part in reversed(parts):
            if overlap_size + len(part) <= self.chunk_overlap:
                overlap_parts.insert(0, part)
                overlap_size += len(part)
            else:
                break

        return overlap_parts
