---
type: Wiki Entity
title: JiraToolkit
id: class:parrot_tools.jiratoolkit.JiraToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for interacting with Jira via pycontribs/jira.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# JiraToolkit

Defined in [`parrot_tools.jiratoolkit`](../summaries/mod:parrot_tools.jiratoolkit.md).

```python
class JiraToolkit(AbstractToolkit)
```

Toolkit for interacting with Jira via pycontribs/jira.

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

Custom-workflow keys (used by :meth:`jira_transition_to`):
    JIRA_WORKFLOW_PATH — default ordered status chain for any project,
        e.g. ``"Backlog > Open > To Do > In Progress > Resolved"`` (``>``,
        ``->`` and ``→`` are all accepted separators).
    JIRA_WORKFLOW_PATH_<PROJECT> — per-project override keyed by the issue
        key prefix, e.g. ``JIRA_WORKFLOW_PATH_TROC``. Falls back to
        JIRA_WORKFLOW_PATH when a project has no specific entry.

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

## Methods

- `def set_tool_manager(self, manager: ToolManager)` — Set the ToolManager reference for DataFrame sharing.
- `async def jira_get_issue(self, issue: str, fields: Optional[str]=None, expand: Optional[str]=None, structured: Optional[StructuredOutputOptions]=None, include_history: bool=False, history_page_size: int=100) -> JiraToolEnvelope` — Get a Jira issue by key or id.
- `async def jira_transition_issue(self, issue: str, transition: Union[str, int], fields: Optional[Dict[str, Any]]=None, assignee: Optional[Dict[str, Any]]=None, resolution: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Transition a Jira issue. Requires jira.write permission.
- `async def jira_transition_to(self, issue: str, target_status: str, fields: Optional[Dict[str, Any]]=None, assignee: Optional[Dict[str, Any]]=None, resolution: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Move an issue to *target_status*, walking every intermediate step.
- `async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]` — Add an attachment to an issue. Requires jira.write permission.
- `async def jira_assign_issue(self, issue: str, assignee: str) -> Dict[str, Any]` — Assign an issue to a user. Requires jira.write permission.
- `async def jira_create_issue(self, project: Optional[str]=None, summary: str='', issuetype: Optional[str]=None, description: Optional[str]=None, assignee: Optional[str]=None, priority: Optional[str]=None, labels: Optional[List[str]]=None, components: Optional[List[str]]=None, due_date: Optional[str]=None, parent: Optional[str]=None, original_estimate: Optional[str]=None, fields: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Create a new issue. Requires jira.write permission.
- `async def jira_update_issue(self, issue: str, summary: Optional[str]=None, description: Optional[str]=None, assignee: Optional[Dict[str, Any]]=None, acceptance_criteria: Optional[str]=None, original_estimate: Optional[str]=None, time_tracking: Optional[Dict[str, str]]=None, affected_versions: Optional[List[Dict[str, str]]]=None, due_date: Optional[str]=None, labels: Optional[List[str]]=None, issuetype: Optional[Dict[str, str]]=None, priority: Optional[Dict[str, str]]=None, fields: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Update an existing issue. Requires jira.write permission.
- `async def jira_find_issues_by_assignee(self, assignee: str, project: Optional[str]=None, max_results: int=50) -> Dict[str, Any]` — Find issues assigned to a given user (thin wrapper over jira_search_issues).
- `async def jira_get_transitions(self, issue: str, expand: Optional[str]=None) -> List[Dict[str, Any]]` — Get available transitions for an issue.
- `async def jira_add_comment(self, issue: str, body: str, is_internal: bool=False, attachments: Optional[List[str]]=None) -> Dict[str, Any]` — Add a comment to an issue, optionally attaching files. Requires jira.write permission.
- `async def jira_add_worklog(self, issue: str, time_spent: str, comment: Optional[str]=None, started: Optional[str]=None) -> Dict[str, Any]` — Add worklog to an issue. Requires jira.write permission.
- `async def jira_get_issue_types(self, project: Optional[str]=None) -> List[Dict[str, Any]]` — List issue types, optionally for a specific project.
- `async def jira_get_projects(self) -> Dict[str, Any]` — List all accessible projects.
- `async def jira_verify_auth(self) -> Dict[str, Any]` — Verify the toolkit is authenticated against Jira.
- `async def jira_get_components(self, project: Optional[str]=None) -> List[Dict[str, Any]]` — List all components for a project. Use this to find component IDs before creating issues.
- `async def jira_get_component_by_name(self, name: str, project: Optional[str]=None) -> Dict[str, Any]` — Find a component by name and return its details including the internal ID.
- `async def jira_search_users(self, user: Optional[str]=None, start_at: int=0, max_results: int=50, include_active: bool=True, include_inactive: bool=False, query: Optional[str]=None) -> JiraToolEnvelope` — Search for users matching the specified search string.
- `async def jira_search_issues(self, jql: str, start_at: int=0, max_results: Optional[int]=100, fields: Optional[str]=None, expand: Optional[str]=None, json_result: bool=True, store_as_dataframe: bool=False, dataframe_name: Optional[str]=None, summary_only: bool=False, structured: Optional[StructuredOutputOptions]=None) -> JiraToolEnvelope` — Search issues with JQL.
- `async def jira_count_issues(self, jql: str, group_by: Optional[List[str]]=None) -> Dict[str, Any]` — Count issues with optional grouping - optimized for efficiency.
- `async def jira_get_my_tickets(self, status: Optional[Union[str, List[str]]]=None, project: Optional[str]=None, include_closed: bool=False, max_results: Optional[int]=50, order_by: Optional[str]='updated DESC', fields: Optional[str]='key,summary,status,priority,issuetype,project,created,updated,duedate', summary_only: bool=False) -> Dict[str, Any]` — Retrieve the tickets assigned to the CURRENT (authenticated) Jira user.
- `async def jira_aggregate_data(self, dataframe_name: str='jira_issues', group_by: List[str]=None, aggregations: Dict[str, str]=None, sort_by: Optional[str]=None, ascending: bool=False) -> Dict[str, Any]` — Aggregate data from a stored Jira DataFrame.
- `async def jira_set_assignee(self, issue: str, assignee: str) -> Dict[str, Any]` — Set the assignee of an issue by email or accountId.
- `async def jira_set_reporter(self, issue: str, email: str) -> Dict[str, Any]` — Change the reporter of an issue by email.
- `async def jira_add_component(self, issue: str, component_name: str, project: Optional[str]=None) -> Dict[str, Any]` — Add a component to an issue by name.
- `async def jira_add_watcher(self, issue: str, email: str) -> Dict[str, Any]` — Add a user to an issue's watchers list ("who's looking").
- `async def jira_set_acceptance_criteria(self, issue: str, criteria: List[str], custom_field: Optional[str]=None) -> Dict[str, Any]` — Set the acceptance criteria checklist on an issue.
- `async def jira_configure_client(self, username: Optional[str]=None, password: Optional[str]=None, token: Optional[str]=None, auth_type: Optional[str]=None, server_url: Optional[str]=None) -> Dict[str, Any]` — Re-configure the Jira client with new credentials. Requires jira.admin permission.
- `async def jira_list_transitions(self, issue: str) -> List[Dict[str, Any]]` — List all status changes (transitions) for a ticket.
- `async def jira_list_assignees(self, issue: str) -> List[Dict[str, Any]]` — List all historical assignees of a ticket.
- `async def jira_update_ticket(self, **kwargs) -> Dict[str, Any]` — Update a ticket (alias for jira_update_issue). Requires jira.write permission.
- `async def jira_change_assignee(self, issue: str, assignee: str) -> Dict[str, Any]` — Change the ticket to a new assignee. Requires jira.write permission.
- `async def jira_find_user(self, email: str) -> Dict[str, Any]` — Find a user by email.
- `async def jira_list_tags(self, issue: str) -> List[str]` — List all tags (labels) added to a ticket.
- `async def jira_add_tag(self, issue: str, tag: str) -> Dict[str, Any]` — Add a tag to a ticket. Requires jira.write permission.
- `async def jira_remove_tag(self, issue: str, tag: str) -> Dict[str, Any]` — Remove a tag from a ticket. Requires jira.write permission.
