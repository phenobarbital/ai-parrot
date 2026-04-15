import logging

from .abstract import AbstractKnowledgeBase
from .redis import RedisKnowledgeBase
from .local import LocalKB

# Suppress noisy DEBUG output from httpcore/httpx during KB operations
logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.INFO)

__all__ = (
    'AbstractKnowledgeBase',
    'RedisKnowledgeBase',
    'LocalKB',
)
