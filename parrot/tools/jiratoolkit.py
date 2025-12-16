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
import logging
import asyncio
import importlib
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

from .toolkit import AbstractToolkit
from .decorators import tool_schema


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
    structured: Optional[StructuredOutputOptions] = Field(
        default=None,
        description="Optional structured output mapping",
        json_schema_extra=STRUCTURED_OUTPUT_FIELD_SCHEMA
    )


class SearchIssuesInput(BaseModel):
    """Input for searching issues with JQL."""
    jql: str = Field(description="JQL query, e.g. 'project=PROJ and assignee != currentUser()'")
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
        description="Project key, e.g. 'NAV' or project id"
    )
    summary: str = Field(
        description="Issue summary/title"
    )
    issuetype: str = Field(
        default="Task",
        description="Issue type name: 'Epic', 'Story', 'Bug', 'Task', 'Sub-task', etc."
    )
    description: Optional[str] = Field(
        default=None,
        description="Issue description"
    )
    assignee: Optional[str] = Field(
        default=None,
        description="Assignee account ID or username"
    )
    priority: Optional[str] = Field(
        default=None,
        description="Priority name: 'Highest', 'High', 'Medium', 'Low', 'Lowest'"
    )
    labels: Optional[List[str]] = Field(
        default=None,
        description="Labels list, e.g. ['backend', 'urgent']"
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in YYYY-MM-DD format"
    )
    parent: Optional[str] = Field(
        default=None,
        description="Parent issue key for sub-tasks or stories under epics"
    )
    original_estimate: Optional[str] = Field(
        default=None,
        description="Original time estimate, e.g. '8h', '2d', '30m'"
    )
    # Generic fields for any other issue data
    fields: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional fields dict for custom or less common fields"
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


class AddWorklogInput(BaseModel):
    """Input for adding a worklog to an issue."""
    issue: str = Field(description="Issue key or id")
    time_spent: str = Field(description="Time spent, e.g. '2h', '30m'")
    comment: Optional[str] = Field(default=None, description="Worklog comment")
    started: Optional[str] = Field(default=None, description="Date started (ISO-8601 or similar)")


class GetIssueTypesInput(BaseModel):
    """Input for listing issue types."""
    project: Optional[str] = Field(default=None, description="Project key to filter by. If omitted, returns all available types.")



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


# -----------------------------
# Toolkit implementation
# -----------------------------
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

    """

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

        self.server_url = server_url or _cfg("JIRA_INSTANCE") or ""
        if not self.server_url:
            raise ValueError(
                "Jira server_url is required (e.g., https://your.atlassian.net)"
            )

        self.logger = logging.getLogger(__name__)
        self.auth_type = (auth_type or _cfg("JIRA_AUTH_TYPE", "token_auth")).lower()
        self.username = username or _cfg("JIRA_USERNAME")
        self.password = password or _cfg("JIRA_PASSWORD") or _cfg("JIRA_API_TOKEN")
        self.token = token or _cfg("JIRA_SECRET_TOKEN")

        self.oauth_consumer_key = oauth_consumer_key or _cfg("JIRA_OAUTH_CONSUMER_KEY")
        self.oauth_key_cert = oauth_key_cert or _cfg("JIRA_OAUTH_KEY_CERT")
        self.oauth_access_token = oauth_access_token or _cfg("JIRA_OAUTH_ACCESS_TOKEN")
        self.oauth_access_token_secret = oauth_access_token_secret or _cfg("JIRA_OAUTH_ACCESS_TOKEN_SECRET")

        self.default_project = default_project or _cfg("JIRA_DEFAULT_PROJECT")

        # Create Jira client
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
                basic_auth=(self.username, self.password)
            )

        if self.auth_type == "token_auth":
            if not self.token:
                # Some setups use username+token via basic; keep token_auth strict here
                raise ValueError("token_auth requires a Personal Access Token")
            return JIRA(options=options, token_auth=self.token)

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
            return JIRA(options=options, oauth=oauth_dict)

        raise ValueError(f"Unsupported auth_type: {self.auth_type}")

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
                obj = _model.model_validate(payload) # type: ignore[attr-defined]
                return obj.model_dump() # type: ignore[attr-defined]
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

        return self._apply_structured_output(raw, structured) if structured else raw

    @tool_schema(TransitionIssueInput)
    async def jira_transition_issue(
        self,
        issue: str,
        transition: Union[str, int],
        fields: Optional[Dict[str, Any]] = None,
        assignee: Optional[Dict[str, Any]] = None,
        resolution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Transition a Jira issue.
        
        Automatically sets 8h original estimate for issues without one
        when transitioning to 'To Do', 'TODO', or 'In Progress'.

        Example:
            jira.transition_issue(issue, '5', assignee={'name': 'pm_user'}, resolution={'id': '3'})
        """
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

        def _run():
            # Transition may be id or name; let Jira client resolve
            return self.jira.transition_issue(issue, transition, **kwargs)

        await asyncio.to_thread(_run)
        # Return the latest state of the issue
        return await self.jira_get_issue(issue)

    @tool_schema(AddAttachmentInput)
    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]:
        """Add an attachment to an issue.

        Example: jira.add_attachment(issue=issue, attachment='/path/to/file.txt')
        """
        def _run():
            return self.jira.add_attachment(issue=issue, attachment=attachment)

        await asyncio.to_thread(_run)
        return {"ok": True, "issue": issue, "attachment": attachment}

    @tool_schema(AssignIssueInput)
    async def jira_assign_issue(self, issue: str, assignee: str) -> Dict[str, Any]:
        """Assign an issue to a user.

        Example: jira.assign_issue(issue, 'newassignee')
        """
        def _run():
            return self.jira.assign_issue(issue, assignee)

        await asyncio.to_thread(_run)
        return {"ok": True, "issue": issue, "assignee": assignee}

    @tool_schema(CreateIssueInput)
    async def jira_create_issue(
        self,
        project: str,
        summary: str,
        issuetype: str = "Task",
        description: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        labels: Optional[List[str]] = None,
        due_date: Optional[str] = None,
        parent: Optional[str] = None,
        original_estimate: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new issue.

        Examples:
            # Create a bug with estimate
            jira_create_issue(
                project='NAV',
                summary='Login button not working',
                issuetype='Bug',
                description='Users cannot click the login button',
                priority='High',
                original_estimate='4h'
            )
            
            # Create a story
            jira_create_issue(
                project='NAV',
                summary='Add user profile page',
                issuetype='Story',
                labels=['frontend', 'user-experience'],
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
        # Build fields dict
        issue_fields: Dict[str, Any] = {
            "project": {"key": project},
            "summary": summary,
            "issuetype": {"name": issuetype},
        }
        
        if description:
            issue_fields["description"] = description
        if assignee:
            issue_fields["assignee"] = {"accountId": assignee}
        if priority:
            issue_fields["priority"] = {"name": priority}
        if labels:
            issue_fields["labels"] = labels
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

        obj = await asyncio.to_thread(_run)
        data = self._issue_to_dict(obj)
        return {"ok": True, "id": data.get("id"), "key": data.get("key"), "issue": data}

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
        """Update an existing issue.

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

    @tool_schema(AddCommentInput)
    async def jira_add_comment(
        self,
        issue: str,
        body: str,
        is_internal: bool = False
    ) -> Dict[str, Any]:
        """Add a comment to an issue.

        Example: jira.jira_add_comment('JRA-1330', 'This is a comment')
        """
        def _run():
            return self.jira.add_comment(issue, body)

        comment = await asyncio.to_thread(_run)
        # Use helper to extract raw dict if available
        return self._issue_to_dict(comment)

    @tool_schema(AddWorklogInput)
    async def jira_add_worklog(
        self,
        issue: str,
        time_spent: str,
        comment: Optional[str] = None,
        started: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add worklog to an issue.

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

        types = await asyncio.to_thread(_run)
        # types is list of IssueType objects
        return [
            {"id": t.id, "name": t.name, "description": getattr(t, "description", "")}
            for t in types
        ]

    @tool_schema(GetProjectsInput)
    async def jira_get_projects(self) -> List[Dict[str, Any]]:
        """List all accessible projects.

        Example: jira.jira_get_projects()
        """
        def _run():
            return self.jira.projects()

        projs = await asyncio.to_thread(_run)
        return [{"id": p.id, "key": p.key, "name": p.name} for p in projs]

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
                'components': ','.join([c.get('name', '') for c in (fields.get('components') or [])]) if fields.get('components') else None,
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
            items = [self._apply_structured_output(it, structured) for it in issues]
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
            return {
                "error": "ToolManager not set. Cannot access stored DataFrames.",
                "suggestion": "First fetch data with jira_search_issues(fetch_all=True)"
            }
        
        try:
            df = self._tool_manager.get_shared_dataframe(dataframe_name)
        except KeyError:
            available = self._tool_manager.list_shared_dataframes()
            return {
                "error": f"DataFrame '{dataframe_name}' not found.",
                "available_dataframes": available,
                "suggestion": "First fetch data with jira_search_issues(fetch_all=True, dataframe_name='...')"
            }
        
        if df.empty:
            return {"error": "DataFrame is empty", "row_count": 0}
        
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
            return {
                "error": f"Aggregation failed: {e}",
                "available_columns": list(df.columns),
                "suggestion": "Check that group_by columns exist in the DataFrame"
            }

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
    "CountIssuesInput",
    "AggregateIssuesInput",
]
