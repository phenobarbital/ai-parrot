"""Rust-backed Markdown splitter (thin wrapper over semantic_text_splitter.MarkdownSplitter).

Respects fenced code blocks, headers, lists, and blockquotes natively.
"""
import logging, uuid  # noqa: E401
from typing import Any, Dict, List, Optional, Union
from semantic_text_splitter import MarkdownSplitter
from .base import BaseTextSplitter, TextChunk
from .semantic import _byte_to_char  # reuse offset helper

logger = logging.getLogger(__name__)


class MarkdownTextSplitter(BaseTextSplitter):
    """Markdown-aware splitter backed by the Rust crate. Never cuts inside
    fenced code blocks, headers, or list items. Pass ``tokenizer=`` for
    token-based capacity."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        strip_headers: bool = False,       # legacy — dropped
        return_each_line: bool = False,    # legacy — dropped
        min_chunk_size: int = 0,
        tokenizer: Optional[Union[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                         min_chunk_size=min_chunk_size, **kwargs)
        if tokenizer is None:
            self._rust = MarkdownSplitter(capacity=chunk_size, overlap=chunk_overlap)
            self._capacity_unit = "chars"
        elif isinstance(tokenizer, str):
            self._rust = MarkdownSplitter.from_tiktoken_model(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap)
            self._capacity_unit = "tokens"
        else:
            self._rust = MarkdownSplitter.from_huggingface_tokenizer(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap)
            self._capacity_unit = "tokens"

        logger.info("Using semantic-text-splitter (Rust, Markdown) chunk_size=%d capacity=%s overlap=%d",
                    chunk_size, self._capacity_unit, chunk_overlap)
        dropped = [name for name, val in (
            ("strip_headers", strip_headers),
            ("return_each_line", return_each_line),
        ) if val]
        if dropped:
            logger.warning("MarkdownTextSplitter ignored legacy kwargs: %s "
                           "(handled natively by the Rust splitter)", ", ".join(dropped))

    def split_text(self, text: str) -> List[str]:
        """Return chunk strings; never breaks inside fenced code blocks."""
        if not text:
            return []
        return list(self._rust.chunks(text))

    def create_chunks(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[TextChunk]:
        """Return TextChunk objects with char offsets and metadata."""
        if not text:
            return []
        pairs = list(self._rust.chunk_indices(text))
        total = len(pairs)
        chunks: List[TextChunk] = []
        for i, (off, chunk_text) in enumerate(pairs):
            start = _byte_to_char(text, off)
            end = start + len(chunk_text)
            meta: Dict[str, Any] = {
                **(metadata or {}),
                "chunk_index": i,
                "total_chunks": total,
                "splitter_type": self.__class__.__name__,
            }
            if self.add_start_index:
                meta["start_index"] = start
                meta["end_index"] = end
            chunks.append(TextChunk(
                text=chunk_text, start_position=start, end_position=end,
                token_count=self._count_tokens(chunk_text), metadata=meta,
                chunk_id=f"chunk_{i:04d}_{uuid.uuid4().hex[:8]}",
            ))
        return self._enforce_min_chunk_size(chunks)
