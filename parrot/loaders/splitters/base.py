import re
import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple, Union, Callable
from dataclasses import dataclass
import tiktoken
from transformers import AutoTokenizer


@dataclass
class TextChunk:
    """Represents a chunk of text with metadata"""
    text: str
    start_position: int
    end_position: int
    token_count: int
    metadata: Dict[str, Any]
    chunk_id: Optional[str] = None


class BaseTextSplitter(ABC):
    """Base class for all text splitters"""

    def __init__(
        self,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        keep_separator: bool = True,
        add_start_index: bool = True
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.keep_separator = keep_separator
        self.add_start_index = add_start_index

    @abstractmethod
    def split_text(self, text: str) -> List[str]:
        """Split text into chunks"""
        pass

    def create_chunks(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]:
        """Create TextChunk objects with metadata"""
        text_chunks = self.split_text(text)
        chunks = []
        current_position = 0

        for i, chunk_text in enumerate(text_chunks):
            # Find the actual position in the original text
            start_pos = text.find(chunk_text, current_position)
            if start_pos == -1:
                start_pos = current_position

            end_pos = start_pos + len(chunk_text)

            chunk_metadata = {
                **(metadata or {}),
                'chunk_index': i,
                'total_chunks': len(text_chunks),
                'splitter_type': self.__class__.__name__
            }

            if self.add_start_index:
                chunk_metadata['start_index'] = start_pos
                chunk_metadata['end_index'] = end_pos

            chunk = TextChunk(
                text=chunk_text,
                start_position=start_pos,
                end_position=end_pos,
                token_count=self._count_tokens(chunk_text),
                metadata=chunk_metadata,
                chunk_id=f"chunk_{i:04d}_{uuid.uuid4().hex[:8]}"
            )

            chunks.append(chunk)
            current_position = start_pos + len(chunk_text) - self.chunk_overlap

        return chunks

    @abstractmethod
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        pass

    def _merge_splits(self, splits: List[str], separator: str) -> List[str]:
        """Merge splits with overlap handling"""
        if not splits:
            return []

        docs = []
        current_doc = []
        current_length = 0

        for split in splits:
            split_len = self._count_tokens(split)

            if current_length + split_len > self.chunk_size and current_doc:
                # Create document from current chunks
                doc = separator.join(current_doc)
                if doc:
                    docs.append(doc)

                # Start new document with overlap
                overlap_splits = self._get_overlap_splits(current_doc, separator)
                current_doc = overlap_splits + [split]
                current_length = sum(self._count_tokens(s) for s in current_doc)
            else:
                current_doc.append(split)
                current_length += split_len

        # Add final document
        if current_doc:
            doc = separator.join(current_doc)
            if doc:
                docs.append(doc)

        return docs

    def _get_overlap_splits(self, splits: List[str], separator: str) -> List[str]:
        """Get splits for overlap"""
        if not splits or self.chunk_overlap == 0:
            return []

        overlap_splits = []
        overlap_length = 0

        # Start from the end and work backwards
        for split in reversed(splits):
            split_len = self._count_tokens(split)
            if overlap_length + split_len <= self.chunk_overlap:
                overlap_splits.insert(0, split)
                overlap_length += split_len
            else:
                break

        return overlap_splits
