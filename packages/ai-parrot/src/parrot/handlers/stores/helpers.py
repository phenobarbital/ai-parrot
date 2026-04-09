"""Vector Store Helper — public metadata endpoints for vector store configuration."""
from typing import List, Dict, Any
from navigator.views import BaseHandler
from parrot.stores import supported_stores
from parrot.stores.models import DistanceStrategy
from parrot.embeddings import supported_embeddings, get_embedding_models, get_use_cases
from parrot_loaders.factory import LOADER_MAPPING


class VectorStoreHelper(BaseHandler):
    """Public metadata endpoints for vector store configuration.

    All methods are static and return plain dicts/lists.
    These are called by VectorStoreHandler.get() to serve
    unauthenticated metadata endpoints.
    """

    @staticmethod
    def supported_stores() -> dict:
        """Return supported vector store types.

        Returns:
            dict: Mapping of store key to class name, e.g. {'postgres': 'PgVectorStore'}.
        """
        return supported_stores

    @staticmethod
    def supported_embeddings() -> dict:
        """Return supported embedding model types.

        Returns:
            dict: Mapping of embedding key to class name.
        """
        return supported_embeddings

    @staticmethod
    def supported_loaders() -> dict:
        """Return supported file loaders as a clean extension→class_name mapping.

        Transforms the internal LOADER_MAPPING (extension → (module, class))
        into a simpler (extension → class_name) format.

        Returns:
            dict: Mapping of file extension to loader class name.
        """
        return {ext: cls_name for ext, (_, cls_name) in LOADER_MAPPING.items()}

    @staticmethod
    def supported_embedding_models(
        provider: str = None,
        use_case: str = None,
    ) -> List[Dict[str, Any]]:
        """Return the curated catalog of embedding models.

        Args:
            provider: Filter by provider (huggingface, openai, google).
            use_case: Filter by use case (similarity, retrieval, clustering,
                      multilingual, code).

        Returns:
            list: Embedding model descriptors with metadata.
        """
        return get_embedding_models(provider=provider, use_case=use_case)

    @staticmethod
    def supported_use_cases() -> Dict[str, str]:
        """Return embedding use-case categories and descriptions.

        Returns:
            dict: Mapping of use-case key to human-readable description.
        """
        return get_use_cases()

    @staticmethod
    def supported_index_types() -> list:
        """Return supported distance strategy / index types.

        Returns:
            list: List of DistanceStrategy enum values as strings.
        """
        return [strategy.value for strategy in DistanceStrategy]
