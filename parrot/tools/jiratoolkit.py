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
from email.policy import strict
from typing import Any, Dict, List, Optional, Union
import os
import asyncio
import importlib
from pydantic import BaseModel, Field

from parrot.bots.prompts import data
try:
    # Optional config source; fall back to env vars if missing
    from navconfig import config as nav_config  # type: ignore
except Exception:  # pragma: no cover - optional
    nav_config = None

try:
    from jira import JIRA
except ImportError as e:  # pragma: no cover - optional
    raise ImportError("Please install the 'jira' package: pip install jira") from e

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
    max_results: int = Field(default=50, description="Max results per page (Jira default 50)")
    fields: Optional[str] = Field(default=None, description="Fields to return (comma-separated) or '*'")
    expand: Optional[str] = Field(default=None, description="Expand options")
    structured: Optional[StructuredOutputOptions] = Field(
        default=None,
        description="Optional structured output mapping",
        json_schema_extra=STRUCTURED_OUTPUT_FIELD_SCHEMA
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
    fields: Dict[str, Any] = Field(
        description="Issue fields payload, e.g., {'project': {'id': 123}, 'summary': '...', 'issuetype': {'name': 'Bug'}}"
    )


class UpdateIssueInput(BaseModel):
    """Input for updating an existing issue."""
    issue: str = Field(description="Issue key or id")
    summary: Optional[str] = Field(default=None, description="New summary")
    description: Optional[str] = Field(default=None, description="New description")
    assignee: Optional[Dict[str, Any]] = Field(default=None, description="New assignee dict")
    fields: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary field updates dict")


class FindIssuesByAssigneeInput(BaseModel):
    """Input for finding issues assigned to a given user."""
    assignee: str = Field(description="Assignee identifier (e.g., 'admin' or accountId)")
    project: Optional[str] = Field(default=None, description="Restrict to project key")
    max_results: int = Field(default=50, description="Max results")


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
    """

    # Expose the default input schema as metadata (optional)
    input_class = JiraInput

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
        options: Dict[str, Any] = {"server": self.server_url}

        if self.auth_type == "basic_auth":
            if not (self.username and self.password):
                raise ValueError("basic_auth requires username and password")
            return JIRA(options=options, basic_auth=(self.username, self.password))

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

    @tool_schema(SearchIssuesInput)
    async def jira_search_issues(
        self,
        jql: str,
        start_at: int = 0,
        max_results: int = 50,
        fields: Optional[str] = None,
        expand: Optional[str] = None,
        structured: Optional[StructuredOutputOptions] = None,
    ) -> Dict[str, Any]:
        """Search issues with JQL.

        Example: jira.search_issues('project=PROJ and assignee != currentUser()')
        """
        def _run():
            return self.jira.search_issues(
                jql,
                startAt=start_at,
                maxResults=max_results,
                fields=fields,
                expand=expand
            )

        results = await asyncio.to_thread(_run)
        # ResultList[Issue] is iterable; convert to list of dicts
        if structured:
            items = [self._apply_structured_output(self._issue_to_dict(it), structured) for it in results]
        else:
            items = [self._issue_to_dict(it) for it in results]
        return {"total": getattr(results, "total", len(items)), "issues": items}

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

        Example:
            jira.transition_issue(issue, '5', assignee={'name': 'pm_user'}, resolution={'id': '3'})
        """
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
    async def jira_create_issue(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new issue.

        Example:
            fields = {
                'project': {'id': 123},
                'summary': 'New issue from jira-python',
                'description': 'Look into this one',
                'issuetype': {'name': 'Bug'},
            }
            new_issue = jira.create_issue(fields=fields)
        """
        def _run():
            return self.jira.create_issue(fields=fields)

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
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Update an existing issue.

        Examples:
            issue.update(summary='new summary', description='A new summary was added')
            issue.update(assignee={'name': 'new_user'})
        """
        update_kwargs: Dict[str, Any] = {}
        if summary is not None:
            update_kwargs.setdefault("fields", {})["summary"] = summary
        if description is not None:
            update_kwargs.setdefault("fields", {})["description"] = description
        if assignee is not None:
            update_kwargs["assignee"] = assignee
        if fields:
            update_kwargs.setdefault("fields", {}).update(fields)

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
        jql = f"assignee={assignee}"
        if project or self.default_project:
            proj = project or self.default_project
            jql = f"project={proj} AND ({jql})"
        return await self.jira_search_issues(jql=jql, max_results=max_results)


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
]
