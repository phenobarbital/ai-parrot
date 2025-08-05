from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import re
import numpy as np


@dataclass
class ChunkInfo:
    """Information about a document chunk"""
    chunk_id: str
    parent_document_id: str
    chunk_index: int
    chunk_text: str
    start_position: int
    end_position: int
    chunk_embedding: np.ndarray
    metadata: Dict[str, Any]


class LateChunkingProcessor:
    """
    Late Chunking processor integrated with PgVectorStore.

    Late chunking generates embeddings for the full document first, then creates
    contextually-aware chunk embeddings that preserve the global document context.
    """

    def __init__(
        self,
        vector_store,
        chunk_size: int = 8192,
        chunk_overlap: int = 200,
        preserve_sentences: bool = True,
        min_chunk_size: int = 100
    ):
        self.vector_store = vector_store
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.preserve_sentences = preserve_sentences
        self.min_chunk_size = min_chunk_size

    async def process_document_late_chunking(
        self,
        document_text: str,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[np.ndarray, List[ChunkInfo]]:
        """
        Process document with late chunking strategy.

        Args:
            document_text: Full document text
            document_id: Unique document identifier
            metadata: Optional metadata for the document

        Returns:
            Tuple of (full_document_embedding, list_of_chunk_info)
        """
        # Step 1: Generate full-document embedding for global context
        full_embedding = self.vector_store._embed_.embed_query(document_text)

        # Step 2: Split into semantic chunks
        chunks = self._semantic_chunk_split(document_text)

        # Step 3: Generate contextual embeddings for each chunk
        chunk_infos = []

        for chunk_idx, (chunk_text, start_pos, end_pos) in enumerate(chunks):
            # Create contextual prompt that includes document context
            contextual_text = self._create_contextual_text(
                document_text, chunk_text, start_pos, end_pos
            )

            # Generate embedding with context
            chunk_embedding = self.vector_store._embed_.embed_query(contextual_text)

            # Create chunk ID
            chunk_id = f"{document_id}_chunk_{chunk_idx:04d}"

            # Prepare chunk metadata
            chunk_metadata = {
                **(metadata or {}),
                'parent_document_id': document_id,
                'chunk_index': chunk_idx,
                'total_chunks': len(chunks),
                'start_position': start_pos,
                'end_position': end_pos,
                'chunk_size': len(chunk_text),
                'is_chunk': True,
                'chunk_type': 'late_chunking',
                'context_preserved': True
            }

            chunk_info = ChunkInfo(
                chunk_id=chunk_id,
                parent_document_id=document_id,
                chunk_index=chunk_idx,
                chunk_text=chunk_text,
                start_position=start_pos,
                end_position=end_pos,
                chunk_embedding=chunk_embedding,
                metadata=chunk_metadata
            )

            chunk_infos.append(chunk_info)

        return np.array(full_embedding), chunk_infos

    def _semantic_chunk_split(self, text: str) -> List[Tuple[str, int, int]]:
        """
        Split text preserving semantic boundaries.

        Returns:
            List of (chunk_text, start_position, end_position) tuples
        """
        if self.preserve_sentences:
            return self._sentence_aware_chunking(text)
        else:
            return self._simple_chunking(text)

    def _sentence_aware_chunking(self, text: str) -> List[Tuple[str, int, int]]:
        """Split text while preserving sentence boundaries."""
        # Split by sentences (basic approach - could use spaCy for better results)
        sentence_endings = re.finditer(r'[.!?]+\s+', text)
        sentence_positions = [0] + [m.end() for m in sentence_endings] + [len(text)]

        chunks = []
        current_start = 0

        for i in range(1, len(sentence_positions)):
            current_end = sentence_positions[i]
            current_size = current_end - current_start

            # If current chunk is too large, create chunk at previous boundary
            if current_size > self.chunk_size and len(chunks) > 0:
                # Find the last good break point
                prev_end = sentence_positions[i-1]
                if prev_end - current_start >= self.min_chunk_size:
                    chunk_text = text[current_start:prev_end].strip()
                    chunks.append((chunk_text, current_start, prev_end))

                    # Start new chunk with overlap
                    overlap_start = max(current_start, prev_end - self.chunk_overlap)
                    current_start = overlap_start

            # If we're at the end, add final chunk
            if i == len(sentence_positions) - 1:
                chunk_text = text[current_start:current_end].strip()
                if len(chunk_text) >= self.min_chunk_size:
                    chunks.append((chunk_text, current_start, current_end))

        return chunks if chunks else [(text, 0, len(text))]

    def _simple_chunking(self, text: str) -> List[Tuple[str, int, int]]:
        """Simple character-based chunking with overlap."""
        chunks = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end].strip()

            if len(chunk_text) >= self.min_chunk_size:
                chunks.append((chunk_text, start, end))

            # Move start position with overlap
            start += self.chunk_size - self.chunk_overlap

            if end == len(text):
                break

        return chunks

    def _create_contextual_text(
        self,
        full_text: str,
        chunk_text: str,
        start_pos: int,
        end_pos: int
    ) -> str:
        """
        Create contextual text that includes surrounding context for better embeddings.
        """
        # Get surrounding context (e.g., 200 chars before and after)
        context_window = 200

        context_start = max(0, start_pos - context_window)
        context_end = min(len(full_text), end_pos + context_window)

        # Extract context
        before_context = full_text[context_start:start_pos] if context_start < start_pos else ""
        after_context = full_text[end_pos:context_end] if end_pos < context_end else ""

        # Create contextual text with clear boundaries
        contextual_text = f"{before_context.strip()} [FOCUS] {chunk_text} [/FOCUS] {after_context.strip()}"  # noqa

        return contextual_text.strip()
