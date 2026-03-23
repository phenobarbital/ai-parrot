from typing import Optional
from dataclasses import dataclass

@dataclass
class TransportConfig:
    """Configuration for a single transport."""
    transport: str  # "stdio" or "http" or "sse" or "unix"
    enabled: bool = True
    host: Optional[str] = None  # Only for HTTP
    port: Optional[int] = None  # Only for HTTP
    url: Optional[str] = None  # Only for HTTP/SSE transport
    name_suffix: Optional[str] = None  # e.g., "local" or "remote"
    socket_path: Optional[str] = None  # Only for UNIX socket transport
