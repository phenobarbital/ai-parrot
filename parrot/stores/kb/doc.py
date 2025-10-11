from typing import Any, Dict, List, Optional
from .redis import RedisKnowledgeBase


class UserContext(RedisKnowledgeBase):
    """Knowledge Base for user context and session data."""

    def __init__(self, **kwargs):
        super().__init__(
            name="User Context",
            category="context",
            namespace="user_context",
            activation_patterns=[
                "last conversation", "previously", "we discussed",
                "earlier you mentioned", "remember when"
            ],
            use_hash_storage=True,
            ttl=86400 * 30,  # 30 days expiration
            **kwargs
        )

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Retrieve user context matching the query."""
        if not user_id:
            return []

        context = await self.get(user_id)
        if not context:
            return []

        facts = []
        query_lower = query.lower()

        # Search through context fields
        for key, value in context.items():
            if query_lower in key.lower() or query_lower in str(value).lower():
                facts.append({
                    'content': f"User context - {key}: {value}",
                    'metadata': {
                        'context_key': key,
                        'user_id': user_id,
                        'value': value
                    },
                    'source': 'user_context',
                    'relevance': 1.0 if query_lower == key.lower() else 0.5
                })

        return facts

    async def update_context(
        self,
        user_id: str,
        context_data: Dict[str, Any]
    ) -> bool:
        """
        Update user context with new data.

        Args:
            user_id: User identifier
            context_data: Context data to update

        Returns:
            True if successful
        """
        return await self.update(user_id, context_data)

    async def get_context(self, user_id: str) -> Dict[str, Any]:
        """Get all context for a user."""
        return await self.get(user_id, default={})

    async def set_context_field(
        self,
        user_id: str,
        field: str,
        value: Any
    ) -> bool:
        """Set a specific context field."""
        return await self.insert(user_id, value, field=field)

    async def get_context_field(
        self,
        user_id: str,
        field: str,
        default: Any = None
    ) -> Any:
        """Get a specific context field."""
        return await self.get(user_id, field=field, default=default)

    async def clear_context(self, user_id: str) -> bool:
        """Clear all context for a user."""
        return await self.delete(user_id)


class ChatbotSettings(RedisKnowledgeBase):
    """Knowledge Base for chatbot-specific settings."""

    def __init__(self, **kwargs):
        super().__init__(
            name="Chatbot Settings",
            category="settings",
            namespace="bot_settings",
            activation_patterns=[],  # Not activated by patterns
            use_hash_storage=True,
            **kwargs
        )

    async def search(
        self,
        query: str,
        chatbot_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Retrieve chatbot settings."""
        if not chatbot_id:
            return []

        settings = await self.get(chatbot_id)
        if not settings:
            return []

        return [{
            'content': f"Chatbot settings: {settings}",
            'metadata': {
                'chatbot_id': chatbot_id,
                'settings': settings
            },
            'source': 'chatbot_settings'
        }]

    async def get_setting(
        self,
        chatbot_id: str,
        setting: str,
        default: Any = None
    ) -> Any:
        """Get a specific chatbot setting."""
        return await self.get(chatbot_id, field=setting, default=default)

    async def set_setting(
        self,
        chatbot_id: str,
        setting: str,
        value: Any
    ) -> bool:
        """Set a specific chatbot setting."""
        return await self.insert(chatbot_id, value, field=setting)

class DocumentMetadata(RedisKnowledgeBase):
    """Knowledge Base for document metadata and indexing."""

    def __init__(self, **kwargs):
        super().__init__(
            name="Document Metadata",
            category="documents",
            namespace="doc_meta",
            activation_patterns=[
                "document", "file", "uploaded", "attachment"
            ],
            use_hash_storage=True,
            **kwargs
        )

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Search document metadata.

        FIXED: Properly handle user_id filtering since it's stored as a field,
        not part of the key structure.
        """
        query_lower = query.lower()
        results = []

        # Search across ALL documents (don't pass user_id to base search)
        # The base search would try to use it in the key pattern which is wrong
        all_results = await super().search(
            query,
            identifier=None,  # Search all documents
            field_filter=['title', 'description', 'tags', 'filename'],
            limit=kwargs.get('limit', 100)
        )

        # Now filter by user_id if provided
        for result in all_results:
            doc_data = result.get('data', {})

            # Filter by user_id if specified
            if user_id and doc_data.get('user_id') != user_id:
                continue

            # Format results for document context
            results.append({
                'content': f"Document: {doc_data.get('title', 'Unknown')} - {doc_data.get('description', '')}",
                'metadata': {
                    'document_id': result.get('identifier'),
                    'user_id': doc_data.get('user_id'),
                    'title': doc_data.get('title'),
                    'filename': doc_data.get('filename'),
                    'tags': doc_data.get('tags', []),
                    **{k: v for k, v in doc_data.items() if k not in ['title', 'filename', 'tags', 'user_id']}
                },
                'source': 'document_metadata',
                'relevance': result.get('relevance', 0.0)
            })

        # Sort by relevance
        results.sort(key=lambda x: x.get('relevance', 0.0), reverse=True)
        return results

    async def add_document(
        self,
        doc_id: str,
        user_id: str,
        title: str,
        filename: str,
        description: str = "",
        tags: List[str] = None,
        **metadata
    ) -> bool:
        """
        Add document metadata.

        Args:
            doc_id: Document identifier
            user_id: Owner user ID
            title: Document title
            filename: Original filename
            description: Document description
            tags: Document tags
            **metadata: Additional metadata

        Returns:
            True if successful
        """
        doc_data = {
            'user_id': user_id,
            'title': title,
            'filename': filename,
            'description': description,
            'tags': tags or [],
            **metadata
        }
        return await self.insert(doc_id, doc_data)

    async def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific document's metadata."""
        return await self.get(doc_id)

    async def delete_document(self, doc_id: str) -> bool:
        """ Delete a document's metadata."""
        return await self.delete(doc_id)

    async def list_user_documents(
        self,
        user_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List all documents for a specific user."""
        all_docs = await self.list_all(limit=limit)

        user_docs = []
        for doc in all_docs:
            doc_data = doc.get('data', {})
            if doc_data.get('user_id') == user_id:
                user_docs.append({
                    'document_id': doc['identifier'],
                    **doc_data
                })

        return user_docs

    async def search_by_tags(
        self,
        tags: List[str],
        user_id: Optional[str] = None,
        match_all: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Search documents by tags.

        Args:
            tags: List of tags to search for
            user_id: Optional user filter
            match_all: If True, document must have all tags; if False, any tag matches

        Returns:
            List of matching documents
        """
        all_docs = await self.list_all()
        results = []

        for doc in all_docs:
            doc_data = doc.get('data', {})

            # Filter by user if specified
            if user_id and doc_data.get('user_id') != user_id:
                continue

            doc_tags = doc_data.get('tags', [])

            # Check tag matching
            if match_all:
                # Document must have all specified tags
                if all(tag in doc_tags for tag in tags):
                    results.append({
                        'document_id': doc['identifier'],
                        **doc_data
                    })
            else:
                # Document must have at least one tag
                if any(tag in doc_tags for tag in tags):
                    results.append({
                        'document_id': doc['identifier'],
                        **doc_data
                    })

        return results
