"""Backward-compatible re-export shim for ConversationDynamoDB.

The class was moved to parrot.storage.backends.dynamodb in FEAT-116.
This shim is kept for one release cycle to avoid breaking existing imports.

FEAT-116: dynamodb-fallback-redis — Module 3 (re-export shim).
"""

from parrot.storage.backends.dynamodb import ConversationDynamoDB  # noqa: F401

__all__ = ["ConversationDynamoDB"]
