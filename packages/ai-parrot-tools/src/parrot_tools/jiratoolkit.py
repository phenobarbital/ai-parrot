"""
Jira Toolkit - A unified toolkit for Jira operations using pycontribs/jira.

This toolkit wraps common Jira actions as async tools, extending AbstractToolkit.
It supports multiple authentication modes on init: basic_auth, token_auth, and OAuth1.

Dependencies:
    - jira (pycontribs/jira)
    - pydantic
    - navconfig (optional, for pulling default config values)

Example usage:
    toolkit = JiraToolkit(
        server_url="https://your-domain.atlassian.net",
        auth_type="token_auth",
        username="you@example.com",
        token="<PAT>",
        default_project="JRA"
    )
    tools = toolkit.get_tools()
    issue = await toolkit.jira_get_issue("JRA-1330")

Notes:
- All public async methods become tools via AbstractToolkit.
- Methods are async but the underlying jira client is sync, so calls run via asyncio.to_thread.
- Each method returns JSON-serializable dicts/lists (using Issue.raw where possible).
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Union, Literal
import os
import re
import logging
import asyncio
import importlib
from datetime import datetime
from pydantic import BaseModel, Field
import pandas as pd

try:
    # Optional config source; fall back to env vars if missing
    from navconfig import config as nav_config  # type: ignore
except Exception:  # pragma: no cover - optional
    nav_config = None

try:
    from jira import JIRA
except ImportError as e:  # pragma: no cover - optional
    raise ImportError(
        "Please install the 'jira' package: pip install jira"
    ) from e
from parrot.tools.manager import ToolManager
from parrot.auth.exceptions import AuthorizationRequired
from .toolkit import AbstractToolkit
from .decorators import tool_schema, requires_permission


# -----------------------------
# Helpers
# -----------------------------

def _parse_csv(value: str) -> List[str]:
    """Parse a comma-separated string into a list, stripping whitespace."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


# -----------------------------
# Input models (schemas)
# -----------------------------
STRUCTURED_OUTPUT_FIELD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "include": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Whitelist of dot-paths to include"
        },
        "mapping": {
            "type": "object",
            "description": "dest_key -> dot-path mapping",
            "additionalProperties": {"type": "string"}
        },
        "model_path": {
            "type": "string",
            "description": "Dotted path to a Pydantic BaseModel subclass"
        },
        "strict": {
            "type": "boolean",
            "description": "If True, missing paths raise; otherwise they become None"
        }
    }
}


class StructuredOutputOptions(BaseModel):
    """Options to shape the output of Jira items into either a whitelist or a Pydantic model.


    You can:
    - provide `include` as a list of dot-paths to keep (e.g., ["key", "fields.summary", "fields.assignee.displayName"]).
    - OR provide `mapping` as {dest_key: dot_path} to rename/flatten fields.
    - OR provide `model_path` as a dotted import path to a BaseModel subclass. We will validate and return `model_dump()`.


    If more than one is provided, precedence is: mapping > include > model_path (mapping/include are applied before model).
    """
    include: Optional[List[str]] = Field(default=None, description="Whitelist of dot-paths to include")
    mapping: Optional[Dict[str, str]] = Field(default=None, description="dest_key -> dot-path mapping")
    model_path: Optional[str] = Field(default=None, description="Dotted path to a Pydantic BaseModel subclass")
    strict: bool = Field(default=False, description="If True, missing paths raise; otherwise they become None")

# =============================================================================
# Field Presets for Efficiency
# =============================================================================

FIELD_PRESETS = {
    # Minimal fields for counting
    "count": "key,assignee,reporter,status,priority,issuetype,project,created",

    # Fields for listing/browsing
    "list": "key,summary,assignee,status,priority,issuetype,project,created,updated",

    # Fields for detailed analysis
    "analysis": (
        "key,summary,description,assignee,reporter,status,priority,issuetype,"
        "project,created,updated,resolutiondate,duedate,labels,components,"
        "timeoriginalestimate,timespent,customfield_10016"  # story points
    ),

    # All fields
    "all": "*all",
}

# Type hint for presets
FieldPreset = Literal["count", "list", "analysis", "all"]

class JiraInput(BaseModel):
    """Default input for Jira tools: holds auth + default project context.

    You usually do **not** pass this into every call; it's used to configure the
    toolkit on initialization. It's defined here for consistency and as a type
    you can reuse when wiring the toolkit into agents.
    """

    server_url: str = Field(description="Base URL for Jira server (e.g., https://your.atlassian.net)")
    auth_type: str = Field(
        description="Authentication type: 'basic_auth', 'token_auth', or 'oauth'",
        default="token_auth",
    )
    username: Optional[str] = Field(default=None, description="Username (email) for basic/token auth")
    password: Optional[str] = Field(default=None, description="Password for basic auth (or API token)")
    token: Optional[str] = Field(default=None, description="Personal Access Token for token_auth")

    # OAuth1 params (pycontribs JIRA OAuth1)
    oauth_consumer_key: Optional[str] = None
    oauth_key_cert: Optional[str] = Field(default=None, description="PEM private key content or path")
    oauth_access_token: Optional[str] = None
    oauth_access_token_secret: Optional[str] = None

    # Default project context
    default_project: Optional[str] = Field(default=None, description="Default project key, e.g., 'JRA'")


class GetIssueInput(BaseModel):
    """Input for getting a single issue."""
    issue: str = Field(description="Issue key or id, e.g., 'JRA-1330'")
    fields: Optional[str] = Field(default=None, description="Fields to fetch (comma-separated) or '*' ")
    expand: Optional[str] = Field(default=None, description="Entities to expand, e.g. 'renderedFields' ")
    include_history: bool = Field(default=False, description="Include the issue history")
    history_page_size: Optional[int] = Field(
        default=100,
        description="number of items to be returned via changelog"
    )
    structured: Optional[StructuredOutputOptions] = Field(
        default=None,
        description="Optional structured output mapping",
        json_schema_extra=STRUCTURED_OUTPUT_FIELD_SCHEMA
    )


class SearchIssuesInput(BaseModel):
    """Input for searching issues with JQL."""
    jql: str = Field(
        description=(
            "JQL query. Must include at least one filter clause (e.g. "
            "'project = PROJ', 'assignee = currentUser()', a date range). "
            "Jira Cloud rejects unbounded queries like 'order by created desc' "
            "with no restriction."
        )
    )
    start_at: int = Field(default=0, description="Start index for pagination")
    max_results: Optional[int] = Field(
        default=100,
        description=(
            "Max results to return. Set to None to fetch all matching issues. "
            "Jira supports up to 1000 per page. "
            "Default 100 is for browsing; use None for complete counts."
        )
    )
    fields: Optional[str] = Field(
        default=None,
        description=(
            "Fields to return (comma-separated). Use minimal fields for efficiency: "
            "'key,assignee,status,priority' for counts, "
            "'key,summary,assignee,status,created' for listings, "
            "'*all' or None for full details. "
            "Fewer fields = faster response and smaller context."
        )
    )
    expand: Optional[str] = Field(
        default=None,
        description="Expand options (changelog, renderedFields, etc.)"
    )
    structured: Optional[StructuredOutputOptions] = Field(
        default=None,
        description="Optional structured output mapping",
        json_schema_extra=STRUCTURED_OUTPUT_FIELD_SCHEMA
    )
    # Options for efficient handling
    json_result: bool = Field(
        default=True,
        description=(
            "Return results as a JSON object instead of a list of issues. "
            "Set True when you need to do aggregations, grouping, or complex analysis."
        )
    )
    store_as_dataframe: bool = Field(
        default=False,
        description=(
            "Store results in a shared DataFrame for analysis with PythonPandasTool. "
            "Set True when you need to do aggregations, grouping, or complex analysis."
        )
    )
    dataframe_name: Optional[str] = Field(
        default=None,
        description="Name for the stored DataFrame. Defaults to 'jira_issues'."
    )
    summary_only: bool = Field(
        default=False,
        description=(
            "Return only summary statistics (counts by assignee, status, etc.) "
            "instead of raw issues. Ideal for 'how many' or 'count by' queries. "
            "Drastically reduces context window usage."
        )
    )


class CountIssuesInput(BaseModel):
    """Optimized input for counting issues - requests minimal fields."""

    jql: str = Field(
        description="JQL query to count issues"
    )
    group_by: Optional[List[str]] = Field(
        default=None,
        description=(
            "Fields to group counts by. Options: "
            "'assignee', 'reporter', 'status', 'priority', 'issuetype', 'project'. "
            "Example: ['assignee', 'status'] for count by user and status."
        )
    )


class GetMyTicketsInput(BaseModel):
    """Input for retrieving the CURRENT (authenticated) user's Jira tickets.

    INSTRUCT: Use this tool whenever the user asks for THEIR OWN tickets or
    issues (e.g. "my tickets", "my open issues", "what am I assigned to",
    "tickets assigned to me", "mis tickets"). Do NOT build a manual JQL
    query in that case — this tool resolves the authenticated identity
    server-side via ``assignee = currentUser()``.
    """

    status: Optional[Union[str, List[str]]] = Field(
        default=None,
        description=(
            "Optional status filter. Single status (e.g. 'In Progress') or a "
            "list (e.g. ['To Do', 'In Progress']). If omitted, Done/Closed/"
            "Resolved tickets are excluded unless include_closed=True."
        )
    )
    project: Optional[str] = Field(
        default=None,
        description="Optional Jira project key filter (e.g. 'NAV')."
    )
    include_closed: bool = Field(
        default=False,
        description=(
            "When True, include Done/Closed/Resolved tickets. "
            "Ignored if a ``status`` filter is provided."
        )
    )
    max_results: Optional[int] = Field(
        default=50,
        description="Max tickets to return. Use None to fetch all matches."
    )
    order_by: Optional[str] = Field(
        default="updated DESC",
        description="JQL ORDER BY clause. Default: 'updated DESC'."
    )
    fields: Optional[str] = Field(
        default="key,summary,status,priority,issuetype,project,created,updated,duedate",
        description="Comma-separated Jira fields to return."
    )
    summary_only: bool = Field(
        default=False,
        description="Return grouped counts instead of raw tickets."
    )


class AggregateJiraDataInput(BaseModel):
    """Input for aggregating stored Jira data."""

    dataframe_name: str = Field(
        default="jira_issues",
        description="Name of the DataFrame to aggregate"
    )
    group_by: List[str] = Field(
        description="Columns to group by, e.g. ['assignee_name', 'status']"
    )
    aggregations: Dict[str, str] = Field(
        default={"key": "count"},
        description=(
            "Aggregations to perform. Format: {column: agg_func}. "
            "Example: {'key': 'count', 'story_points': 'sum'}"
        )
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="Column to sort results by"
    )
    ascending: bool = Field(
        default=False,
        description="Sort order"
    )


class TransitionIssueInput(BaseModel):
    """Input for transitioning an issue."""
    issue: str = Field(description="Issue key or id")
    transition: Union[str, int] = Field(description="Transition id or name (e.g., '5' or 'Done')")
    fields: Optional[Dict[str, Any]] = Field(default=None, description="Extra fields to set on transition")
    assignee: Optional[Dict[str, Any]] = Field(default=None, description="Assignee dict, e.g., {'name': 'pm_user'}")
    resolution: Optional[Dict[str, Any]] = Field(default=None, description="Resolution dict, e.g., {'id': '3'}")


class AddAttachmentInput(BaseModel):
    """Input for adding an attachment to an issue."""
    issue: str = Field(description="Issue key or id")
    attachment: str = Field(description="Path to attachment file on disk")


class AssignIssueInput(BaseModel):
    """Input for assigning an issue to a user."""
    issue: str = Field(description="Issue key or id")
    assignee: str = Field(description="Account id or username (depends on Jira cloud/server)")


class CreateIssueInput(BaseModel):
    """Input for creating a new issue."""
    project: str = Field(
        default="NAV",
        description="Project key, e.g. 'NAV' or project id"
    )
    summary: str = Field(
        description="Issue summary/title"
    )
    issuetype: str = Field(
        default="Task",
        description="Issue type, e.g. 'Task', 'Story', 'Bug', 'Epic', 'Sub-task'"
    )
    description: Optional[str] = Field(
        default=None,
        description="Issue description"
    )
    assignee: Optional[str] = Field(
        default=None,
        description="Assignee account ID or username"
    )
    priority: Optional[Literal["Highest", "High", "Medium", "Low", "Lowest"]] = Field(
        default=None,
        description="Priority"
    )
    labels: Optional[List[str]] = Field(
        default=None,
        description="Labels list, e.g. ['backend', 'urgent']"
    )
    components: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of component IDs (not names). "
            "Use jira_get_components(project) to find IDs first."
        )
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in YYYY-MM-DD format",
        json_schema_extra={"x-exclude-form": True}
    )
    parent: Optional[str] = Field(
        default=None,
        description="Parent issue key for sub-tasks or stories under epics",
        json_schema_extra={"x-exclude-form": True}
    )
    original_estimate: Optional[str] = Field(
        default=None,
        description="Original time estimate, e.g. '8h', '2d', '30m'"
    )
    # Generic fields for any other issue data
    fields: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional fields dict for custom or less common fields",
        json_schema_extra={"x-exclude-form": True}
    )


class UpdateIssueInput(BaseModel):
    """Input for updating an existing issue."""
    issue: str = Field(description="Issue key or id")
    summary: Optional[str] = Field(default=None, description="New summary")
    description: Optional[str] = Field(default=None, description="New description")
    assignee: Optional[Dict[str, Any]] = Field(default=None, description="New assignee dict, e.g. {'accountId': '...'}")

    # New fields
    acceptance_criteria: Optional[str] = Field(
        default=None,
        description="Acceptance criteria text (often stored in a custom field)"
    )
    original_estimate: Optional[str] = Field(
        default=None,
        description="Original time estimate, e.g. '2h', '1d', '30m'"
    )
    time_tracking: Optional[Dict[str, str]] = Field(
        default=None,
        description="Time tracking dict, e.g. {'originalEstimate': '2h', 'remainingEstimate': '1h'}"
    )
    affected_versions: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Affected versions list, e.g. [{'name': '1.0'}, {'name': '2.0'}]"
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in YYYY-MM-DD format"
    )
    labels: Optional[List[str]] = Field(
        default=None,
        description="Labels list, e.g. ['backend', 'priority']"
    )
    issuetype: Optional[Dict[str, str]] = Field(
        default=None,
        description="Issue type dict, e.g. {'name': 'Bug'} or {'id': '10001'}"
    )
    priority: Optional[Dict[str, str]] = Field(
        default=None,
        description="Priority dict, e.g. {'name': 'High'} or {'id': '2'}"
    )

    # Generic fields for any other updates
    fields: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary field updates dict")


class FindIssuesByAssigneeInput(BaseModel):
    """Input for finding issues assigned to a given user."""
    assignee: str = Field(description="Assignee identifier (e.g., 'admin' or accountId)")
    project: Optional[str] = Field(default=None, description="Restrict to project key")
    max_results: int = Field(default=50, description="Max results")


class GetTransitionsInput(BaseModel):
    """Input for getting available transitions for an issue."""
    issue: str = Field(description="Issue key or id")
    expand: Optional[str] = Field(default=None, description="Expand options, e.g. 'transitions.fields'")


class AddCommentInput(BaseModel):
    """Input for adding a comment to an issue."""
    issue: str = Field(description="Issue key or id")
    body: str = Field(description="Comment body text")
    is_internal: bool = Field(default=False, description="If true, mark as internal (Service Desk)")
    attachments: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of file paths (images or other files) to attach to the issue "
            "alongside this comment. Files are attached at the issue level."
        ),
    )


class AddWorklogInput(BaseModel):
    """Input for adding a worklog to an issue."""
    issue: str = Field(description="Issue key or id")
    time_spent: str = Field(description="Time spent, e.g. '2h', '30m'")
    comment: Optional[str] = Field(default=None, description="Worklog comment")
    started: Optional[str] = Field(default=None, description="Date started (ISO-8601 or similar)")


class GetIssueTypesInput(BaseModel):
    """Input for listing issue types."""
    project: Optional[str] = Field(
        default=None,
        description="Project key to filter by. If omitted, returns all available types."
    )


class SearchUsersInput(BaseModel):
    """Input for searching users."""
    user: Optional[str] = Field(default=None, description="String to match usernames, name or email against.")
    start_at: int = Field(default=0, description="Index of the first user to return.")
    max_results: int = Field(default=50, description="Maximum number of users to return.")
    include_active: bool = Field(default=True, description="True to include active users.")
    include_inactive: bool = Field(default=False, description="True to include inactive users.")
    query: Optional[str] = Field(default=None, description="Search term. It can just be the email.")


class GetProjectsInput(BaseModel):
    """Input for listing projects."""
    pass


class VerifyAuthInput(BaseModel):
    """Input for verifying Jira authentication."""
    pass


class GetComponentsInput(BaseModel):
    """Input for listing project components."""
    project: Optional[str] = Field(
        default=None,
        description="Project key, e.g. 'NAV'. Falls back to default project if omitted."
    )


class GetComponentByNameInput(BaseModel):
    """Input for finding a component by name."""
    name: str = Field(description="Component name to search for (case-insensitive match).")
    project: Optional[str] = Field(
        default=None,
        description="Project key. Falls back to default project if omitted."
    )


class TicketIdInput(BaseModel):
    """Input for generic ticket operations."""
    issue: str = Field(description="Issue key or id")


class FindUserInput(BaseModel):
    """Input for finding a user."""
    email: str = Field(description="User email address or query string")


class TagInput(BaseModel):
    """Input for tag operations."""
    issue: str = Field(description="Issue key or id")
    tag: str = Field(description="Tag (label) name")


class ChangeAssigneeInput(BaseModel):
    """Input for changing assignee."""
    issue: str = Field(description="Issue key or id")
    assignee: str = Field(description="New assignee (account ID or username)")


class ListHistoryInput(BaseModel):
    """Input for listing history."""
    issue: str = Field(description="Issue key or id")



class ChangeReporterInput(BaseModel):
    """Input for changing the reporter of an issue."""
    issue: str = Field(description="Issue key or id (e.g. 'NAV-6213')")
    email: str = Field(description="Email address of the new reporter")


class AddComponentInput(BaseModel):
    """Input for adding a component to an issue by name."""
    issue: str = Field(description="Issue key or id (e.g. 'NAV-6213')")
    component_name: str = Field(description="Component name (case-insensitive, e.g. 'Backend')")
    project: Optional[str] = Field(default=None, description="Project key. Falls back to default project if omitted.")


class AddWatcherInput(BaseModel):
    """Input for adding a watcher to an issue."""
    issue: str = Field(description="Issue key or id (e.g. 'NAV-6213')")
    email: str = Field(description="Email address of the user to add as watcher")


class SetAcceptanceCriteriaInput(BaseModel):
    """Input for setting acceptance criteria on an issue."""
    issue: str = Field(description="Issue key or id (e.g. 'NAV-6213')")
    criteria: List[str] = Field(description="List of acceptance criteria items (each item becomes a checklist entry)")
    custom_field: Optional[str] = Field(
        default=None,
        description="Custom field ID for acceptance criteria (e.g. 'customfield_10021'). Auto-detected if omitted."
    )


class ConfigureClientInput(BaseModel):
    """Input for re-configuring the Jira client."""
    username: Optional[str] = Field(default=None, description="New username (email)")
    password: Optional[str] = Field(default=None, description="New password or API token")
    token: Optional[str] = Field(default=None, description="New Personal Access Token")
    auth_type: Optional[str] = Field(default=None, description="Authentication type: 'basic_auth', 'token_auth', etc.")
    server_url: Optional[str] = Field(default=None, description="New server URL")


class JiraToolkit(AbstractToolkit):
    """Toolkit for interacting with Jira via pycontribs/jira.

    Provides methods for:
    - Getting an issue
    - Searching issues
    - Transitioning issues
    - Adding attachments
    - Assigning issues
    - Creating and updating issues
    - Finding issues by assignee
    - Counting issues
    - Aggregating stored Jira data

    Authentication modes:
        - basic_auth: username + password
        - token_auth: personal access token (preferred for Jira Cloud)
        - oauth: OAuth1 parameters

    Configuration precedence for init parameters:
        1) Explicit kwargs to __init__
        2) navconfig.config keys (if available)
        3) Environment variables

    Recognized config/env keys:
        JIRA_SERVER_URL, JIRA_AUTH_TYPE, JIRA_USERNAME, JIRA_PASSWORD, JIRA_TOKEN,
        JIRA_OAUTH_CONSUMER_KEY, JIRA_OAUTH_KEY_CERT, JIRA_OAUTH_ACCESS_TOKEN,
        JIRA_OAUTH_ACCESS_TOKEN_SECRET, JIRA_DEFAULT_PROJECT

    Field presets for efficiency:
        count: key,assignee,reporter,status,priority,issuetype,project,created
        list: key,summary,assignee,status,priority,issuetype,project,created,updated
        analysis: key,summary,description,assignee,reporter,status,priority,issuetype,project,created,updated,resolutiondate,duedate,labels,components,timeoriginalestimate,timespent,customfield_10016
        all: *all

    Usage:
    -----
    # For counts - efficient, minimal context
    jira.jira_count_issues(
        jql="project = NAV AND status = Open",
        group_by=["assignee", "status"]
    )

    # For analysis - store in DataFrame
    jira.jira_search_issues(
        jql="project = NAV",
        max_results=1000,
        fields="key,assignee,status,created",  # Only what you need!
        store_as_dataframe=True,
        summary_only=True  # Just counts in response
    )

    """  # noqa

    # Expose the default input schema as metadata (optional)
    input_class = JiraInput
    _tool_manager: Optional[ToolManager] = None

    def __init__(
        self,
        server_url: Optional[str] = None,
        auth_type: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        oauth_consumer_key: Optional[str] = None,
        oauth_key_cert: Optional[str] = None,
        oauth_access_token: Optional[str] = None,
        oauth_access_token_secret: Optional[str] = None,
        default_project: Optional[str] = None,
        credential_resolver: Any = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        # Pull defaults from navconfig or env vars
        def _cfg(key: str, default: Optional[str] = None) -> Optional[str]:
            if (nav_config is not None) and hasattr(nav_config, "get"):
                val = nav_config.get(key)
                if val is not None:
                    return str(val)
            return os.getenv(key, default)

        self.logger = logging.getLogger(__name__)

        # Determine auth_type FIRST so oauth2_3lo can skip server_url validation.
        _configured_auth = auth_type or _cfg("JIRA_AUTH_TYPE")
        if _configured_auth:
            self.auth_type = _configured_auth.lower()
        else:
            # Defer until we know server_url (resolved below).
            self.auth_type = None  # type: ignore[assignment]

        # For oauth2_3lo the server URL is resolved per-user at runtime via the
        # CredentialResolver, so ``server_url`` is optional.
        self.server_url = server_url or _cfg("JIRA_INSTANCE") or ""
        if self.auth_type != "oauth2_3lo" and not self.server_url:
            raise ValueError(
                "Jira server_url is required (e.g., https://your.atlassian.net)"
            )

        if self.auth_type is None:
            # Legacy heuristic: Jira Cloud defaults to basic_auth, server to token_auth.
            if "atlassian.net" in self.server_url:
                self.auth_type = "basic_auth"
            else:
                self.auth_type = "token_auth"

        self.username = username or _cfg("JIRA_USERNAME")
        self.password = password or _cfg("JIRA_PASSWORD") or _cfg("JIRA_API_TOKEN")
        self.token = token or _cfg("JIRA_SECRET_TOKEN")

        self.oauth_consumer_key = oauth_consumer_key or _cfg("JIRA_OAUTH_CONSUMER_KEY")
        self.oauth_key_cert = oauth_key_cert or _cfg("JIRA_OAUTH_KEY_CERT")
        self.oauth_access_token = oauth_access_token or _cfg("JIRA_OAUTH_ACCESS_TOKEN")
        self.oauth_access_token_secret = oauth_access_token_secret or _cfg("JIRA_OAUTH_ACCESS_TOKEN_SECRET")

        self.default_project = default_project or _cfg("JIRA_DEFAULT_PROJECT", "NAV")
        self.default_issue_type = _cfg("JIRA_DEFAULT_ISSUE_TYPE", "Task")
        # HTTP timeout (seconds) applied to every Jira request. Prevents a
        # stuck network call from pinning an asyncio.to_thread worker
        # forever — which, combined with the Telegram wrapper agent lock,
        # freezes the bot. Honored by pycontribs JIRA via the ``timeout``
        # kwarg (see JIRA.__init__).
        try:
            self.request_timeout: float = float(
                _cfg("JIRA_REQUEST_TIMEOUT", "30") or 30
            )
        except (TypeError, ValueError):
            self.request_timeout = 30.0
        self.default_labels = _parse_csv(_cfg("JIRA_DEFAULT_LABELS", "") or "")
        self.default_components = _parse_csv(_cfg("JIRA_DEFAULT_COMPONENTS", "") or "")
        self.default_due_date_offset = _cfg("JIRA_DEFAULT_DUE_DATE_OFFSET")
        self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")

        # OAuth 2.0 (3LO) per-user mode: defer client creation to _pre_execute.
        self.credential_resolver = credential_resolver
        if self.auth_type == "oauth2_3lo":
            if self.credential_resolver is None:
                raise ValueError(
                    "oauth2_3lo requires a credential_resolver"
                )
            self.jira = None  # resolved per-call in _pre_execute
            # Per-user JIRA client cache: {"{channel}:{user_id}": (client, token_hash)}
            self._client_cache: Dict[str, tuple] = {}
        else:
            # Legacy: create the client immediately.
            self._set_jira_client()

    def _set_jira_client(self):
        """Set the internal Jira client instance."""
        self.jira = self._init_jira_client()

    # -----------------------------
    # Client init helpers
    # -----------------------------
    def _init_jira_client(self) -> JIRA:
        """Instantiate the pycontribs JIRA client according to auth_type."""
        options: Dict[str, Any] = {
            "server": self.server_url,
            "verify": False,
            'headers': {
                'Accept-Encoding': 'gzip, deflate'
            }
        }

        if self.auth_type == "basic_auth":
            if not (self.username and self.password):
                raise ValueError("basic_auth requires username and password")
            return JIRA(
                options=options,
                basic_auth=(self.username, self.password),
                timeout=self.request_timeout,
            )

        if self.auth_type == "token_auth":
            if not self.token:
                # Some setups use username+token via basic; keep token_auth strict here
                raise ValueError("token_auth requires a Personal Access Token")
            return JIRA(
                options=options,
                token_auth=self.token,
                timeout=self.request_timeout,
            )

        if self.auth_type == "oauth":
            # oauth_key_cert can be the PEM content or a file path to PEM
            key_cert = self._read_key_cert(self.oauth_key_cert)
            oauth_dict = {
                "access_token": self.oauth_access_token,
                "access_token_secret": self.oauth_access_token_secret,
                "consumer_key": self.oauth_consumer_key,
                "key_cert": key_cert,
            }
            if not all([oauth_dict.get("access_token"), oauth_dict.get("access_token_secret"),
                        oauth_dict.get("consumer_key"), oauth_dict.get("key_cert")]):
                raise ValueError("oauth requires consumer_key, key_cert, access_token, access_token_secret")
            return JIRA(
                options=options,
                oauth=oauth_dict,
                timeout=self.request_timeout,
            )

        raise ValueError(f"Unsupported auth_type: {self.auth_type}")

    # -----------------------------
    # OAuth 2.0 (3LO) per-user client
    # -----------------------------
    _CLIENT_CACHE_MAX_SIZE: int = 100
    # Scopes requested during the OAuth consent flow — mirrors
    # ``parrot.auth.jira_oauth.DEFAULT_SCOPES`` to avoid a hard import.
    _OAUTH_SCOPES: tuple = (
        "read:jira-work",
        "write:jira-work",
        "read:jira-user",
        "offline_access",
    )

    def _init_jira_client_from_token(self, token_set: Any) -> JIRA:
        """Construct a JIRA client backed by a user's OAuth 2.0 access token.

        The pycontribs ``jira`` library does not expose Bearer auth as a
        first-class option, but it honors any headers passed via
        ``options['headers']``.  We also point ``server`` at the Atlassian
        gateway derived from the ``cloud_id``.
        """
        options: Dict[str, Any] = {
            "server": token_set.api_base_url,
            "verify": True,
            "headers": {
                "Authorization": f"Bearer {token_set.access_token}",
                "Accept-Encoding": "gzip, deflate",
            },
        }
        return JIRA(options=options, timeout=self.request_timeout)

    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        """Resolve per-user Jira credentials for ``oauth2_3lo`` mode.

        For legacy ``basic_auth`` / ``token_auth`` / ``oauth`` modes this is a
        no-op — the JIRA client created in ``__init__`` is reused.

        Raises:
            AuthorizationRequired: When the user has not authorized yet.
        """
        if self.auth_type != "oauth2_3lo":
            return None

        perm_ctx = kwargs.get("_permission_context")
        if perm_ctx is None:
            raise AuthorizationRequired(
                tool_name=tool_name,
                message=(
                    "Permission context is required for Jira OAuth 2.0 (3LO) "
                    "tools. The call must be routed through ToolManager with "
                    "a populated PermissionContext."
                ),
                provider="jira",
                scopes=list(self._OAUTH_SCOPES),
            )

        user_id = getattr(perm_ctx, "user_id", None)
        channel = getattr(perm_ctx, "channel", None) or "unknown"
        if not user_id:
            raise AuthorizationRequired(
                tool_name=tool_name,
                message="Cannot resolve Jira credentials without a user_id.",
                provider="jira",
                scopes=list(self._OAUTH_SCOPES),
            )

        user_key = f"{channel}:{user_id}"
        token_set = await self.credential_resolver.resolve(channel, user_id)
        if token_set is None:
            try:
                auth_url = await self.credential_resolver.get_auth_url(
                    channel, user_id
                )
            except NotImplementedError:
                auth_url = None
            raise AuthorizationRequired(
                tool_name=tool_name,
                message="Please authorize your Jira account to use this tool.",
                auth_url=auth_url,
                provider="jira",
                scopes=list(self._OAUTH_SCOPES),
            )

        # Cache JIRA clients per user keyed by token fingerprint so token
        # rotations force a client rebuild.  Python's built-in hash() is
        # non-deterministic across process restarts (PYTHONHASHSEED), so we
        # use a stable string fingerprint instead.
        _at = getattr(token_set, "access_token", "")
        token_hash = (_at[:16] + _at[-8:]) if len(_at) > 24 else _at
        cached = self._client_cache.get(user_key)
        if cached is not None and cached[1] == token_hash:
            self.jira = cached[0]
            return None

        client = self._init_jira_client_from_token(token_set)
        # Trim cache if it has grown past the bound (simple eviction — drop
        # the oldest insertion).  Python 3.7+ dicts preserve insertion order.
        if len(self._client_cache) >= self._CLIENT_CACHE_MAX_SIZE:
            oldest_key = next(iter(self._client_cache))
            self._client_cache.pop(oldest_key, None)
        self._client_cache[user_key] = (client, token_hash)
        self.jira = client
        return None

    @staticmethod
    def _read_key_cert(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        # If looks like a path and exists, read it; else assume it's PEM content
        if os.path.exists(value):
            with open(value, "r", encoding="utf-8") as f:
                return f.read()
        return value

    def set_tool_manager(self, manager: ToolManager):
        """Set the ToolManager reference for DataFrame sharing."""
        self._tool_manager = manager

    # -----------------------------
    # Utility
    # -----------------------------
    def _issue_to_dict(self, issue_obj: Any) -> Dict[str, Any]:
        # pycontribs Issue objects have a .raw (dict) and .key
        try:
            raw = getattr(issue_obj, "raw", None)
            if isinstance(raw, dict):
                return raw
            # Fallback minimal structure
            return {"id": getattr(issue_obj, "id", None), "key": getattr(issue_obj, "key", None)}
        except Exception:
            return {"id": getattr(issue_obj, "id", None), "key": getattr(issue_obj, "key", None)}

    # ---- structured output helpers ----
    def _import_string(self, path: str):
        """Import a dotted module path and return the attribute/class designated by the last name in the path."""
        module_path, _, attr = path.rpartition(".")
        if not module_path:
            raise ValueError(f"Invalid model_path '{path}', expected 'package.module:Class' style")
        module = importlib.import_module(module_path)
        return getattr(module, attr)

    def _get_by_path(self, data: Dict[str, Any], path: str, strict: bool = False) -> Any:
        """Get a value from a nested dict by dot-separated path. If strict and path not found, raises KeyError."""
        cur: Any = data
        for part in path.split('.'):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif strict:
                raise KeyError(f"Path '{path}' not found at '{part}'")
            else:
                return None
        return cur

    def _quote_jql_value(self, value: Union[str, int, float]) -> str:
        """Quote a JQL value, escaping special characters.

        Jira's JQL treats characters like '@' as reserved when unquoted. This helper wraps
        values in double quotes and escapes backslashes, double quotes, and newlines so that
        user-provided identifiers (e.g., emails) are always valid JQL literals.
        """

        text = str(value)
        escaped = (
            text.replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
        return f'"{escaped}"'

    def _build_assignee_jql(
        self, assignee: str, project: Optional[str] = None, default_project: Optional[str] = None
    ) -> str:
        """Construct a JQL query for an assignee, quoting values as needed."""

        jql = f"assignee={self._quote_jql_value(assignee)}"
        if project or default_project:
            proj = project or default_project
            jql = f"project={proj} AND ({jql})"
        return jql

    # Matches a trailing ORDER BY clause (case-insensitive). JQL only allows
    # ORDER BY at the end of the query, so stripping it leaves the filters.
    _ORDER_BY_RE = re.compile(r"\border\s+by\b.*$", re.IGNORECASE | re.DOTALL)

    def _ensure_bounded_jql(self, jql: Optional[str]) -> str:
        """Return a bounded JQL, injecting `project = <default>` when needed.

        Atlassian's `/search/jql` endpoint rejects queries that have no filter
        clauses (e.g. empty string, or just `order by created desc`) with
        "Unbounded JQL queries are not allowed here". We guard against that by
        stripping any trailing ORDER BY, and if nothing remains:

        - prepend `project = <default_project>` when one is configured, or
        - raise ValueError asking the caller to add a restriction.

        The returned string preserves the original ORDER BY suffix.
        """

        raw = (jql or "").strip()
        without_order = self._ORDER_BY_RE.sub("", raw).strip()
        if without_order:
            return raw

        if self.default_project:
            bounded = f"project = {self.default_project}"
            # Re-attach the ORDER BY clause, if any was present.
            order_match = self._ORDER_BY_RE.search(raw)
            if order_match:
                bounded = f"{bounded} {order_match.group(0).strip()}"
            self.logger.warning(
                "Unbounded JQL received (%r); bounding with default project %s",
                jql, self.default_project
            )
            return bounded

        raise ValueError(
            "Unbounded JQL is not allowed by Jira Cloud. Add at least one filter "
            "clause (e.g. 'project = NAV', 'assignee = currentUser()', or a date "
            "range) before ORDER BY."
        )

    def _project_include(self, data: Dict[str, Any], include: List[str], strict: bool = False) -> Dict[str, Any]:
        """Return a dict including only the specified dot-paths, preserving nested structure."""
        out: Dict[str, Any] = {}
        for path in include:
            val = self._get_by_path(data, path, strict=strict)
            # Build nested structure mirroring the path
            cursor = out
            parts = path.split('.')
            for i, p in enumerate(parts):
                if i == len(parts) - 1:
                    cursor[p] = val
                else:
                    cursor = cursor.setdefault(p, {})
        return out

    def _project_mapping(self, data: Dict[str, Any], mapping: Dict[str, str], strict: bool = False) -> Dict[str, Any]:
        """Return a dict with keys renamed/flattened according to mapping {dest_key: dot_path}."""
        return {dest: self._get_by_path(data, src, strict=strict) for dest, src in mapping.items()}

    def _apply_structured_output(self, raw: Dict[str, Any], opts: Optional[StructuredOutputOptions]) -> Dict[str, Any]:
        """Apply include/mapping/model to raw dict according to opts, returning the transformed dict."""
        if not opts:
            return raw
        payload = raw
        if opts.mapping:
            payload = self._project_mapping(raw, opts.mapping, strict=opts.strict)
        elif opts.include:
            payload = self._project_include(raw, opts.include, strict=opts.strict)
        if opts.model_path:
            _model = self._import_string(opts.model_path)
            try:
                # pydantic v2
                obj = _model.model_validate(payload)  # type: ignore[attr-defined]
                return obj.model_dump()  # type: ignore[attr-defined]
            except AttributeError:
                # pydantic v1 fallback
                obj = _model.parse_obj(payload)
                return obj.dict()
        return payload

    def _ensure_structured(
        self,
        opts: Optional[Union[StructuredOutputOptions, Dict[str, Any]]]
    ) -> Optional[StructuredOutputOptions]:
        """Ensure opts is a StructuredOutputOptions instance if provided as a dict."""
        if opts is None:
            return None
        if isinstance(opts, StructuredOutputOptions):
            return opts
        if isinstance(opts, dict):
            try:
                return StructuredOutputOptions(**opts)
            except AttributeError:
                return StructuredOutputOptions.model_validate(opts)
        raise ValueError("structured must be a StructuredOutputOptions instance or a dict")

    def _extract_field_history(self, changelog_entries, field_name: str):
        """Return normalized history events for a single field (e.g., 'assignee', 'status')."""
        events = []
        for h in changelog_entries or []:
            created = h.get("created")
            author = h.get("author") or {}
            for item in h.get("items") or []:
                if item.get("field") == field_name:
                    events.append({
                        "created": created,
                        "changed_by": {
                            "accountId": author.get("accountId"),
                            "displayName": author.get("displayName"),
                        },
                        "from": item.get("from"),
                        "fromString": item.get("fromString"),
                        "to": item.get("to"),
                        "toString": item.get("toString"),
                    })
        # ISO timestamps sort lexicographically OK
        events.sort(key=lambda e: e["created"] or "")
        return events

    async def _get_full_changelog(self, issue: str, page_size: int = 100):
        """
        Fetch full changelog via /issue/{key}/changelog pagination.
        Works in Jira Cloud and typically in DC/Server too (depending on API version).
        """
        def _fetch_page(start_at: int):
            # _get_json is provided by pycontribs/jira client (even though it's "internal")
            return self.jira._get_json(  # noqa: SLF001 (if you lint for private usage)
                f"issue/{issue}/changelog",
                params={"startAt": start_at, "maxResults": page_size},
            )

        start_at = 0
        all_entries = []

        while True:
            page = await asyncio.to_thread(_fetch_page, start_at)

            # Jira Cloud v3 uses "values"; some responses use "histories"
            values = page.get("values") or page.get("histories") or []
            if not values:
                break

            all_entries.extend(values)

            # Cloud v3 provides isLast/total/maxResults/startAt
            is_last = page.get("isLast")
            total = page.get("total")
            max_results = page.get("maxResults", page_size)
            cur_start = page.get("startAt", start_at)

            if is_last is True:
                break
            if total is not None and (cur_start + max_results) >= total:
                break

            start_at = cur_start + max_results

        return all_entries

    # -----------------------------
    # Tools (public async methods)
    # -----------------------------
    @tool_schema(GetIssueInput)
    async def jira_get_issue(
        self,
        issue: str,
        fields: Optional[str] = None,
        expand: Optional[str] = None,
        structured: Optional[StructuredOutputOptions] = None,
        include_history: bool = False,
        history_page_size: int = 100,
    ) -> Union[Dict[str, Any], Any]:
        """Get a Jira issue by key or id.

        Example: issue = jira.issue('JRA-1330')

        If `structured` is provided, the output will be transformed according to the options.
        """
        def _run():
            return self.jira.issue(issue, fields=fields, expand=expand)

        obj = await asyncio.to_thread(_run)
        raw = self._issue_to_dict(obj)
        structured = self._ensure_structured(structured)

        if include_history:
            changelog_entries = await self._get_full_changelog(issue, page_size=history_page_size)
            # Flatten history into a list of events
            history_events = []
            for entry in changelog_entries:
                author = entry.get("author") or {}
                items = []
                for item in entry.get("items") or []:
                    items.append({
                        "field": item.get("field"),
                        "fromString": item.get("fromString"),
                        "toString": item.get("toString")
                    })

                if items:
                    history_events.append({
                        "author": author.get("displayName"),
                        "created": entry.get("created"),
                        "items": items
                    })

            raw["history"] = history_events
            raw["_changelog_count"] = len(changelog_entries)

        return self._apply_structured_output(raw, structured) if structured else raw

    @requires_permission('jira.write')
    @tool_schema(TransitionIssueInput)
    async def jira_transition_issue(
        self,
        issue: str,
        transition: Union[str, int],
        fields: Optional[Dict[str, Any]] = None,
        assignee: Optional[Dict[str, Any]] = None,
        resolution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Transition a Jira issue. Requires jira.write permission.

        Automatically sets 8h original estimate for issues without one
        when transitioning to 'To Do', 'TODO', or 'In Progress'.

        The transition argument accepts a transition id (e.g. '5'), a transition
        action name (e.g. 'Start Progress'), or a target status name (e.g. 'Done').
        The available transitions depend on the project's workflow — if the
        requested value cannot be resolved, this tool raises an error listing
        every valid option so you can retry with a correct one.

        Example:
            jira.transition_issue(issue, '5', assignee={'name': 'pm_user'}, resolution={'id': '3'})
        """
        # Common aliases: maps a user-facing intent to transition names or
        # target statuses that may represent it across different workflows.
        TRANSITION_ALIASES: Dict[str, tuple] = {
            "done": ("done", "close", "closed", "resolve", "resolved", "complete", "completed", "mark as done", "finish", "finished"),
            "in progress": ("in progress", "in-progress", "start progress", "start", "begin", "begin work", "work on it"),
            "to do": ("to do", "todo", "reopen", "reopened", "open", "backlog", "back to to do"),
            "cancelled": ("cancelled", "canceled", "cancel", "wont do", "won't do", "won't fix", "wont fix"),
            "blocked": ("blocked", "block", "on hold"),
        }
        # Statuses that require an estimate
        ESTIMATE_REQUIRED_TRANSITIONS = {'to do', 'todo', 'in progress', 'in-progress'}
        DEFAULT_ESTIMATE = "8h"

        # Check if this transition needs an estimate check
        transition_name = str(transition).lower().strip()
        needs_estimate_check = transition_name in ESTIMATE_REQUIRED_TRANSITIONS

        # If transitioning to TODO/In Progress, check if issue has original estimate
        if needs_estimate_check:
            current_issue = await self.jira_get_issue(issue)
            raw = current_issue.get("raw", current_issue)
            timetracking = raw.get("fields", {}).get("timetracking", {}) if isinstance(raw, dict) else {}
            original_estimate = timetracking.get("originalEstimate") if timetracking else None

            if not original_estimate:
                # Set default 8h estimate before transitioning
                self.logger.info(f"Setting default {DEFAULT_ESTIMATE} estimate for {issue} before transition")
                await self.jira_update_issue(
                    issue=issue,
                    original_estimate=DEFAULT_ESTIMATE
                )

        # Build kwargs as accepted by pycontribs
        kwargs: Dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if assignee:
            kwargs["assignee"] = assignee
        if resolution:
            kwargs["resolution"] = resolution

        # Resolve transition: pycontribs matches transition *action* names,
        # not target status names.  We look up available transitions and
        # match by action name OR target status name (case-insensitive).
        resolved_transition: Optional[Union[str, int]] = None
        available: List[Dict[str, Any]] = []
        if str(transition).isdigit():
            resolved_transition = transition
        else:
            available = await self.jira_get_transitions(issue)
            target = str(transition).lower().strip()
            aliases = set(TRANSITION_ALIASES.get(target, (target,)))
            aliases.add(target)

            # First pass: exact match on action name or target status
            for t in available:
                t_name = (t.get("name") or "").lower().strip()
                t_status = (t.get("to", {}).get("name", "") if isinstance(t.get("to"), dict) else "").lower().strip()
                if t_name in aliases or t_status in aliases:
                    resolved_transition = t["id"]
                    self.logger.info(
                        f"Resolved transition '{transition}' -> id {resolved_transition} "
                        f"(name='{t.get('name')}', to='{t.get('to', {}).get('name', '')}')"
                    )
                    break

            # Second pass: substring match as a last resort
            if resolved_transition is None:
                for t in available:
                    t_name = (t.get("name") or "").lower().strip()
                    t_status = (t.get("to", {}).get("name", "") if isinstance(t.get("to"), dict) else "").lower().strip()
                    if any(a and (a in t_name or a in t_status) for a in aliases):
                        resolved_transition = t["id"]
                        self.logger.info(
                            f"Resolved transition '{transition}' via substring -> id {resolved_transition} "
                            f"(name='{t.get('name')}', to='{t.get('to', {}).get('name', '')}')"
                        )
                        break

        if resolved_transition is None:
            options = [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "to": (t.get("to", {}) or {}).get("name"),
                }
                for t in available
            ]
            raise ValueError(
                f"Invalid transition '{transition}' for issue {issue}. "
                f"Available transitions: {options}. "
                "Retry with one of the listed 'id', 'name', or 'to' values."
            )

        def _run():
            return self.jira.transition_issue(issue, resolved_transition, **kwargs)

        await asyncio.to_thread(_run)
        # Return the latest state of the issue
        return await self.jira_get_issue(issue)

    @requires_permission('jira.write')
    @tool_schema(AddAttachmentInput)
    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]:
        """Add an attachment to an issue. Requires jira.write permission.

        Example: jira.add_attachment(issue=issue, attachment='/path/to/file.txt')
        """
        def _run():
            return self.jira.add_attachment(issue=issue, attachment=attachment)

        await asyncio.to_thread(_run)
        return {"ok": True, "issue": issue, "attachment": attachment}

    @requires_permission('jira.write')
    @tool_schema(AssignIssueInput)
    async def jira_assign_issue(self, issue: str, assignee: str) -> Dict[str, Any]:
        """Assign an issue to a user. Requires jira.write permission.

        Accepts an email address or an accountId.

        Examples:
            jira_assign_issue(issue='NAV-123', assignee='user@example.com')
            jira_assign_issue(issue='NAV-123', assignee='60d1f2a3b4c5e6f7')
        """
        account_id = await self._resolve_account_id(assignee)

        def _run():
            return self.jira.assign_issue(issue, account_id)

        await asyncio.to_thread(_run)
        return {"ok": True, "issue": issue, "assignee": account_id}

    @requires_permission('jira.write')
    @tool_schema(CreateIssueInput)
    async def jira_create_issue(
        self,
        project: Optional[str] = None,
        summary: str = "",
        issuetype: Optional[str] = None,
        description: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        labels: Optional[List[str]] = None,
        components: Optional[List[str]] = None,
        due_date: Optional[str] = None,
        parent: Optional[str] = None,
        original_estimate: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new issue. Requires jira.write permission.

        Omitted fields fall back to configured defaults (JIRA_DEFAULT_* env vars).

        Assignee accepts an email address or accountId — emails are resolved automatically.
        Components accept names or IDs — names are resolved automatically.

        Examples:
            # Create a task with only a summary (uses all defaults)
            jira_create_issue(summary='Fix login bug')

            # Create a bug assigned by email
            jira_create_issue(
                project='NAV',
                summary='Login button not working',
                issuetype='Bug',
                assignee='dev@example.com',
                priority='High',
                original_estimate='4h'
            )

            # Create a story with components by name
            jira_create_issue(
                project='NAV',
                summary='Add user profile page',
                issuetype='Story',
                labels=['frontend', 'user-experience'],
                components=['Backend', 'Assembly360'],
                original_estimate='2d'
            )

            # Create a sub-task
            jira_create_issue(
                project='NAV',
                summary='Design mockup',
                issuetype='Sub-task',
                parent='NAV-123'
            )
        """
        # Apply configured defaults for omitted fields
        project = project or self.default_project or "NAV"
        issuetype = issuetype or self.default_issue_type or "Task"
        if labels is None and self.default_labels:
            labels = list(self.default_labels)
        if components is None and self.default_components:
            components = list(self.default_components)
        if due_date is None and self.default_due_date_offset:
            try:
                from datetime import timedelta
                offset_days = int(self.default_due_date_offset)
                due_date = (datetime.now() + timedelta(days=offset_days)).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                self.logger.warning(
                    "Invalid JIRA_DEFAULT_DUE_DATE_OFFSET: %s", self.default_due_date_offset
                )
        if original_estimate is None and self.default_estimate:
            original_estimate = self.default_estimate

        # Validate issuetype against the project's actual issue type scheme
        # so we return a useful error (with valid names) to the agent instead
        # of opaque "HTTP 400: The issue type selected is invalid.".
        canonical_issuetype = await self._validate_issue_type(project, issuetype)

        # Build fields dict
        issue_fields: Dict[str, Any] = {
            "project": {"key": project},
            "summary": summary,
            "issuetype": {"name": canonical_issuetype},
        }

        if description:
            issue_fields["description"] = description
        if assignee:
            account_id = await self._resolve_account_id(assignee)
            issue_fields["assignee"] = {"accountId": account_id}
        if priority:
            issue_fields["priority"] = {"name": priority}
        if labels:
            issue_fields["labels"] = labels
        if components:
            resolved = []
            for c in components:
                if c.isdigit():
                    resolved.append({"id": c})
                else:
                    comp = await self.jira_get_component_by_name(name=c, project=project)
                    resolved.append({"id": str(comp["id"])})
            issue_fields["components"] = resolved
        if due_date:
            issue_fields["duedate"] = due_date
        if parent:
            issue_fields["parent"] = {"key": parent}
        if original_estimate:
            issue_fields["timetracking"] = {"originalEstimate": original_estimate}

        # Merge with additional fields if provided
        if fields:
            issue_fields.update(fields)

        def _run():
            return self.jira.create_issue(fields=issue_fields)

        # Wrap the blocking call in wait_for so a stuck HTTP request cannot
        # hold the asyncio.to_thread worker (and, via the Telegram wrapper's
        # agent lock, the whole bot) forever. Budget slightly above the
        # underlying requests timeout so the HTTP layer errors first.
        try:
            obj = await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=self.request_timeout + 5,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Jira create_issue timed out after {self.request_timeout + 5:.0f}s "
                f"(project={project}, issuetype={canonical_issuetype})"
            ) from exc
        data = self._issue_to_dict(obj)
        return {"ok": True, "id": data.get("id"), "key": data.get("key"), "issue": data}

    @requires_permission('jira.write')
    @tool_schema(UpdateIssueInput)
    async def jira_update_issue(
        self,
        issue: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        assignee: Optional[Dict[str, Any]] = None,
        acceptance_criteria: Optional[str] = None,
        original_estimate: Optional[str] = None,
        time_tracking: Optional[Dict[str, str]] = None,
        affected_versions: Optional[List[Dict[str, str]]] = None,
        due_date: Optional[str] = None,
        labels: Optional[List[str]] = None,
        issuetype: Optional[Dict[str, str]] = None,
        priority: Optional[Dict[str, str]] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Update an existing issue. Requires jira.write permission.

        Examples:
            # Update summary and description
            jira_update_issue(issue='NAV-123', summary='New title', description='Updated desc')

            # Update assignee
            jira_update_issue(issue='NAV-123', assignee={'accountId': 'abc123'})

            # Update due date and labels
            jira_update_issue(issue='NAV-123', due_date='2025-01-15', labels=['backend', 'urgent'])

            # Update time tracking
            jira_update_issue(issue='NAV-123', time_tracking={'originalEstimate': '8h', 'remainingEstimate': '4h'})

            # Change issue type
            jira_update_issue(issue='NAV-123', issuetype={'name': 'Bug'})
        """
        update_kwargs: Dict[str, Any] = {}
        update_fields: Dict[str, Any] = {}

        # Standard fields
        if summary is not None:
            update_fields["summary"] = summary
        if description is not None:
            update_fields["description"] = description
        if assignee is not None:
            update_fields["assignee"] = assignee
        if due_date is not None:
            update_fields["duedate"] = due_date
        if labels is not None:
            update_fields["labels"] = labels
        if issuetype is not None:
            update_fields["issuetype"] = issuetype
        if priority is not None:
            update_fields["priority"] = priority
        if affected_versions is not None:
            update_fields["versions"] = affected_versions

        # Time tracking (special field)
        if time_tracking is not None:
            update_fields["timetracking"] = time_tracking
        elif original_estimate is not None:
            update_fields["timetracking"] = {"originalEstimate": original_estimate}

        # Acceptance criteria (often a custom field - common ones are customfield_10021 or customfield_10022)
        # This is instance-specific, so we'll try the common one or use fields dict
        if acceptance_criteria is not None:
            # Try common custom field IDs for acceptance criteria
            update_fields["customfield_10021"] = acceptance_criteria

        # Merge with arbitrary fields if provided
        if fields:
            update_fields.update(fields)

        if update_fields:
            update_kwargs["fields"] = update_fields

        def _run():
            # jira.issue returns Issue; then we call .update on it
            obj = self.jira.issue(issue)
            obj.update(**update_kwargs)
            return obj

        obj = await asyncio.to_thread(_run)
        return self._issue_to_dict(obj)

    @tool_schema(FindIssuesByAssigneeInput)
    async def jira_find_issues_by_assignee(
        self, assignee: str, project: Optional[str] = None, max_results: int = 50
    ) -> Dict[str, Any]:
        """Find issues assigned to a given user (thin wrapper over jira_search_issues).

        Example: jira.search_issues("assignee=admin")
        """

        jql = self._build_assignee_jql(assignee, project, self.default_project)
        return await self.jira_search_issues(jql=jql, max_results=max_results)

    @tool_schema(GetTransitionsInput)
    async def jira_get_transitions(
        self,
        issue: str,
        expand: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get available transitions for an issue.

        Example: jira.jira_get_transitions('JRA-1330')
        """
        def _run():
            return self.jira.transitions(issue, expand=expand)

        transitions = await asyncio.to_thread(_run)
        # transitions returns a list of dicts typically
        return transitions

    @requires_permission('jira.write')
    @tool_schema(AddCommentInput)
    async def jira_add_comment(
        self,
        issue: str,
        body: str,
        is_internal: bool = False,
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Add a comment to an issue, optionally attaching files. Requires jira.write permission.

        Example: jira.jira_add_comment('JRA-1330', 'This is a comment')
        Example with attachments:
            jira.jira_add_comment(
                'JRA-1330',
                'See attached screenshot',
                attachments=['/path/to/screenshot.png']
            )
        """
        def _run():
            return self.jira.add_comment(issue, body)

        comment = await asyncio.to_thread(_run)
        result = self._issue_to_dict(comment)

        # Upload attachments if provided
        if attachments:
            uploaded: List[Dict[str, Any]] = []
            for file_path in attachments:
                if not os.path.isfile(file_path):
                    uploaded.append({"file": file_path, "error": "File not found"})
                    self.logger.warning(f"Attachment file not found: {file_path}")
                    continue

                def _upload(fp: str = file_path) -> Any:
                    return self.jira.add_attachment(
                        issue=issue, attachment=fp
                    )

                try:
                    att = await asyncio.to_thread(_upload)
                    att_info: Dict[str, Any] = {
                        "filename": getattr(att, "filename", os.path.basename(file_path)),
                        "id": getattr(att, "id", None),
                        "size": getattr(att, "size", None),
                        "mimeType": getattr(att, "mimeType", None),
                    }
                    uploaded.append(att_info)
                except Exception as exc:
                    uploaded.append({"file": file_path, "error": str(exc)})
                    self.logger.error(f"Failed to attach {file_path}: {exc}")
            result["attachments"] = uploaded

        return result

    @requires_permission('jira.write')
    @tool_schema(AddWorklogInput)
    async def jira_add_worklog(
        self,
        issue: str,
        time_spent: str,
        comment: Optional[str] = None,
        started: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add worklog to an issue. Requires jira.write permission.

        Example: jira.jira_add_worklog('JRA-1330', '1h 30m', 'Working on feature')
        """
        def _run():
            return self.jira.add_worklog(
                issue=issue,
                timeSpent=time_spent,
                comment=comment,
                started=started
            )

        worklog = await asyncio.to_thread(_run)
        # Worklog object typically has id, etc.
        val = self._issue_to_dict(worklog)
        # Ensure we return something useful even if raw is missing
        if not val or not val.get('id'):
            return {
                "id": getattr(worklog, "id", None),
                "issue": issue,
                "timeSpent": time_spent,
                "created": getattr(worklog, "created", None)
            }
        return val

    @tool_schema(GetIssueTypesInput)
    async def jira_get_issue_types(self, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """List issue types, optionally for a specific project.

        Example: jira.jira_get_issue_types(project='PROJ')
        """
        def _run():
            if project:
                proj = self.jira.project(project)
                return proj.issueTypes
            else:
                return self.jira.issue_types()

        try:
            types = await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=self.request_timeout + 5,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Jira list issue_types timed out after {self.request_timeout + 5:.0f}s"
            ) from exc
        # types is list of IssueType objects
        return [
            {"id": t.id, "name": t.name, "description": getattr(t, "description", "")}
            for t in types
        ]

    async def _validate_issue_type(self, project: str, issuetype: str) -> str:
        """Return the canonical issue type name for ``project`` or raise.

        Jira rejects ``POST /issue`` with an opaque 400 when the issuetype
        isn't associated with the target project's issue type scheme. This
        helper checks the project's actual types first and surfaces the
        valid names so the LLM can retry with a correct value.

        Returns:
            The canonical (correctly-cased) issue type name as known to
            Jira.

        Raises:
            ValueError: When ``issuetype`` doesn't match any type for the
                project. The message contains all valid names.
        """
        try:
            valid = await self.jira_get_issue_types(project=project)
        except Exception as exc:  # noqa: BLE001 — don't block create on probe failure
            # If we can't list types (permissions, transient error), skip
            # validation and let the real POST produce whatever error Jira
            # sends. Silent-best-effort validation only.
            self.logger.warning(
                "Could not pre-validate issue type for project %s: %s",
                project, exc,
            )
            return issuetype

        names = [t["name"] for t in valid if t.get("name")]
        requested_lower = issuetype.strip().lower()
        for name in names:
            if name.lower() == requested_lower:
                return name  # canonical casing
        raise ValueError(
            f"Issue type '{issuetype}' is not valid for project '{project}'. "
            f"Valid issue types: {', '.join(names) if names else '(none returned)'}"
        )

    # Atlassian returns this header on 200 responses when an auth attempt
    # was made but failed (common on Jira Cloud with a stale API token).
    # See the response headers on any silently-broken request:
    #   X-Seraph-Loginreason: AUTHENTICATED_FAILED
    _SERAPH_HEADER = "X-Seraph-Loginreason"
    _SERAPH_FAIL_VALUES = {"AUTHENTICATED_FAILED", "AUTHENTICATION_DENIED"}

    def _probe_auth_sync(self) -> Dict[str, Any]:
        """Raw HTTP probe against ``/rest/api/2/myself``.

        pycontribs' ``JIRA.myself()`` does not surface response headers, and
        Jira Cloud returns a 200 + ``X-Seraph-Loginreason: AUTHENTICATED_FAILED``
        when the session is anonymous after a failed auth attempt. Going
        through the underlying session lets us read those headers directly.
        """

        url = f"{self.server_url.rstrip('/')}/rest/api/2/myself"
        session = getattr(self.jira, "_session", None)
        try:
            response = session.get(url) if session is not None else None
        except Exception as exc:  # noqa: BLE001 — surface transport failures too
            self.logger.warning("jira auth probe raised: %s", exc)
            return {
                "authenticated": False,
                "server_url": self.server_url,
                "auth_type": self.auth_type,
                "error": f"{type(exc).__name__}: {exc}",
            }

        if response is None:
            return {
                "authenticated": False,
                "server_url": self.server_url,
                "auth_type": self.auth_type,
                "error": "No underlying session available on JIRA client.",
            }

        headers = dict(response.headers or {})
        seraph = headers.get(self._SERAPH_HEADER) or headers.get(
            self._SERAPH_HEADER.lower()
        )
        seraph_failed = bool(seraph) and seraph.upper() in self._SERAPH_FAIL_VALUES
        status = response.status_code
        is_http_ok = 200 <= status < 300
        authenticated = is_http_ok and not seraph_failed

        try:
            body = response.json() if is_http_ok else None
        except ValueError:
            body = None

        # Always emit a log line with the relevant headers so operators see the
        # auth state even when the tool's return value is not surfaced.
        self.logger.info(
            "Jira auth probe → status=%s seraph=%s url=%s",
            status, seraph or "<absent>", url,
        )

        result: Dict[str, Any] = {
            "authenticated": authenticated,
            "server_url": self.server_url,
            "auth_type": self.auth_type,
            "status_code": status,
            "seraph_login_reason": seraph,
            "user": body if authenticated else None,
        }
        if not authenticated:
            result["error"] = (
                f"HTTP {status}"
                + (f" — {seraph}" if seraph else "")
                + ". Verify JIRA_USERNAME / JIRA_API_TOKEN (or JIRA_PASSWORD) "
                  "and JIRA_INSTANCE."
            )
            # Include a short body preview to help diagnose.
            text = getattr(response, "text", "") or ""
            if text:
                result["response_preview"] = text[:400]
        return result

    @tool_schema(GetProjectsInput)
    async def jira_get_projects(self) -> Dict[str, Any]:
        """List all accessible projects.

        On Jira Cloud, a silently failed authentication (wrong username or
        revoked API token) returns an empty project list with HTTP 200 and a
        ``X-Seraph-Loginreason: AUTHENTICATED_FAILED`` header. When the list
        comes back empty this tool probes ``/rest/api/2/myself`` and surfaces
        the auth status plus the Seraph header so the caller can explain it.

        Returns: ``{"projects": [...], "count": N, "authenticated": bool,
        "auth_probe": {...}}``
        """
        def _run():
            return self.jira.projects()

        projs = await asyncio.to_thread(_run)
        project_list = [{"id": p.id, "key": p.key, "name": p.name} for p in projs]

        if project_list:
            return {
                "projects": project_list,
                "count": len(project_list),
                "authenticated": True,
            }

        probe = await asyncio.to_thread(self._probe_auth_sync)
        hint = (
            "Authentication check failed — "
            f"seraph={probe.get('seraph_login_reason')!r}, "
            f"status={probe.get('status_code')}. "
            "Verify JIRA_USERNAME / JIRA_PASSWORD (or JIRA_API_TOKEN) and "
            "the configured JIRA_INSTANCE URL."
            if not probe.get("authenticated")
            else "Authenticated user has no accessible projects."
        )
        return {
            "projects": [],
            "count": 0,
            "authenticated": probe.get("authenticated", False),
            "auth_probe": probe,
            "hint": hint,
        }

    @tool_schema(VerifyAuthInput)
    async def jira_verify_auth(self) -> Dict[str, Any]:
        """Verify the toolkit is authenticated against Jira.

        Performs a raw ``GET /rest/api/2/myself`` so the Atlassian
        ``X-Seraph-Loginreason`` header is inspected — this catches the
        silent-auth-failure case where the API still returns HTTP 200 but
        serves anonymous content. Never raises.
        """
        return await asyncio.to_thread(self._probe_auth_sync)

    @tool_schema(GetComponentsInput)
    async def jira_get_components(self, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all components for a project. Use this to find component IDs before creating issues.

        IMPORTANT: When creating issues with components, you must use the component ID
        (not the name). Call this method first to discover the IDs.

        Example: jira.jira_get_components(project='NAV')
        Returns: [{"id": "10042", "name": "Backend", "description": "..."}, ...]
        """
        proj = project or self.default_project
        if not proj:
            raise ValueError("Project key is required for listing components")

        def _run():
            return self.jira.project_components(proj)

        components = await asyncio.to_thread(_run)
        return [
            {
                "id": c.id,
                "name": c.name,
                "description": getattr(c, "description", "") or "",
            }
            for c in components
        ]

    @tool_schema(GetComponentByNameInput)
    async def jira_get_component_by_name(
        self, name: str, project: Optional[str] = None
    ) -> Dict[str, Any]:
        """Find a component by name and return its details including the internal ID.

        Use this method to resolve a component name to its Jira internal ID
        before creating tickets. Jira requires component IDs (not names) when
        creating or updating issues.

        Workflow for ticket creation with components:
            1. component = await jira_get_component_by_name(name='Backend', project='NAV')
            2. component_id = component['id']  # e.g. '10042'
            3. await jira_create_issue(summary='Fix bug', components=[component_id])

        Args:
            name: Component name to search for (case-insensitive match).
            project: Project key. Falls back to default project if omitted.

        Returns:
            Dict with keys: id, name, description.

        Raises:
            ValueError: If the component name is not found in the project.

        Example:
            jira.jira_get_component_by_name(name='Backend', project='NAV')
            # Returns: {"id": "10042", "name": "Backend", "description": "Backend services"}
        """
        all_components = await self.jira_get_components(project=project)
        name_lower = name.lower()
        for comp in all_components:
            if comp["name"].lower() == name_lower:
                return comp
        available = [c["name"] for c in all_components]
        raise ValueError(
            f"Component '{name}' not found in project '{project or self.default_project}'. "
            f"Available components: {available}"
        )

    @tool_schema(SearchUsersInput)
    async def jira_search_users(
        self,
        user: Optional[str] = None,
        start_at: int = 0,
        max_results: int = 50,
        include_active: bool = True,
        include_inactive: bool = False,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search for users matching the specified search string.

        "username" query parameter is deprecated in Jira Cloud; the expected parameter now is "query".
        But the "user" parameter is kept for backwards compatibility.

        Example:
            jira.search_users(query='john.doe@example.com')
        """
        def _run():
            return self.jira.search_users(
                user=user,
                startAt=start_at,
                maxResults=max_results,
                includeActive=include_active,
                includeInactive=include_inactive,
                query=query
            )

        users = await asyncio.to_thread(_run)
        # Convert resources to dicts
        return [self._issue_to_dict(u) for u in users]

    def _store_dataframe(
        self,
        name: str,
        df: pd.DataFrame,
        metadata: Dict[str, Any]
    ) -> str:
        """Store DataFrame in ToolManager's shared context."""
        if self._tool_manager is None:
            self.logger.warning(
                "No ToolManager set. DataFrame not shared. "
                "Call set_tool_manager() to enable sharing."
            )
            return name

        try:
            self._tool_manager.share_dataframe(name, df, metadata)
            self.logger.info(f"DataFrame '{name}' stored: {len(df)} rows")
            return name
        except Exception as e:
            self.logger.error(f"Failed to store DataFrame: {e}")
            return name

    def _json_issues_to_dataframe(self, issues: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Convert JSON issues to a flattened DataFrame.

        Works with json_result=True output format.
        """
        if not issues:
            return pd.DataFrame()

        rows = []
        for issue in issues:
            fields = issue.get('fields', {}) or {}

            # Safe extraction helpers
            def get_nested(obj, *keys, default=None):
                for key in keys:
                    if obj is None or not isinstance(obj, dict):
                        return default
                    obj = obj.get(key)
                return obj if obj is not None else default

            row = {
                'key': issue.get('key'),
                'id': issue.get('id'),
                'self': issue.get('self'),

                # Summary & Description
                'summary': fields.get('summary'),
                'description': (fields.get('description') or '')[:500] if fields.get('description') else None,

                # People
                'assignee_id': get_nested(fields, 'assignee', 'accountId') or get_nested(fields, 'assignee', 'name'),
                'assignee_name': get_nested(fields, 'assignee', 'displayName'),
                'reporter_id': get_nested(fields, 'reporter', 'accountId') or get_nested(fields, 'reporter', 'name'),
                'reporter_name': get_nested(fields, 'reporter', 'displayName'),

                # Status & Priority
                'status': get_nested(fields, 'status', 'name'),
                'status_category': get_nested(fields, 'status', 'statusCategory', 'name'),
                'priority': get_nested(fields, 'priority', 'name'),

                # Type & Project
                'issuetype': get_nested(fields, 'issuetype', 'name'),
                'project_key': get_nested(fields, 'project', 'key'),
                'project_name': get_nested(fields, 'project', 'name'),

                # Dates
                'created': fields.get('created'),
                'updated': fields.get('updated'),
                'resolved': fields.get('resolutiondate'),
                'due_date': fields.get('duedate'),

                # Estimates (story points field ID varies by instance)
                'story_points': fields.get('customfield_10016'),
                'time_estimate': fields.get('timeoriginalestimate'),
                'time_spent': fields.get('timespent'),

                # Collections
                'labels': ','.join(fields.get('labels', [])) if fields.get('labels') else None,
                'components': ','.join(
                    [c.get('name', '') for c in (fields.get('components') or [])]
                ) if fields.get('components') else None,
            }
            rows.append(row)

        df = pd.DataFrame(rows)

        # Convert date columns
        for col in ['created', 'updated', 'resolved', 'due_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', utc=True)

        # Add derived columns for easy grouping
        if 'created' in df.columns and df['created'].notna().any():
            df['created_month'] = df['created'].dt.to_period('M').astype(str)
            df['created_week'] = df['created'].dt.strftime('%Y-W%W')

        return df

    def _generate_summary(
        self,
        df: pd.DataFrame,
        jql: str,
        total: int,
        group_by: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generate summary statistics for LLM consumption."""
        summary = {
            "total_count": total,
            "fetched_count": len(df),
            "jql": jql,
        }

        if df.empty:
            return summary

        # Default groupings
        default_groups = ['assignee_name', 'status']
        groups_to_use = group_by or default_groups

        # Generate counts for each field
        for field in groups_to_use:
            if field in df.columns:
                counts = df[field].value_counts(dropna=False).head(25).to_dict()
                # Replace NaN key with "Unassigned"
                if pd.isna(list(counts.keys())[0]) if counts else False:
                    counts = {("Unassigned" if pd.isna(k) else k): v for k, v in counts.items()}
                summary[f"by_{field}"] = counts

        # Date range if available
        if 'created' in df.columns and df['created'].notna().any():
            summary["date_range"] = {
                "oldest": df['created'].min().isoformat() if pd.notna(df['created'].min()) else None,
                "newest": df['created'].max().isoformat() if pd.notna(df['created'].max()) else None,
            }

        return summary

    def _resolve_fields(
        self,
        fields: Optional[str],
        for_counting: bool = False,
        group_by: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Resolve fields parameter to actual field string.

        Args:
            fields: User input - preset name or field string
            for_counting: If True and fields is None, auto-select minimal
            group_by: If provided, select only fields needed for these groupings
        """
        # If explicit fields provided, check for preset
        if fields:
            preset = FIELD_PRESETS.get(fields.lower())
            if preset:
                self.logger.debug(f"Using field preset '{fields}': {preset}")
                return preset
            return fields

        # Auto-select for counting based on group_by
        if for_counting and group_by:
            field_map = {
                'assignee': 'assignee',
                'reporter': 'reporter',
                'status': 'status',
                'priority': 'priority',
                'issuetype': 'issuetype',
                'project': 'project',
                'created_month': 'created',
            }
            needed = {'key'}
            for g in group_by:
                if g in field_map:
                    needed.add(field_map[g])
            return ','.join(sorted(needed))

        # Default for counting without specific groups
        if for_counting:
            return FIELD_PRESETS["count"]

        # No resolution needed
        return fields

    @tool_schema(SearchIssuesInput)
    async def jira_search_issues(
        self,
        jql: str,
        start_at: int = 0,
        max_results: Optional[int] = 100,
        fields: Optional[str] = None,
        expand: Optional[str] = None,
        json_result: bool = True,
        store_as_dataframe: bool = False,
        dataframe_name: Optional[str] = None,
        summary_only: bool = False,
        structured: Optional[StructuredOutputOptions] = None,
    ) -> Dict[str, Any]:
        """
        Search issues with JQL.

        For efficiency:
        - Use `fields` to request only needed data (e.g., 'key,assignee,status')
        - Use `max_results=None` to fetch all matching issues
        - Use `summary_only=True` for counts to avoid context bloat
        - Use `store_as_dataframe=True` for complex analysis with PythonPandasTool

        Examples:
        ---------
        # Simple search (default)
        jira_search_issues(jql="project = NAV AND status = Open")

        # Fetch all issues for counting
        jira_search_issues(
            jql="project = NAV AND status = Open",
            max_results=None,  # Fetch all!
            fields="key,assignee,status",
            summary_only=True
        )

        # Full data for analysis
        jira_search_issues(
            jql="project = NAV",
            max_results=None,
            fields="key,summary,assignee,status,created,priority",
            store_as_dataframe=True,
            dataframe_name="nav_issues"
        )
        # Then use PythonPandasTool to analyze 'nav_issues' DataFrame
        """

        jql = self._ensure_bounded_jql(jql)

        self.logger.info(
            f"Executing JQL: {jql} with max results {max_results}"
        )

        # Use enhanced_search_issues for Jira Cloud (uses nextPageToken pagination)
        def _run_enhanced_search(page_token: Optional[str], current_max: int):
            return self.jira.enhanced_search_issues(
                jql,
                maxResults=current_max,
                fields=fields.split(',') if fields else None,
                expand=expand,
                nextPageToken=page_token
            )

        all_issues = []
        fetched = 0
        next_page_token: Optional[str] = None
        is_last = False

        # Pagination loop using nextPageToken
        # If max_results is None, fetch all (loop until isLast=True)
        while not is_last:
            # Calculate how many we still need
            # Use 100 per page if fetching all, otherwise remaining
            if max_results is None:
                page_size = 100  # Reasonable page size for full fetch
            else:
                remaining = max_results - fetched
                if remaining <= 0:
                    break
                page_size = min(remaining, 100)

            # Using asyncio.to_thread for the blocking call
            result_list = await asyncio.to_thread(_run_enhanced_search, next_page_token, page_size)

            # enhanced_search_issues returns a ResultList object
            batch_issues = [self._issue_to_dict(i) for i in result_list]

            # Get pagination info from ResultList
            next_page_token = getattr(result_list, 'nextPageToken', None)
            is_last = getattr(result_list, 'isLast', True)  # Default to True if missing

            if not batch_issues:
                break

            all_issues.extend(batch_issues)
            fetched += len(batch_issues)

            # If max_results is set and we've reached it, stop
            if max_results is not None and fetched >= max_results:
                break

            # If no more pages, stop
            if is_last or next_page_token is None:
                break

        issues = all_issues

        # Total is not returned by enhanced_search_issues, use fetched count
        total = len(issues)

        # Convert to DataFrame
        df = self._json_issues_to_dataframe(issues)

        # Store DataFrame if requested
        df_name = dataframe_name or "jira_issues"
        if structured:
            _sopts = self._ensure_structured(structured)
            items = [self._apply_structured_output(it, _sopts) for it in issues]
            return {"total": total, "issues": items}

        if store_as_dataframe and not df.empty:
            self._store_dataframe(
                df_name,
                df,
                {
                    "jql": jql,
                    "total": total,
                    "fetched_at": datetime.now().isoformat(),
                    "fields_requested": fields,
                }
            )
            return {
                "total": total,
                "dataframe_name": df_name,
                "dataframe_info": (
                    f"Full data stored in DataFrame '{df_name}' with {len(df)} rows. "
                    f"Use PythonPandasTool for custom aggregations."
                ),
                "pagination": {
                    "start_at": start_at,
                    "max_results": max_results,
                    "returned": len(issues),
                    "total": total,
                    "has_more": (start_at + len(issues)) < total,
                },
                "jql": jql
            }

        # Build response
        if summary_only:
            # Return summary with counts - minimal context usage
            result = self._generate_summary(df, jql, total)
            result["pagination"] = {
                "start_at": start_at,
                "max_results": max_results,
                "returned": len(issues),
                "total": total,
                "has_more": (start_at + len(issues)) < total,
            }
            if store_as_dataframe:
                result["dataframe_name"] = df_name
                result["dataframe_info"] = (
                    f"Full data stored in DataFrame '{df_name}' with {len(df)} rows. "
                    f"Use PythonPandasTool for custom aggregations."
                )
            return result

        else:
            # Return issues with metadata
            result = {
                "total": total,
                "issues": issues,
                "pagination": {
                    "start_at": start_at,
                    "max_results": max_results,
                    "returned": len(issues),
                    "total": total,
                    "has_more": (start_at + len(issues)) < total,
                },
            }

            if store_as_dataframe:
                result["dataframe_name"] = df_name
                result["dataframe_info"] = f"Data also stored in DataFrame '{df_name}'"

            # Add notice if not all results returned
            if len(issues) < total:
                result["notice"] = (
                    f"Showing {len(issues)} of {total} total issues. "
                    f"Increase max_results (up to 1000) to get more, or "
                    f"use summary_only=True for counts."
                )

            return result

    @tool_schema(CountIssuesInput)
    async def jira_count_issues(
        self,
        jql: str,
        group_by: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Count issues with optional grouping - optimized for efficiency.

        Uses minimal fields to reduce payload size and processing time.
        Fetches ALL matching issues to provide accurate counts.

        Examples:
        ---------
        # Total count
        jira_count_issues(jql="project = NAV AND status = Open")
        # Returns: {"total_count": 847, "fetched_count": 847}

        # Count by assignee
        jira_count_issues(
            jql="project = NAV AND created >= '2025-01-01'",
            group_by=["assignee"]
        )
        # Returns: {"total_count": 234, "by_assignee": {"John": 45, "Jane": 32, ...}}

        # Count by multiple fields
        jira_count_issues(
            jql="project = NAV",
            group_by=["assignee", "status"]
        )
        """

        # Determine which fields we actually need based on group_by
        field_mapping = {
            'assignee': 'assignee',
            'reporter': 'reporter',
            'status': 'status',
            'priority': 'priority',
            'issuetype': 'issuetype',
            'project': 'project',
            'created_month': 'created',
            'created_week': 'created',
        }

        needed_fields = {'key'}  # Always need key for counting
        if group_by:
            for g in group_by:
                if g in field_mapping:
                    needed_fields.add(field_mapping[g])
        else:
            # Default: get common grouping fields
            needed_fields.update(['assignee', 'status'])

        fields_str = ','.join(needed_fields)

        self.logger.info(f"Counting issues for JQL: {jql}")

        # Delegate to search_issues which handles pagination
        # max_results=None fetches ALL matching issues
        search_result = await self.jira_search_issues(
            jql,
            max_results=None,  # Fetch all for accurate counts
            fields=fields_str,
            json_result=True,
            store_as_dataframe=False
        )

        # search_result is a dict: {'total': int, 'issues': list, ...}
        total = search_result.get('total', 0)
        issues = search_result.get('issues', [])

        result = {
            "total_count": total,
            "fetched_count": len(issues),
            "jql": jql,
        }

        if total > len(issues):
            result["warning"] = (
                f"Only fetched {len(issues)} of {total} issues. "
                f"Counts below are based on fetched data only. "
                f"Increase max_results for complete counts."
            )

        if not issues:
            return result

        # Convert and aggregate
        df = self._json_issues_to_dataframe(issues)

        # Column mapping for user-friendly names
        column_mapping = {
            'assignee': 'assignee_name',
            'reporter': 'reporter_name',
            'status': 'status',
            'priority': 'priority',
            'issuetype': 'issuetype',
            'project': 'project_key',
            'created_month': 'created_month',
            'created_week': 'created_week',
        }

        # Generate counts
        groups_to_count = group_by or ['assignee', 'status']
        for group_field in groups_to_count:
            col = column_mapping.get(group_field, group_field)
            if col in df.columns:
                counts = df[col].value_counts(dropna=False).to_dict()
                # Clean up NaN keys
                counts = {
                    ("Unassigned" if pd.isna(k) else k): v
                    for k, v in counts.items()
                }
                result[f"by_{group_field}"] = counts

        # Multi-dimensional grouping if multiple fields
        if group_by and len(group_by) > 1:
            cols = [column_mapping.get(g, g) for g in group_by if column_mapping.get(g, g) in df.columns]
            if len(cols) > 1:
                try:
                    pivot = df.groupby(cols, dropna=False).size().reset_index(name='count')
                    # Convert to list of records for readability
                    result["grouped"] = pivot.head(50).to_dict(orient='records')
                except Exception as e:
                    self.logger.warning(f"Multi-group failed: {e}")

        return result

    @tool_schema(GetMyTicketsInput)
    async def jira_get_my_tickets(
        self,
        status: Optional[Union[str, List[str]]] = None,
        project: Optional[str] = None,
        include_closed: bool = False,
        max_results: Optional[int] = 50,
        order_by: Optional[str] = "updated DESC",
        fields: Optional[str] = (
            "key,summary,status,priority,issuetype,project,created,updated,duedate"
        ),
        summary_only: bool = False,
    ) -> Dict[str, Any]:
        """Retrieve the tickets assigned to the CURRENT (authenticated) Jira user.

        INSTRUCT: Run this tool **whenever the user asks for HIS/HER own
        tickets or issues**. Example trigger phrases (English and Spanish):
        "my tickets", "my issues", "my open tickets", "what am I assigned to",
        "tickets assigned to me", "show me my work", "what's on my plate",
        "mis tickets", "mis issues", "mis tareas asignadas", "qué tengo
        asignado". In those cases, do NOT build a JQL query manually and do
        NOT call ``jira_search_issues`` — use this tool instead. It resolves
        the authenticated identity server-side via the JQL ``currentUser()``
        function, so it always returns tickets assigned to the user who owns
        the active OAuth token (no email lookups, no PII, no name-collision
        ambiguity).

        When ``status`` is omitted, Done/Closed/Resolved tickets are filtered
        out so the response focuses on actionable work. Pass
        ``include_closed=True`` to include them.

        Args:
            status: Optional status filter. A single status ("In Progress")
                or a list (["To Do", "In Progress"]).
            project: Optional Jira project key filter (e.g. "NAV").
            include_closed: When True, include Done/Closed/Resolved tickets.
                Ignored when ``status`` is provided.
            max_results: Max tickets to return. Use None to fetch all.
            order_by: JQL ORDER BY clause. Default: "updated DESC".
            fields: Comma-separated Jira fields to return.
            summary_only: Return grouped counts instead of raw tickets.

        Returns:
            Dict with the matching issues (or a grouped summary when
            ``summary_only=True``).

        Examples:
        ---------
        # All my active tickets (excludes Done/Closed/Resolved)
        await jira_get_my_tickets()

        # My in-progress NAV tickets
        await jira_get_my_tickets(status="In Progress", project="NAV")

        # Everything assigned to me, including closed work
        await jira_get_my_tickets(include_closed=True, max_results=None)
        """
        clauses: List[str] = ["assignee = currentUser()"]

        if project:
            clauses.append(f"project = {self._quote_jql_value(project)}")

        if status is not None:
            status_list = [status] if isinstance(status, str) else list(status)
            if status_list:
                quoted = ", ".join(self._quote_jql_value(s) for s in status_list)
                if len(status_list) == 1:
                    clauses.append(f"status = {quoted}")
                else:
                    clauses.append(f"status in ({quoted})")
        elif not include_closed:
            clauses.append('status not in ("Done", "Closed", "Resolved")')

        jql = " AND ".join(clauses)
        if order_by:
            jql = f"{jql} ORDER BY {order_by}"

        self.logger.info("Fetching current user's tickets with JQL: %s", jql)

        return await self.jira_search_issues(
            jql=jql,
            max_results=max_results,
            fields=fields,
            summary_only=summary_only,
        )

    @tool_schema(AggregateJiraDataInput)
    async def jira_aggregate_data(
        self,
        dataframe_name: str = "jira_issues",
        group_by: List[str] = None,
        aggregations: Dict[str, str] = None,
        sort_by: Optional[str] = None,
        ascending: bool = False,
    ) -> Dict[str, Any]:
        """
        Aggregate data from a stored Jira DataFrame.

        Use this after jira_search_issues with fetch_all=True to perform
        custom aggregations on the stored data.

        Examples:
        ---------
        # Count by assignee
        jira_aggregate_data(
            dataframe_name="jira_issues",
            group_by=["assignee_name"],
            aggregations={"key": "count"}
        )

        # Sum story points by status
        jira_aggregate_data(
            dataframe_name="jira_issues",
            group_by=["status"],
            aggregations={"story_points": "sum", "key": "count"},
            sort_by="story_points"
        )
        """

        if self._tool_manager is None:
            raise ValueError(
                "ToolManager not set. Cannot access stored DataFrames. "
                "First fetch data with jira_search_issues(fetch_all=True)"
            )

        try:
            df = self._tool_manager.get_shared_dataframe(dataframe_name)
        except KeyError:
            available = self._tool_manager.list_shared_dataframes()
            raise KeyError(
                f"DataFrame '{dataframe_name}' not found. "
                f"Available DataFrames: {available}. "
                f"First fetch data with jira_search_issues(fetch_all=True, dataframe_name='...')"
            )

        if df.empty:
            raise ValueError(f"DataFrame '{dataframe_name}' is empty (0 rows).")

        if not group_by:
            group_by = ["assignee_name"]

        if not aggregations:
            aggregations = {"key": "count"}

        try:
            # Perform aggregation
            agg_result = df.groupby(group_by, dropna=False).agg(aggregations).reset_index()

            # Flatten column names if MultiIndex
            if isinstance(agg_result.columns, pd.MultiIndex):
                agg_result.columns = ['_'.join(col).strip('_') for col in agg_result.columns]

            # Sort if requested
            if sort_by and sort_by in agg_result.columns:
                agg_result = agg_result.sort_values(sort_by, ascending=ascending)

            return {
                "success": True,
                "row_count": len(agg_result),
                "columns": list(agg_result.columns),
                "data": agg_result.to_dict(orient='records'),
            }
        except Exception as e:
            raise ValueError(
                f"Aggregation failed: {e}. "
                f"Available columns: {list(df.columns)}. "
                f"Check that group_by columns exist in the DataFrame."
            ) from e

    # -----------------------------------------------------------------
    # High-level edit helpers (resolve names/emails automatically)
    # -----------------------------------------------------------------

    @requires_permission('jira.write')
    @tool_schema(ChangeAssigneeInput)
    async def jira_set_assignee(self, issue: str, assignee: str) -> Dict[str, Any]:
        """Set the assignee of an issue by email or accountId.

        Resolves the email to an accountId automatically when needed.

        Examples:
            jira_set_assignee(issue='NAV-6213', assignee='jleon@trocglobal.com')
            jira_set_assignee(issue='NAV-6213', assignee='60d1f2a3b4c5e6f7g8h9i0j1')
        """
        account_id = await self._resolve_account_id(assignee)
        await self.jira_update_issue(
            issue=issue,
            fields={"assignee": {"accountId": account_id}},
        )
        return {"ok": True, "issue": issue, "assignee": account_id}

    @requires_permission('jira.write')
    @tool_schema(ChangeReporterInput)
    async def jira_set_reporter(self, issue: str, email: str) -> Dict[str, Any]:
        """Change the reporter of an issue by email.

        Resolves the email to an accountId, then updates the reporter field.

        Examples:
            jira_set_reporter(issue='NAV-6213', email='jleon@trocglobal.com')
        """
        account_id = await self._resolve_account_id(email)
        await self.jira_update_issue(
            issue=issue,
            fields={"reporter": {"accountId": account_id}},
        )
        return {"ok": True, "issue": issue, "reporter": account_id}

    @requires_permission('jira.write')
    @tool_schema(AddComponentInput)
    async def jira_add_component(
        self, issue: str, component_name: str, project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a component to an issue by name.

        Resolves the component name to its internal Jira ID, then appends it
        to the issue's existing components (without removing current ones).

        Examples:
            jira_add_component(issue='NAV-6213', component_name='Backend')
            jira_add_component(issue='NAV-6213', component_name='Assembly360', project='NAV')
        """
        # Resolve component name → id
        comp = await self.jira_get_component_by_name(name=component_name, project=project)
        comp_id = comp["id"]

        # Get current components so we append, not replace
        current = await self.jira_get_issue(issue, fields="components")
        existing = current.get("fields", {}).get("components", [])
        existing_ids = {str(c.get("id")) for c in existing}

        if str(comp_id) in existing_ids:
            return {
                "ok": True,
                "message": f"Component '{component_name}' already on {issue}",
                "components": [c.get("name") for c in existing],
            }

        new_components = [{"id": str(c.get("id"))} for c in existing]
        new_components.append({"id": str(comp_id)})

        await self.jira_update_issue(issue=issue, fields={"components": new_components})
        return {
            "ok": True,
            "added": component_name,
            "component_id": comp_id,
            "issue": issue,
        }

    @requires_permission('jira.write')
    @tool_schema(AddWatcherInput)
    async def jira_add_watcher(self, issue: str, email: str) -> Dict[str, Any]:
        """Add a user to an issue's watchers list ("who's looking").

        Resolves the email to an accountId, then adds them as a watcher.

        Examples:
            jira_add_watcher(issue='NAV-6213', email='jleon@trocglobal.com')
        """
        account_id = await self._resolve_account_id(email)

        def _run():
            self.jira.add_watcher(issue, account_id)

        await asyncio.to_thread(_run)
        return {"ok": True, "issue": issue, "watcher": account_id}

    @requires_permission('jira.write')
    @tool_schema(SetAcceptanceCriteriaInput)
    async def jira_set_acceptance_criteria(
        self,
        issue: str,
        criteria: List[str],
        custom_field: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Set the acceptance criteria checklist on an issue.

        Formats the criteria as a numbered markdown list and writes it to the
        acceptance-criteria custom field.  If ``custom_field`` is not provided,
        the method auto-detects by trying common custom field IDs
        (customfield_10021, customfield_10022, customfield_10035).

        Examples:
            jira_set_acceptance_criteria(
                issue='NAV-6213',
                criteria=[
                    'User can log in with SSO',
                    'Session expires after 30 min of inactivity',
                    'Error message shown on invalid credentials',
                ],
            )
        """
        # Format as numbered checklist
        formatted = "\n".join(f"# {item}" for item in criteria)

        if custom_field:
            await self.jira_update_issue(issue=issue, fields={custom_field: formatted})
            return {"ok": True, "issue": issue, "field": custom_field, "criteria_count": len(criteria)}

        # Auto-detect: try common custom field IDs
        candidate_fields = ["customfield_10021", "customfield_10022", "customfield_10035"]
        last_error = None
        for cf in candidate_fields:
            try:
                await self.jira_update_issue(issue=issue, fields={cf: formatted})
                self.logger.info(f"Acceptance criteria set via {cf}")
                return {"ok": True, "issue": issue, "field": cf, "criteria_count": len(criteria)}
            except Exception as e:
                last_error = e
                continue

        raise ValueError(
            f"Could not set acceptance criteria on {issue}. "
            f"Tried fields: {candidate_fields}. Last error: {last_error}. "
            f"Pass custom_field='customfield_XXXXX' explicitly."
        )

    async def _resolve_account_id(self, email_or_id: str) -> str:
        """Resolve an email address to a Jira accountId.

        If the input already looks like an accountId (no '@'), it is returned as-is.
        """
        if "@" not in email_or_id:
            return email_or_id
        result = await self.jira_find_user(email_or_id)
        if not result.get("found"):
            raise ValueError(f"No Jira user found for email: {email_or_id}")
        matches = result["matches"]
        # Prefer exact email match
        for m in matches:
            if (m.get("emailAddress") or "").lower() == email_or_id.lower():
                return m["accountId"]
        # Fallback to first match
        return matches[0]["accountId"]

    @requires_permission('jira.admin')
    @tool_schema(ConfigureClientInput)
    async def jira_configure_client(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        auth_type: Optional[str] = None,
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Re-configure the Jira client with new credentials. Requires jira.admin permission.

        Updates the internal client instance to use the provided credentials.
        Useful for switching users or rotating tokens without restarting the agent.
        """
        if server_url:
            self.server_url = server_url
        if auth_type:
            self.auth_type = auth_type
        if username:
            self.username = username
        if password:
            self.password = password
        if token:
            self.token = token

        try:
            self._set_jira_client()
            return {
                "ok": True,
                "message": "Jira client re-configured successfully.",
                "server_url": self.server_url,
                "auth_type": self.auth_type,
                "username": self.username
            }
        except Exception as e:
            self.logger.error(f"Failed to re-configure Jira client: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

    # -----------------------------
    # New Methods
    # -----------------------------

    @tool_schema(ListHistoryInput)
    async def jira_list_transitions(self, issue: str) -> List[Dict[str, Any]]:
        """List all status changes (transitions) for a ticket."""
        changelog = await self._get_full_changelog(issue)
        return self._extract_field_history(changelog, "status")

    @tool_schema(ListHistoryInput)
    async def jira_list_assignees(self, issue: str) -> List[Dict[str, Any]]:
        """List all historical assignees of a ticket."""
        changelog = await self._get_full_changelog(issue)
        return self._extract_field_history(changelog, "assignee")

    @requires_permission('jira.write')
    @tool_schema(UpdateIssueInput)
    async def jira_update_ticket(self, **kwargs) -> Dict[str, Any]:
        """Update a ticket (alias for jira_update_issue). Requires jira.write permission."""
        return await self.jira_update_issue(**kwargs)

    @requires_permission('jira.write')
    @tool_schema(ChangeAssigneeInput)
    async def jira_change_assignee(self, issue: str, assignee: str) -> Dict[str, Any]:
        """Change the ticket to a new assignee. Requires jira.write permission."""
        return await self.jira_assign_issue(issue=issue, assignee=assignee)

    @tool_schema(FindUserInput)
    async def jira_find_user(self, email: str) -> Dict[str, Any]:
        """Find a user by email."""
        # 'query' is the standard param for email search in new/cloud Jira
        results = await self.jira_search_users(query=email)
        if not results:
            return {"found": False, "email": email}
        # Return exact match or best guess
        return {"found": True, "matches": results}

    @tool_schema(TicketIdInput)
    async def jira_list_tags(self, issue: str) -> List[str]:
        """List all tags (labels) added to a ticket."""
        obj = await self.jira_get_issue(issue, fields="labels")
        # Structure varies, but usually it's in fields['labels']
        if isinstance(obj, dict):
            return obj.get("fields", {}).get("labels", [])
        return []

    @requires_permission('jira.write')
    @tool_schema(TagInput)
    async def jira_add_tag(self, issue: str, tag: str) -> Dict[str, Any]:
        """Add a tag to a ticket. Requires jira.write permission."""
        # 1. Fetch current labels
        current_tags = await self.jira_list_tags(issue)
        if tag in current_tags:
            return {"ok": True, "message": f"Tag '{tag}' already exists", "tags": current_tags}

        # 2. Add new tag
        new_tags = current_tags + [tag]
        await self.jira_update_issue(issue=issue, labels=new_tags)
        return {"ok": True, "added": tag, "tags": new_tags}

    @requires_permission('jira.write')
    @tool_schema(TagInput)
    async def jira_remove_tag(self, issue: str, tag: str) -> Dict[str, Any]:
        """Remove a tag from a ticket. Requires jira.write permission."""
        # 1. Fetch current labels
        current_tags = await self.jira_list_tags(issue)
        if tag not in current_tags:
            return {"ok": False, "message": f"Tag '{tag}' not found", "tags": current_tags}

        # 2. Remove tag
        new_tags = [t for t in current_tags if t != tag]
        await self.jira_update_issue(issue=issue, labels=new_tags)
        return {"ok": True, "removed": tag, "tags": new_tags}

__all__ = [
    "JiraToolkit",
    "JiraInput",
    "GetIssueInput",
    "SearchIssuesInput",
    "TransitionIssueInput",
    "AddAttachmentInput",
    "AssignIssueInput",
    "CreateIssueInput",
    "UpdateIssueInput",
    "FindIssuesByAssigneeInput",
    "GetTransitionsInput",
    "AddCommentInput",
    "AddWorklogInput",
    "GetIssueTypesInput",
    "GetProjectsInput",
    "VerifyAuthInput",
    "CountIssuesInput",
    "TicketIdInput",
    "ListHistoryInput",
    "TagInput",
    "FindUserInput",
    "ChangeAssigneeInput",
    "ChangeReporterInput",
    "AddComponentInput",
    "AddWatcherInput",
    "SetAcceptanceCriteriaInput",
    "ConfigureClientInput",
]
