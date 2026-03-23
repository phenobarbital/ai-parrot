"""
LocalKBMixin: Mixin to add local markdown KB support to agents.

This mixin provides automatic loading of markdown knowledge bases from
the agent's local directory structure (AGENTS_DIR/<agent_name>/kb/).
"""
from typing import Optional, List
from pathlib import Path
# from ...stores.kb.local import LocalKB
from ...conf import AGENTS_DIR


class LocalKBMixin:
    """
    Mixin to add local markdown KB support to agents.

    Usage:
        class AbstractBot(DBInterface, LocalKBMixin, ABC):
            ...

    This mixin provides:
    - Automatic KB directory detection
    - Loading of markdown files from AGENTS_DIR/<agent_name>/kb/
    - Integration with the agent's knowledge_bases list
    - Proper error handling and logging
    """
    def _get_kb_local_files(self, kb_dir: Path) -> List[Path]:
        """
        Get list of markdown or text files in KB directory.

        Args:
            kb_dir: Path to KB directory

        Returns:
            List[Path]: List of .md or .txt files
        """
        if not kb_dir.exists():
            return []

        return list(kb_dir.glob("*.md")) + list(kb_dir.glob("*.txt"))

    def _get_agent_kb_directory(self) -> Optional[Path]:
        """
        Get the kb/ directory for this agent.

        Returns path to AGENTS_DIR/<agent_name|agent_id>/kb/
        """
        safe_name = None
        if hasattr(self, 'agent_id'):
            safe_name = self.agent_id.lower().replace(' ', '_')

        elif hasattr(self, 'name'):
            safe_name = self.name.lower().replace(' ', '_')
        else:
            return None
        kb_dir = Path(AGENTS_DIR) / safe_name / 'kb'
        return kb_dir

    async def configure_local_kb(self) -> None:
        """
        Configure local markdown KB for this agent.

        Called automatically during configure().
        Loads markdown files from AGENTS_DIR/<agent_name>/kb/

        Process:
        1. Locate agent's KB directory
        2. Scan for .md files
        3. Create LocalMarkdownKB instance
        4. Load and vectorize documents
        5. Add to agent's knowledge_bases list

        This method fails gracefully - if no KB exists or loading fails,
        the agent continues without local KB.
        """
        kb_dir = self._get_agent_kb_directory()

        print('::: Configuring local KB from directory:', kb_dir)

        if not kb_dir or not kb_dir.exists():
            self.logger.debug(
                f":: No local KB directory found at {kb_dir}"
            )
            return

        # Check if directory has markdown or text files
        local_files = self._get_kb_local_files(kb_dir)
        if not local_files:
            self.logger.debug(
                f"No document files found in local KB directory {kb_dir}"
            )
            return

        self.logger.notice(
            f"Loading local KB from {kb_dir} "
            f"({len(local_files)} document files)"
        )

        try:
            # Create LocalKB store
            from ...stores.kb.local import LocalKB
            local_kb = LocalKB(
                name=f"{self.name}_local",
                kb_directory=kb_dir,
                category="agent_local",
                description=f"Local knowledge base for {self.name}",
                embedding_model=getattr(
                    self,
                    'kb_embedding_model',
                    'sentence-transformers/all-mpnet-base-v2'
                ),
                dimension=getattr(self, 'kb_dimension', 384),
                always_active=True,
                auto_load=True,
            )

            # Load documents
            num_docs = await local_kb.load_documents()

            # Add to knowledge bases list
            if not hasattr(self, 'knowledge_bases'):
                self.knowledge_bases = []

            self.knowledge_bases.append(local_kb)

            self.logger.info(
                f"Local KB loaded: {num_docs} chunks from {len(local_files)} files"
            )

        except Exception as e:
            self.logger.error(
                f"Error loading local KB: {e}",
                exc_info=True
            )

    def has_local_kb(self) -> bool:
        """
        Check if agent has a local KB loaded.

        Returns:
            bool: True if local KB is present in knowledge_bases
        """
        if not hasattr(self, 'knowledge_bases'):
            return False

        for kb in self.knowledge_bases:
            if hasattr(kb, 'category') and kb.category == "agent_local":
                return True

        return False

    def get_local_kb_info(self) -> Optional[dict]:
        """
        Get information about the loaded local KB.

        Returns:
            Optional[dict]: KB info including name, directory, files count
        """
        if not hasattr(self, 'knowledge_bases'):
            return None

        for kb in self.knowledge_bases:
            if hasattr(kb, 'category') and kb.category == "agent_local":
                return {
                    'name': kb.name,
                    'directory': str(kb.kb_directory),
                    'files_loaded': len(kb._loaded_files),
                    'is_loaded': kb._is_loaded,
                    'cache_file': str(kb.cache_file)
                }

        return None
