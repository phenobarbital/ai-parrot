"""Common / shared models — Relay pagination generics and OAuth token.

All models in this module are pure Pydantic v2 data classes with no
dependencies on GigSmart-specific types. They are reused across every
API surface.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, ConfigDict, model_validator

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Relay pagination
# ---------------------------------------------------------------------------


class RelayPageInfo(BaseModel):
    """GraphQL Relay PageInfo fragment.

    Args:
        has_next_page: True when more pages follow the current cursor.
        has_previous_page: True when pages precede the current cursor.
        start_cursor: Cursor for the first edge in the current page.
        end_cursor: Cursor for the last edge in the current page — pass as
            ``after`` to fetch the next page.
    """

    model_config = ConfigDict(populate_by_name=True)

    has_next_page: bool = Field(alias="hasNextPage")
    has_previous_page: bool = Field(default=False, alias="hasPreviousPage")
    start_cursor: str | None = Field(default=None, alias="startCursor")
    end_cursor: str | None = Field(default=None, alias="endCursor")


class RelayEdge(BaseModel, Generic[T]):
    """A single edge in a Relay connection.

    Args:
        node: The actual resource payload.
        cursor: Opaque pagination cursor for this edge.
    """

    model_config = ConfigDict(populate_by_name=True)

    node: T
    cursor: str | None = None


class RelayConnection(BaseModel, Generic[T]):
    """A Relay pagination connection wrapping a list of typed edges.

    Args:
        edges: List of :class:`RelayEdge` wrappers around the resource type.
        page_info: Pagination metadata for the current page.
    """

    model_config = ConfigDict(populate_by_name=True)

    edges: list[RelayEdge[T]] = Field(default_factory=list)
    page_info: RelayPageInfo = Field(alias="pageInfo")

    def nodes(self) -> list[T]:
        """Return the unwrapped list of node objects from all edges."""
        return [edge.node for edge in self.edges]


# ---------------------------------------------------------------------------
# OAuth token
# ---------------------------------------------------------------------------


class OAuthToken(BaseModel):
    """Parsed OAuth 2.1 token response from the GigSmart token endpoint.

    Args:
        access_token: The Bearer token string.
        token_type: Always ``"bearer"`` for GigSmart.
        expires_in: Token lifetime in seconds.
        refresh_token: Present only for auth_code grant responses.
        scope: Space-separated list of granted scopes.
        expires_at: Computed absolute UTC expiry time (``now + expires_in``).
    """

    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(alias="access_token")
    token_type: str = Field(default="bearer", alias="token_type")
    expires_in: int = Field(alias="expires_in")
    refresh_token: str | None = Field(default=None, alias="refresh_token")
    scope: str = Field(alias="scope")
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _compute_expires_at(self) -> "OAuthToken":
        """Compute ``expires_at`` from ``expires_in`` when not explicitly provided."""
        if self.expires_at is None:
            self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.expires_in)
        return self

    def is_expired(self) -> bool:
        """Return True if the token has passed its expiry time."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def needs_refresh(self, threshold_seconds: int = 120) -> bool:
        """Return True if the token expires within *threshold_seconds*."""
        if not self.expires_at:
            return True
        remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return remaining < threshold_seconds
