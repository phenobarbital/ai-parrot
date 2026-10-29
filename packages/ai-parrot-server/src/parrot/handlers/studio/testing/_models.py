"""Request models and constants of the Studio testing surface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field



SESSION_PREFIX = "_studio_test:"

#: A conversation the client names (``session_id`` on ``test/ask`` and on the test ``DELETE``).
CLIENT_SESSION_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class _ServerManagedDepsError(Exception):
    """Raised when a tool's constructor requires deps this endpoint can't supply."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Missing server-managed dependencies: {missing}")


class TestAskRequest(BaseModel):
    """``POST .../test/ask`` payload.

    Attributes:
        query: The question to send to the test agent instance.
        use_byok: When ``True`` (default) and a BYOK key is stored for the
            agent's LLM provider, the test client is built with that key
            (TASK-2516 ``resolve_user_api_key``). When no key is stored,
            this is a no-op — the agent's normally-configured client is
            used. An auth failure from a genuinely stored key is NEVER
            retried against the server's default key (spec §7).
        key_source: ``"server"`` or ``"byok"`` (PA-2). Required (``409 key_source_required``) when BOTH a server
            key and a stored personal key exist for the provider; a source that does not exist is
            ``422 key_source_unavailable``. An explicit source wins over ``use_byok``.
        session_id: Optional conversation the client names (``CLIENT_SESSION_PATTERN``). Each one keeps its own
            history, so a client can hold several conversations with one agent and come back to any of them while
            the conversation backend keeps it. Without it, the caller's one test session (``studio_test:``) is used.
            Database mode only; the legacy path ignores it.
    """

    query: str
    use_byok: bool = True
    key_source: Literal["server", "byok"] | None = None
    session_id: str | None = Field(default=None, pattern=CLIENT_SESSION_PATTERN)


class ToolExecuteRequest(BaseModel):
    """``POST /tools/{slug}/execute`` payload."""

    args: dict[str, Any] = Field(default_factory=dict)


class ToolkitAssignEntry(BaseModel):
    """One toolkit assignment entry."""

    slug: str
    params: dict[str, Any] = Field(default_factory=dict)


class ToolAssignRequest(BaseModel):
    """``POST /agents/{name}/tools`` payload."""

    tools: list[str] = Field(default_factory=list)
    toolkits: list[ToolkitAssignEntry] = Field(default_factory=list)
