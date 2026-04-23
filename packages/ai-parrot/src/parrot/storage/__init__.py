# parrot/storage — conversation and artifact storage layer.
# See docs/storage-backends.md for the backend selection matrix and env var reference.
from .chat import ChatStorage
from .models import ChatMessage, Conversation
from .models import (
    ArtifactType,
    ArtifactCreator,
    ArtifactSummary,
    Artifact,
    ThreadMetadata,
    CanvasBlockType,
    CanvasBlock,
    CanvasDefinition,
)
from .dynamodb import ConversationDynamoDB
from .s3_overflow import S3OverflowManager
from .overflow import OverflowStore                                   # FEAT-116
from .artifacts import ArtifactStore
from .backends.base import ConversationBackend                        # FEAT-116
from .backends import (                                               # FEAT-116
    ConversationSQLiteBackend,
    ConversationPostgresBackend,
    ConversationMongoBackend,
    build_conversation_backend,
    build_overflow_store,
)
from .metrics import StorageMetrics, NoopStorageMetrics               # FEAT-116
from .instrumented import InstrumentedBackend                         # FEAT-116

__all__ = [
    "ChatStorage",
    "ChatMessage",
    "Conversation",
    # FEAT-103 artifact & thread models
    "ArtifactType",
    "ArtifactCreator",
    "ArtifactSummary",
    "Artifact",
    "ThreadMetadata",
    "CanvasBlockType",
    "CanvasBlock",
    "CanvasDefinition",
    # FEAT-103 DynamoDB backend (back-compat)
    "ConversationDynamoDB",
    # FEAT-103 S3 overflow (back-compat)
    "S3OverflowManager",
    # FEAT-116 generalized overflow
    "OverflowStore",
    # FEAT-116 ConversationBackend ABC
    "ConversationBackend",
    # FEAT-116 concrete backends
    "ConversationSQLiteBackend",
    "ConversationPostgresBackend",
    "ConversationMongoBackend",
    # FEAT-116 factories
    "build_conversation_backend",
    "build_overflow_store",
    # FEAT-116 observability
    "StorageMetrics",
    "NoopStorageMetrics",
    "InstrumentedBackend",
    # FEAT-103 ArtifactStore
    "ArtifactStore",
]
