"""Database access for the SaaS plane: schema DDL and the base repository."""
from .repository import BaseRepository, TenantScopeError, check_identifier
from .schema import ensure_schema

__all__ = (
    "BaseRepository",
    "TenantScopeError",
    "check_identifier",
    "ensure_schema",
)
