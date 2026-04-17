"""Authentication and authorization exceptions for AI-Parrot.

This module defines exceptions that toolkits can raise when the framework
needs to surface an authorization requirement back to the caller (typically
the LLM, through :class:`parrot.tools.manager.ToolManager`).
"""
from __future__ import annotations

from typing import List, Optional


class AuthorizationRequired(Exception):
    """Raised when a toolkit needs user authorization before operating.

    ``ToolManager.execute_tool`` catches this exception and converts it into
    a :class:`parrot.tools.abstract.ToolResult` with
    ``status='authorization_required'``.  The metadata carries the
    ``auth_url`` and ``provider`` so the agent/LLM can present an actionable
    link to the end user.

    Typical producer: a toolkit's :meth:`_pre_execute` hook that resolves
    per-user OAuth 2.0 tokens from Redis and discovers none are on file.

    Attributes:
        tool_name: Name of the tool that failed the authorization check.
        message: Human-readable description for logs and the LLM.
        auth_url: URL that the user should open to complete the authorization
            flow. ``None`` when no URL is available yet.
        provider: Identifier of the external provider (``"jira"``,
            ``"github"``, ``"o365"``, …). Defaults to ``"unknown"``.
        scopes: Scopes that the provider should grant during consent.
    """

    def __init__(
        self,
        tool_name: str,
        message: str,
        auth_url: Optional[str] = None,
        provider: str = "unknown",
        scopes: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.message = message
        self.auth_url = auth_url
        self.provider = provider
        self.scopes: List[str] = list(scopes) if scopes else []

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"AuthorizationRequired(tool_name={self.tool_name!r}, "
            f"provider={self.provider!r}, auth_url={self.auth_url!r})"
        )
