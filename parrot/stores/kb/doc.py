from typing import Any, Dict, List, Optional
from .redis import RedisKnowledgeBase


class UserContext(RedisKnowledgeBase):
    """Knowledge Base for user context and session data."""

    def __init__(self, **kwargs):
        super().__init__(
            name="User Context",
            category="context",
            key_prefix="user_context",
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
        facts.extend(
            {
                'content': f"User context - {key}: {value}",
                'metadata': {'context_key': key, 'user_id': user_id},
                'source': 'user_context',
            }
            for key, value in context.items()
            if query_lower in key.lower() or query_lower in str(value).lower()
        )

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


class ChatbotSettings(RedisKnowledgeBase):
    """Knowledge Base for chatbot-specific settings."""

    def __init__(self, **kwargs):
        super().__init__(
            name="Chatbot Settings",
            category="settings",
            key_prefix="bot_settings",
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
            key_prefix="doc_meta",
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
        """Search document metadata."""
        # Custom search logic for documents
        results = await super().search(
            query,
            identifier=user_id,
            field_filter=['title', 'description', 'tags', 'filename'],
            **kwargs
        )

        # Format results for document context
        facts = []
        for result in results:
            doc_data = result.get('data', {})
            facts.append({
                'content': f"Document: {doc_data.get('title', 'Unknown')} - {doc_data.get('description', '')}",
                'metadata': {
                    'document_id': result.get('identifier'),
                    'user_id': user_id,
                    **doc_data
                },
                'source': 'document_metadata'
            })

        return facts

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
