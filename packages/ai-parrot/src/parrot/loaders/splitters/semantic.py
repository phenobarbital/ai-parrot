"""Rust-backed semantic text splitter (thin wrapper over TextSplitter from semantic_text_splitter)."""
import logging, uuid  # noqa: E401
from typing import Any, Dict, List, Optional, Union
from semantic_text_splitter import TextSplitter
from .base import BaseTextSplitter, TextChunk

logger = logging.getLogger(__name__)


def _byte_to_char(text: str, byte_offset: int) -> int:
    """Convert a UTF-8 byte offset to a char offset (forward-compat shim)."""
    if byte_offset <= 0:
        return 0
    if byte_offset <= len(text):          # v0.30.x: already a char offset
        return byte_offset
    encoded = text.encode("utf-8")
    if byte_offset >= len(encoded):
        return len(text)
    return len(encoded[:byte_offset].decode("utf-8", errors="ignore"))


class SemanticTextSplitter(BaseTextSplitter):
    """Sentence/paragraph-aware splitter backed by the Rust crate. Never
    produces mid-word cuts. Pass ``tokenizer=`` for token-based capacity."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 30,
        model_name: str = "gpt-4",              # legacy — dropped
        encoding_name: Optional[str] = None,    # legacy — dropped
        sentence_endings: Optional[str] = None, # legacy — dropped
        preserve_code_blocks: bool = True,      # legacy — dropped
        preserve_tables: bool = True,           # legacy — dropped
        tokenizer: Optional[Union[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                         min_chunk_size=min_chunk_size, **kwargs)
        if tokenizer is None:
            self._rust = TextSplitter(capacity=chunk_size, overlap=chunk_overlap)
            self._capacity_unit = "chars"
        elif isinstance(tokenizer, str):
            self._rust = TextSplitter.from_tiktoken_model(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap)
            self._capacity_unit = "tokens"
        else:
            self._rust = TextSplitter.from_huggingface_tokenizer(
                tokenizer, capacity=chunk_size, overlap=chunk_overlap)
            self._capacity_unit = "tokens"

        logger.info("Using semantic-text-splitter (Rust) chunk_size=%d capacity=%s overlap=%d",
                    chunk_size, self._capacity_unit, chunk_overlap)
        dropped = [name for name, val, dflt in (
            ("encoding_name", encoding_name, None),
            ("sentence_endings", sentence_endings, None),
            ("preserve_code_blocks", preserve_code_blocks, True),
            ("preserve_tables", preserve_tables, True),
        ) if val != dflt]
        if dropped:
            logger.warning("SemanticTextSplitter ignored legacy kwargs: %s "
                           "(handled natively by the Rust splitter)", ", ".join(dropped))

    def split_text(self, text: str) -> List[str]:
        """Return chunk strings; never produces mid-word cuts."""
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
