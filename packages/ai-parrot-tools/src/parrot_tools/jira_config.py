"""JiraToolkit configuration model (FEAT-593)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_SECRET = {"x-secret": True}


class JiraToolkitConfig(BaseModel):
    """Operator-facing Jira toolkit configuration rendered by Agent Studio."""

    model_config = ConfigDict(extra="forbid")
    server_url: str | None = Field(default=None, description="Jira base URL, e.g. https://acme.atlassian.net")
    # Verified against JiraToolkit._init_jira_client (jiratoolkit.py:889-939): the
    # only auth_type values handled by the static (non oauth2_3lo) client-init path.
    auth_type: Literal["basic_auth", "token_auth", "oauth"] | None = None
    username: str | None = None
    password: str | None = Field(default=None, json_schema_extra=_SECRET)
    token: str | None = Field(default=None, json_schema_extra=_SECRET)
    default_project: str | None = Field(default=None, description="Default project key")
    verify_credentials: bool = True
