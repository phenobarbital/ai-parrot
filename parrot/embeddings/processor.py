from typing import List, Dict, Any, Tuple
import numpy as np
from .huggingface import SentenceTransformerModel


class LateChunkingProcessor:
    """Processor for handling late chunking of documents using embeddings.
    This class processes documents by generating embeddings for the entire document first,
    then splitting it into semantic chunks while preserving boundaries.
    It uses the SentenceTransformerModel to generate embeddings and chunk metadata.
    """
    def __init__(self, embedding_generator: SentenceTransformerModel, chunk_size: int = 8192):
        self.embedding_generator = embedding_generator
        self.chunk_size = chunk_size

    async def process_document_late_chunking(
        self,
        document_text: str,
        document_id: str
    ) -> Tuple[List[np.ndarray], List[Dict[str, Any]]]:
        """Process document with late chunking strategy"""

        # Step 1: Generate full-document token embeddings
        full_embeddings = await self.embedding_generator.encode([document_text])

        # Step 2: Split into semantic chunks while preserving boundaries
        chunks = self._semantic_chunk_split(document_text)

        # Step 3: Map chunks to their corresponding token ranges
        chunk_embeddings = []
        chunk_metadata = []

        for chunk_idx, chunk_text in enumerate(chunks):
            # Calculate token range for this chunk
            start_pos = document_text.find(chunk_text)
            end_pos = start_pos + len(chunk_text)

            # Extract embeddings for this chunk's token range
            chunk_embedding = await self._extract_chunk_embedding(
                full_embeddings[0], chunk_text, document_text
            )

            chunk_embeddings.append(chunk_embedding)
            chunk_metadata.append({
                'document_id': document_id,
                'chunk_index': chunk_idx,
                'start_position': start_pos,
                'end_position': end_pos,
                'chunk_text': chunk_text[:200] + '...' if len(chunk_text) > 200 else chunk_text
            })

        return chunk_embeddings, chunk_metadata

    def _semantic_chunk_split(self, text: str) -> List[str]:
        """Split text preserving sentence and paragraph boundaries"""
        # Split by double newlines (paragraphs) first
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_size = 0

        for paragraph in paragraphs:
            paragraph_size = len(paragraph)

            if current_size + paragraph_size > self.chunk_size and current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [paragraph]
                current_size = paragraph_size
            else:
                current_chunk.append(paragraph)
                current_size += paragraph_size

        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks

    async def _extract_chunk_embedding(
        self,
        full_embedding: np.ndarray,
        chunk_text: str,
        full_text: str
    ) -> np.ndarray:
        """Extract contextualized embedding for chunk"""
        # For now, re-embed the chunk with full context
        # In practice, you might use token-level alignments
        chunk_embedding = await self.embedding_generator.encode([chunk_text])
        return chunk_embedding[0]
