from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import logging
import re
import uuid

import numpy as np

from parrot.stores.models import Document


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
        self.logger = logging.getLogger(__name__)

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
        full_embedding = await self.vector_store._embed_.embed_query(document_text)

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
            chunk_embedding = await self.vector_store._embed_.embed_query(contextual_text)

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

    # -----------------------------------------------------------------------
    # FEAT-128: 3-level hierarchy support
    # -----------------------------------------------------------------------

    def _count_tokens(self, text: str) -> int:
        """Approximate token count.

        The existing chunking infrastructure uses character counts as its
        "token" unit (``chunk_size`` defaults to 8192 characters).  We
        keep the same convention here so threshold comparisons are
        consistent across the codebase.

        Args:
            text: The text whose length to estimate.

        Returns:
            Approximate number of tokens (characters in this implementation).
        """
        return len(text)

    def _split_to_parent_chunks(
        self,
        text: str,
        parent_chunk_size: int,
        parent_chunk_overlap: int,
    ) -> List[str]:
        """Split text into parent-chunk sized segments with overlap.

        Uses a sliding window with sentence-boundary snapping to avoid
        cutting sentences mid-way.  The parameters are in the same unit as
        ``chunk_size`` (characters).

        This method is simpler and more direct than
        :meth:`_sentence_aware_chunking` because parent chunks are larger
        windows and we want to guarantee at least ``ceil(len(text) /
        parent_chunk_size)`` chunks.

        Args:
            text: Full document text to split.
            parent_chunk_size: Target size of each parent chunk in characters.
            parent_chunk_overlap: Overlap between adjacent parent chunks in
                characters.  Must be less than ``parent_chunk_size``.

        Returns:
            List of parent-chunk text strings (non-empty).
        """
        text_len = len(text)
        if text_len == 0:
            return []

        chunks: List[str] = []
        start = 0

        while start < text_len:
            end = min(start + parent_chunk_size, text_len)

            # Snap to a sentence boundary near `end` to avoid mid-sentence cuts.
            if end < text_len:
                # Search backwards from `end` for a sentence-ending sequence.
                snap_pos = -1
                for pattern in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
                    p = text.rfind(pattern, start + parent_chunk_size // 2, end)
                    if p != -1 and p > snap_pos:
                        snap_pos = p + len(pattern)
                if snap_pos != -1:
                    end = snap_pos

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Advance with overlap (ensure forward progress).
            next_start = end - parent_chunk_overlap
            if next_start <= start:
                next_start = start + 1  # prevent infinite loop on very small text
            start = next_start

            if start >= text_len:
                break

        return chunks if chunks else [text]

    async def process_document_three_level(
        self,
        document_text: str,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        parent_chunk_size_tokens: int = 4000,
        parent_chunk_overlap_tokens: int = 200,
    ) -> Tuple[List[Document], List[ChunkInfo]]:
        """Split an oversized document into the 3-level hierarchy.

        Architecture:
        - Level 1: original document (NOT stored as a parent row)
        - Level 2: parent_chunks (~``parent_chunk_size_tokens`` chars each)
        - Level 3: child chunks (via existing late-chunking per parent_chunk)

        Each child's ``parent_document_id`` points to its **parent_chunk**
        UUID, NOT to the original document.  The original document is never
        returned as a parent (it is too large for the LLM context).

        Args:
            document_text: Full document text.
            document_id: Original document ID (stored as
                ``source_document_id`` on parent_chunks for audit).
            metadata: Optional base metadata inherited by parent_chunks.
            parent_chunk_size_tokens: Target parent chunk size in characters
                (the "token" unit in this code base is characters).
            parent_chunk_overlap_tokens: Overlap between adjacent parent
                chunks in characters.  Must be < ``parent_chunk_size_tokens``.

        Returns:
            Tuple of (parent_chunk_documents, child_chunk_infos) where:
            - parent_chunk_documents: list of :class:`Document` objects with
              ``metadata['document_type'] == 'parent_chunk'``,
              ``metadata['is_chunk'] == False``,
              ``metadata['source_document_id'] == document_id``.
            - child_chunk_infos: list of :class:`ChunkInfo` whose
              ``parent_document_id`` points to a parent_chunk UUID.

        Raises:
            ValueError: If ``parent_chunk_overlap_tokens >= parent_chunk_size_tokens``.
        """
        if parent_chunk_overlap_tokens >= parent_chunk_size_tokens:
            raise ValueError(
                f"parent_chunk_overlap_tokens ({parent_chunk_overlap_tokens}) "
                f"must be less than parent_chunk_size_tokens ({parent_chunk_size_tokens})."
            )

        base_meta = metadata or {}
        parent_chunk_texts = self._split_to_parent_chunks(
            text=document_text,
            parent_chunk_size=parent_chunk_size_tokens,
            parent_chunk_overlap=parent_chunk_overlap_tokens,
        )

        parent_chunk_documents: List[Document] = []
        all_children: List[ChunkInfo] = []

        for i, parent_text in enumerate(parent_chunk_texts):
            parent_chunk_id = str(uuid.uuid4())

            parent_doc = Document(
                page_content=parent_text,
                metadata={
                    **base_meta,
                    'document_id': parent_chunk_id,
                    'document_type': 'parent_chunk',
                    'is_chunk': False,
                    'source_document_id': document_id,
                    'parent_chunk_index': i,
                },
            )
            parent_chunk_documents.append(parent_doc)

            # Run late chunking on each parent_chunk to produce child chunks.
            # The children's parent_document_id will be set to parent_chunk_id.
            _, children = await self.process_document_late_chunking(
                document_text=parent_text,
                document_id=parent_chunk_id,
                metadata={
                    **base_meta,
                    'parent_chunk_index': i,
                    'source_document_id': document_id,
                },
            )
            all_children.extend(children)

        self.logger.info(
            "3-level hierarchy: document_id=%s split into %d parent_chunks "
            "(avg %.0f chars each), %d child chunks total.",
            document_id,
            len(parent_chunk_documents),
            len(document_text) / max(len(parent_chunk_documents), 1),
            len(all_children),
        )

        return parent_chunk_documents, all_children

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
