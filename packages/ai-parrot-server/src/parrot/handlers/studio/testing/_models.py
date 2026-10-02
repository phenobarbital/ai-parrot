"""Request models and constants of the Studio testing surface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field



SESSION_PREFIX = "_studio_test:"

# App-context dependency wiring for tool instantiation (spec §3 Module 9 —
# "app-context-wired" instantiation for tools whose constructor requires a
# server-managed resource). Extend this map as more such tools are added.
_KNOWN_APP_DEPS: dict[str, str] = {
    "artifact_store": "artifact_store",
}


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
    """

    query: str
    use_byok: bool = True


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
