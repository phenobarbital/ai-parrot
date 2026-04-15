"""Semantic text splitter that chunks by paragraph and sentence boundaries.

Uses token-based sizing via tiktoken. Preserves code blocks and tables
as atomic units. Never produces chunks below min_chunk_size tokens.
"""
import logging
import re
from typing import List, Optional, Tuple

from .base import BaseTextSplitter

logger = logging.getLogger(__name__)

# Sentence-ending pattern (CJK-aware)
DEFAULT_SENTENCE_ENDINGS = r'(?<=[.!?\u3002\uff01\uff1f])\s+'

# Code block pattern (fenced with ```)
CODE_BLOCK_PATTERN = re.compile(r'(```[^\n]*\n.*?```)', re.DOTALL)

# Table pattern: consecutive lines starting with |
TABLE_PATTERN = re.compile(
    r'((?:^[ \t]*\|.*\|[ \t]*$\n?){2,})',
    re.MULTILINE
)


class SemanticTextSplitter(BaseTextSplitter):
    """Paragraph-aware text splitter using token-based sizing.

    Splits on paragraph boundaries (\\n\\n), measures in tokens (tiktoken),
    merges small paragraphs, splits oversized ones at sentence boundaries.
    Never produces chunks below min_chunk_size tokens.

    Args:
        chunk_size: Maximum tokens per chunk.
        chunk_overlap: Number of tokens to overlap between chunks.
        min_chunk_size: Minimum tokens per chunk (merge undersized chunks).
        model_name: Tiktoken model name for tokenization.
        encoding_name: Specific tiktoken encoding name (overrides model_name).
        sentence_endings: Custom regex pattern for sentence boundaries.
        preserve_code_blocks: Keep code blocks (```) as atomic units.
        preserve_tables: Keep markdown tables as atomic units.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 30,
        model_name: str = "gpt-4",
        encoding_name: Optional[str] = None,
        sentence_endings: Optional[str] = None,
        preserve_code_blocks: bool = True,
        preserve_tables: bool = True,
        **kwargs
    ):
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
            **kwargs
        )
        self.model_name = model_name
        self.encoding_name = encoding_name
        self.preserve_code_blocks = preserve_code_blocks
        self.preserve_tables = preserve_tables
        self._sentence_pattern = re.compile(
            sentence_endings or DEFAULT_SENTENCE_ENDINGS
        )
        self._tiktoken_available = False
        self._enc = None
        self._init_tokenizer()

    def _init_tokenizer(self) -> None:
        """Initialize tiktoken tokenizer with graceful fallback."""
        try:
            import tiktoken
            if self.encoding_name:
                self._enc = tiktoken.get_encoding(self.encoding_name)
            else:
                self._enc = tiktoken.encoding_for_model(self.model_name)
            self._tiktoken_available = True
        except (ImportError, KeyError) as exc:
            logger.warning(
                "tiktoken not available (%s), falling back to word-based "
                "token estimation.",
                exc,
            )
            self._tiktoken_available = False

    # ------------------------------------------------------------------
    # Token counting
    # ------------------------------------------------------------------

    def _count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken, or fall back to word estimate.

        Args:
            text: Text to measure.

        Returns:
            Token count.
        """
        if not text:
            return 0
        if self._tiktoken_available and self._enc is not None:
            return len(self._enc.encode(text))
        # Fallback: word-based estimate
        return int(len(text.split()) * 1.3)

    # ------------------------------------------------------------------
    # Atomic block extraction
    # ------------------------------------------------------------------

    def _extract_atomic_blocks(
        self, text: str
    ) -> List[Tuple[str, bool]]:
        """Split text into segments, marking code blocks and tables as atomic.

        Returns a list of (text_segment, is_atomic) tuples in original order.

        Args:
            text: Input text.

        Returns:
            List of (segment, is_atomic) tuples.
        """
        # Collect all atomic block spans
        atomic_spans: List[Tuple[int, int, str]] = []

        if self.preserve_code_blocks:
            for m in CODE_BLOCK_PATTERN.finditer(text):
                atomic_spans.append((m.start(), m.end(), m.group()))

        if self.preserve_tables:
            for m in TABLE_PATTERN.finditer(text):
                # Avoid overlap with code blocks
                overlap = False
                for start, end, _ in atomic_spans:
                    if m.start() < end and m.end() > start:
                        overlap = True
                        break
                if not overlap:
                    atomic_spans.append((m.start(), m.end(), m.group()))

        # Sort by position
        atomic_spans.sort(key=lambda x: x[0])

        segments: List[Tuple[str, bool]] = []
        cursor = 0
        for start, end, block_text in atomic_spans:
            # Add text before this atomic block
            if cursor < start:
                before = text[cursor:start]
                if before.strip():
                    segments.append((before.strip(), False))
            segments.append((block_text.strip(), True))
            cursor = end

        # Add remaining text
        if cursor < len(text):
            remaining = text[cursor:]
            if remaining.strip():
                segments.append((remaining.strip(), False))

        if not segments and text.strip():
            segments.append((text.strip(), False))

        return segments

    # ------------------------------------------------------------------
    # Paragraph splitting
    # ------------------------------------------------------------------

    def _split_paragraphs(self, text: str) -> List[str]:
        """Split text on double newlines into paragraphs.

        Args:
            text: Text to split.

        Returns:
            List of paragraph strings.
        """
        paragraphs = [p.strip() for p in re.split(r'\n\n+', text)]
        return [p for p in paragraphs if p]

    # ------------------------------------------------------------------
    # Sentence splitting (for oversized paragraphs)
    # ------------------------------------------------------------------

    def _split_at_sentences(self, text: str) -> List[str]:
        """Split text at sentence boundaries, accumulating to chunk_size.

        If a single sentence exceeds chunk_size, falls back to token-level
        splitting.

        Args:
            text: Oversized paragraph text.

        Returns:
            List of sentence-grouped chunks.
        """
        sentences = self._sentence_pattern.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return [text] if text.strip() else []

        chunks: List[str] = []
        current_parts: List[str] = []
        current_tokens = 0

        for sentence in sentences:
            sent_tokens = self._count_tokens(sentence)

            # Single sentence exceeds chunk_size: token-level split
            if sent_tokens > self.chunk_size:
                # Flush current
                if current_parts:
                    chunks.append(" ".join(current_parts))
                    current_parts = []
                    current_tokens = 0
                # Token-level splitting
                chunks.extend(self._token_level_split(sentence))
                continue

            if current_tokens + sent_tokens > self.chunk_size and current_parts:
                chunks.append(" ".join(current_parts))
                current_parts = [sentence]
                current_tokens = sent_tokens
            else:
                current_parts.append(sentence)
                current_tokens += sent_tokens

        if current_parts:
            chunks.append(" ".join(current_parts))

        return chunks

    def _token_level_split(self, text: str) -> List[str]:
        """Fall back to raw token-level splitting for very long sentences.

        Args:
            text: Text that exceeds chunk_size as a single sentence.

        Returns:
            List of token-bounded chunks.
        """
        if self._tiktoken_available and self._enc is not None:
            tokens = self._enc.encode(text)
            chunks = []
            start = 0
            while start < len(tokens):
                end = min(start + self.chunk_size, len(tokens))
                chunk_text = self._enc.decode(tokens[start:end])
                chunks.append(chunk_text)
                if end >= len(tokens):
                    break
                start = end - self.chunk_overlap
                if start < 0:
                    start = 0
            return chunks
        else:
            # Word-level fallback
            words = text.split()
            # Approximate: chunk_size tokens ~ chunk_size / 1.3 words
            words_per_chunk = max(1, int(self.chunk_size / 1.3))
            chunks = []
            for i in range(0, len(words), words_per_chunk):
                chunk = " ".join(words[i:i + words_per_chunk])
                chunks.append(chunk)
            return chunks

    # ------------------------------------------------------------------
    # Overlap
    # ------------------------------------------------------------------

    def _apply_overlap(self, chunks: List[str]) -> List[str]:
        """Prepend overlap tokens from previous chunk to each subsequent chunk.

        Args:
            chunks: List of chunk strings.

        Returns:
            Chunks with overlap applied.
        """
        if self.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks

        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            # Get overlap portion from end of previous chunk
            if self._tiktoken_available and self._enc is not None:
                prev_tokens = self._enc.encode(prev)
                overlap_tokens = prev_tokens[-self.chunk_overlap:]
                overlap_text = self._enc.decode(overlap_tokens)
            else:
                prev_words = prev.split()
                # Approximate overlap words
                overlap_word_count = max(1, int(self.chunk_overlap / 1.3))
                overlap_text = " ".join(prev_words[-overlap_word_count:])

            result.append(overlap_text + "\n\n" + chunks[i])

        return result

    # ------------------------------------------------------------------
    # Main split_text
    # ------------------------------------------------------------------

    def split_text(self, text: str) -> List[str]:
        """Split text into semantically coherent chunks.

        Algorithm:
        1. Extract atomic blocks (code blocks, tables).
        2. Split remaining text into paragraphs.
        3. Measure tokens per paragraph.
        4. Merge small paragraphs until chunk_size is approached.
        5. Split oversized paragraphs at sentence boundaries.
        6. Enforce min_chunk_size by merging undersized trailing chunks.
        7. Apply overlap.

        Args:
            text: Input text to split.

        Returns:
            List of chunk strings.
        """
        if not text or not text.strip():
            return []

        # Step 1: Extract atomic blocks
        segments = self._extract_atomic_blocks(text)

        # Step 2-5: Build chunks from segments
        raw_chunks: List[str] = []
        current_parts: List[str] = []
        current_tokens = 0

        for segment_text, is_atomic in segments:
            if is_atomic:
                seg_tokens = self._count_tokens(segment_text)

                # If atomic block + current exceeds chunk_size, flush current first
                if current_tokens > 0 and current_tokens + seg_tokens > self.chunk_size:
                    raw_chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_tokens = 0

                # If atomic block alone exceeds chunk_size, it still stays intact
                if seg_tokens > self.chunk_size:
                    raw_chunks.append(segment_text)
                else:
                    current_parts.append(segment_text)
                    current_tokens += seg_tokens
            else:
                # Split into paragraphs
                paragraphs = self._split_paragraphs(segment_text)

                for para in paragraphs:
                    para_tokens = self._count_tokens(para)

                    # Oversized paragraph: sentence-level splitting
                    if para_tokens > self.chunk_size:
                        # Flush current
                        if current_parts:
                            raw_chunks.append("\n\n".join(current_parts))
                            current_parts = []
                            current_tokens = 0
                        sentence_chunks = self._split_at_sentences(para)
                        raw_chunks.extend(sentence_chunks)
                        continue

                    # Would exceed chunk_size? Flush current
                    if current_tokens + para_tokens > self.chunk_size and current_parts:
                        raw_chunks.append("\n\n".join(current_parts))
                        current_parts = [para]
                        current_tokens = para_tokens
                    else:
                        current_parts.append(para)
                        current_tokens += para_tokens

        # Flush remaining
        if current_parts:
            raw_chunks.append("\n\n".join(current_parts))

        # Step 6: Enforce min_chunk_size
        chunks = self._enforce_min_chunk_size(raw_chunks)

        # Step 7: Apply overlap
        if self.chunk_overlap > 0:
            chunks = self._apply_overlap(chunks)

        return chunks

    def _enforce_min_chunk_size(self, chunks: List[str]) -> List[str]:
        """Merge undersized chunks with their neighbors.

        Args:
            chunks: List of raw chunks.

        Returns:
            Chunks with min_chunk_size enforced.
        """
        if self.min_chunk_size <= 0 or not chunks:
            return chunks

        # Single chunk: always return it regardless of size
        if len(chunks) == 1:
            return chunks

        result = list(chunks)

        # Merge undersized last chunk with previous
        while len(result) >= 2:
            last_tokens = self._count_tokens(result[-1])
            if last_tokens < self.min_chunk_size:
                merged = result[-2] + "\n\n" + result[-1]
                result[-2] = merged
                result.pop()
            else:
                break

        # Merge undersized first chunk with next
        while len(result) >= 2:
            first_tokens = self._count_tokens(result[0])
            if first_tokens < self.min_chunk_size:
                merged = result[0] + "\n\n" + result[1]
                result[1] = merged
                result.pop(0)
            else:
                break

        return result
