"""
LocalKB: Knowledge Base from local text and markdown files with FAISS vector store.
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import re
from pathlib import Path
import asyncio
import time
from navconfig.logging import logging
from .abstract import AbstractKnowledgeBase
from ..faiss_store import FAISSStore
from ..models import Document
from ...utils.helpers import RequestContext


class LocalKB(AbstractKnowledgeBase):
    """
    Local Knowledge Base that loads markdown and text documents from a local directory.

    Uses FAISS for semantic search with disk persistence for fast loading.
    Ideal for agent-specific knowledge like:
    - Database query patterns
    - Tool usage examples
    - Domain-specific procedures
    - Analysis templates

    Example structure:
        AGENTS_DIR/
        └── my_agent/
            └── kb/
                ├── database_queries.md
                ├── prophet_forecast.md
                └── tool_examples.md
    """

    def __init__(
        self,
        name: str,
        kb_directory: Path,
        category: str = "local",
        description: str = None,
        activation_patterns: List[str] = None,
        embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
        dimension: int = 384,
        chunk_size: int = 4096,
        chunk_overlap: int = 100,
        always_active: bool = True,
        auto_load: bool = True,
        **kwargs
    ):
        """
        Initialize LocalKB.

        Args:
            name: Name of the KB (e.g., agent name)
            kb_directory: Path to directory containing .md and .txt files
            category: Category identifier
            description: KB description
            activation_patterns: Patterns that activate this KB
            embedding_model: Model for embeddings
            dimension: Embedding dimension
            chunk_size: Size of text chunks
            chunk_overlap: Overlap between chunks
            always_active: Always include in context
            auto_load: Load on initialization
        """
        super().__init__(
            name=name,
            category=category,
            description=description or f"{name} local knowledge base",
            activation_patterns=activation_patterns or [],
            always_active=always_active,
            priority=10  # High priority for local KB
        )

        self.kb_directory = Path(kb_directory)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.dimension = dimension
        self.logger = logging.getLogger(__name__)

        # FAISS store with persistence
        self.faiss_store = FAISSStore(
            collection_name=f"{name}_local_kb",
            embedding_model=embedding_model,
            distance_strategy="COSINE",
            index_type="HNSW",  # Use HNSW for large KBs
        )

        # Cache file for persistence
        self.cache_file = self.kb_directory / ".kb_cache.faiss"

        # Track loaded files for change detection
        self._loaded_files: Dict[str, float] = {}  # filename -> mtime
        self._is_loaded = False

        if auto_load:
            # Load synchronously during init
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule for later if loop is running
                    asyncio.create_task(self.load_documents())
                else:
                    # Run immediately if no loop
                    loop.run_until_complete(self.load_documents())
            except RuntimeError:
                # No loop available, will load on first search
                pass

    async def should_activate(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, float]:
        """
        Determine if KB should activate.
        For local KB, usually always active.
        """
        if self.always_active:
            return True, 1.0

        # Check activation patterns
        query_lower = query.lower()
        for pattern in self.activation_patterns:
            if pattern.lower() in query_lower:
                return True, 0.9

        return False, 0.0

    async def load_documents(self, force_reload: bool = False) -> int:
        """
        Load markdown documents from kb_directory into FAISS.

        Args:
            force_reload: Force reload even if cache exists

        Returns:
            Number of documents loaded
        """
        # Create kb directory if doesn't exist
        self.kb_directory.mkdir(parents=True, exist_ok=True)

        # Find all markdown and text files
        local_files = list(self.kb_directory.glob("*.md")) + list(self.kb_directory.glob("*.txt"))

        if not local_files:
            self.logger.warning(
                f"No markdown or text files found in {self.kb_directory}"
            )
            return 0

        # Create a map of file modifications
        current_loaded_files = {
            f.name: f.stat().st_mtime for f in local_files
        }

        if self._is_loaded and not force_reload:
            # Check if we need to reload based on file changes
            if self._loaded_files == current_loaded_files:
                self.logger.debug(
                    f"KB: '{self.name}' already loaded and up to date"
                )
                return 0

        # Check if cache exists and is valid
        if self.cache_file.exists() and not force_reload:
            try:
                # Check cache validity
                cache_mtime = self.cache_file.stat().st_mtime
                # Cache must be newer than all source files
                is_cache_valid = all(
                    cache_mtime > mtime for mtime in current_loaded_files.values()
                )

                if is_cache_valid:
                    await self._load_from_cache()
                    self._is_loaded = True
                    # IMPORTANT: Populate _loaded_files so change detection works
                    self._loaded_files = current_loaded_files
                    self.logger.info(
                        f"Loaded KB '{self.name}' from cache (valid as of {time.ctime(cache_mtime)})"
                    )
                    return 0
                else:
                    self.logger.debug(
                        f"KB cache for '{self.name}' is stale, reloading..."
                    )

            except Exception as e:
                self.logger.warning(
                    f"Failed to load cache: {e}, rebuilding..."
                )

        self.logger.info(
            f"Loading {len(local_files)} markdown and text files into KB '{self.name}'"
        )

        # Process each file
        documents = []
        for local_file in local_files:
            try:
                content = local_file.read_text(encoding='utf-8')

                # Split into chunks
                chunks = self._chunk_markdown(content, local_file.name)

                # Create Document objects
                for i, chunk_text in enumerate(chunks):
                    doc = Document(
                        page_content=chunk_text,
                        metadata={
                            'source': local_file.name,
                            'kb_name': self.name,
                            'chunk_id': i,
                            'total_chunks': len(chunks),
                            'file_path': str(local_file),
                        }
                    )
                    documents.append(doc)

                # Track file modification time
                self._loaded_files[local_file.name] = local_file.stat().st_mtime

            except Exception as e:
                self.logger.error(
                    f"Error processing {local_file.name}: {e}"
                )

        if not documents:
            self.logger.warning("No documents to load")
            return 0

        # Initialize FAISS store
        await self.faiss_store.connection()

        # Define collection
        self.faiss_store.define_collection_table(
            collection_name=f"{self.name}_local_kb",
            dimension=self.dimension
        )

        # Add documents to FAISS
        await self.faiss_store.add_documents(
            documents=documents,
            collection=f"{self.name}_local_kb"
        )

        # Save to cache
        await self._save_to_cache()

        self._is_loaded = True

        self.logger.info(
            f"Successfully loaded {len(documents)} chunks from "
            f"{len(local_files)} files into KB '{self.name}'"
        )

        return len(documents)

    def _chunk_markdown(
        self,
        content: str,
        filename: str
    ) -> List[str]:
        """
        Chunk markdown content intelligently by sections.

        Preserves:
        - Headers and their content together
        - Code blocks intact
        - Lists intact
        """
        chunks = []

        # Split by markdown headers
        sections = re.split(r'\n(#{1,6}\s+.+)\n', content)

        current_chunk = []
        current_size = 0

        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue

            section_size = len(section)

            # If section is too large, split it
            if section_size > self.chunk_size:
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                    current_chunk = []
                    current_size = 0

                # Split large section by paragraphs
                paragraphs = section.split('\n\n')
                for para in paragraphs:
                    para = para.strip()
                    if not para:
                        continue

                    if current_size + len(para) > self.chunk_size:
                        if current_chunk:
                            chunks.append('\n'.join(current_chunk))
                        current_chunk = [para]
                        current_size = len(para)
                    else:
                        current_chunk.append(para)
                        current_size += len(para)

            # Normal section fits in chunk
            elif current_size + section_size > self.chunk_size:
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                current_chunk = [section]
                current_size = section_size
            else:
                current_chunk.append(section)
                current_size += section_size

        # Add remaining
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks

    async def search(
        self,
        query: str,
        k: int = 5,
        score_threshold: float = 0.5,
        user_id: str = None,
        session_id: str = None,
        ctx: RequestContext = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant knowledge in markdown files.

        Args:
            query: Search query
            k: Number of results
            score_threshold: Minimum similarity score

        Returns:
            List of relevant chunks with metadata
        """
        # Ensure documents are loaded
        if not self._is_loaded:
            await self.load_documents()

        # Check if files changed
        await self._check_file_changes()

        try:
            # Search FAISS
            results = await self.faiss_store.asearch(
                query=query,
                k=k,
                collection=f"{self.name}_local_kb",
                score_threshold=score_threshold
            )

            # Format results
            formatted_results = []
            formatted_results.extend(
                {
                    'content': result.content,
                    'metadata': result.metadata,
                    'score': result.score,
                    'source': result.metadata.get('source', 'unknown')
                } for result in results
            )
            return formatted_results

        except Exception as e:
            self.logger.error(f"Search error in KB '{self.name}': {e}")
            return []

    async def _check_file_changes(self) -> bool:
        """
        Check if any markdown files have changed.
        If changed, trigger reload.

        Returns:
            True if files changed
        """
        changed = False
        local_files = list(self.kb_directory.glob("*.md")) + list(self.kb_directory.glob("*.txt"))
        for local_file in local_files:
            filename = local_file.name
            current_mtime = local_file.stat().st_mtime

            if filename not in self._loaded_files:
                changed = True
                break

            if current_mtime != self._loaded_files[filename]:
                changed = True
                break

        if changed:
            self.logger.info(
                f"KB files changed, reloading '{self.name}'"
            )
            await self.load_documents(force_reload=True)

        return changed

    async def _save_to_cache(self) -> None:
        """Save FAISS index to cache file."""
        try:
            self.faiss_store.save(self.cache_file)
            self.logger.debug(f"Saved KB cache to {self.cache_file}")
        except Exception as e:
            self.logger.warning(f"Failed to save cache: {e}")

    async def _load_from_cache(self) -> None:
        """Load FAISS index from cache file."""
        await self.faiss_store.connection()
        self.faiss_store.load(self.cache_file)
        self.logger.debug(f"Loaded KB cache from {self.cache_file}")

    def format_context(self, results: List[Dict]) -> str:
        """
        Format search results for prompt injection.

        Groups results by source file for clarity.
        """
        if not results:
            return ""

        lines = [f"\n## {self.name} Useful Facts:", ""]

        # Group by source file
        by_source: Dict[str, List[Dict]] = {}
        for result in results:
            source = result['metadata'].get('source', 'unknown')
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(result)

        # Format each source
        for source, source_results in by_source.items():
            lines.append(f"## From {source}:")
            for result in source_results:
                content = result['content'].strip()
                lines.extend((content, ""))

        return "\n".join(lines)

    async def close(self):
        """Cleanup resources."""
        if self.faiss_store:
            await self.faiss_store.disconnect()
