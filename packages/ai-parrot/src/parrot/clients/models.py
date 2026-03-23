from __future__ import annotations
from typing import Any, Dict, Optional, Type
from dataclasses import dataclass, field
from .base import AbstractClient


@dataclass
class LLMConfig:
    """Resolved LLM configuration."""
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: float = 0.1
    top_k: int = 41
    top_p: float = 0.9
    max_tokens: Optional[int] = None
    client_class: Optional[Type[AbstractClient]] = None
    client_instance: Optional[AbstractClient] = None
    extra: Dict[str, Any] = field(default_factory=dict)
