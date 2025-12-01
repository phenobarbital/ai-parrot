from typing import Optional
from dataclasses import dataclass

@dataclass
class TransportConfig:
    """Configuration for a single transport."""
    transport: str  # "stdio" or "http"
    enabled: bool = True
    host: Optional[str] = None  # Only for HTTP
    port: Optional[int] = None  # Only for HTTP
    name_suffix: Optional[str] = None  # e.g., "local" or "remote"
