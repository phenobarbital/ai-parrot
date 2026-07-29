---
type: Wiki Summary
title: parrot_tools.jiratoolkit
id: mod:parrot_tools.jiratoolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Jira Toolkit - A unified toolkit for Jira operations using pycontribs/jira.
relates_to:
- concept: class:parrot_tools.jiratoolkit.AddAttachmentInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.AddCommentInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.AddComponentInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.AddWatcherInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.AddWorklogInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.AggregateJiraDataInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.AssignIssueInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.ChangeAssigneeInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.ChangeReporterInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.ConfigureClientInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.CountIssuesInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.CreateIssueInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.FindIssuesByAssigneeInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.FindUserInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.GetComponentByNameInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.GetComponentsInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.GetIssueInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.GetIssueTypesInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.GetMyTicketsInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.GetProjectsInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.GetTransitionsInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.JiraInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.JiraToolEnvelope
  rel: defines
- concept: class:parrot_tools.jiratoolkit.JiraToolkit
  rel: defines
- concept: class:parrot_tools.jiratoolkit.ListHistoryInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.SearchIssuesInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.SearchUsersInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.SetAcceptanceCriteriaInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.StructuredOutputOptions
  rel: defines
- concept: class:parrot_tools.jiratoolkit.TagInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.TicketIdInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.TransitionIssueInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.TransitionToInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.UpdateIssueInput
  rel: defines
- concept: class:parrot_tools.jiratoolkit.VerifyAuthInput
  rel: defines
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.jiratoolkit`

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

## Classes

- **`JiraToolEnvelope(TypedDict)`** — Uniform return shape for all JiraToolkit read methods.
- **`StructuredOutputOptions(BaseModel)`** — Options to shape the output of Jira items into either a whitelist or a Pydantic model.
- **`JiraInput(BaseModel)`** — Default input for Jira tools: holds auth + default project context.
- **`GetIssueInput(BaseModel)`** — Input for getting a single issue.
- **`SearchIssuesInput(BaseModel)`** — Input for searching issues with JQL.
- **`CountIssuesInput(BaseModel)`** — Optimized input for counting issues - requests minimal fields.
- **`GetMyTicketsInput(BaseModel)`** — Input for retrieving the CURRENT (authenticated) user's Jira tickets.
- **`AggregateJiraDataInput(BaseModel)`** — Input for aggregating stored Jira data.
- **`TransitionIssueInput(BaseModel)`** — Input for transitioning an issue.
- **`TransitionToInput(BaseModel)`** — Input for walking an issue to a target status across a custom workflow.
- **`AddAttachmentInput(BaseModel)`** — Input for adding an attachment to an issue.
- **`AssignIssueInput(BaseModel)`** — Input for assigning an issue to a user.
- **`CreateIssueInput(BaseModel)`** — Input for creating a new issue.
- **`UpdateIssueInput(BaseModel)`** — Input for updating an existing issue.
- **`FindIssuesByAssigneeInput(BaseModel)`** — Input for finding issues assigned to a given user.
- **`GetTransitionsInput(BaseModel)`** — Input for getting available transitions for an issue.
- **`AddCommentInput(BaseModel)`** — Input for adding a comment to an issue.
- **`AddWorklogInput(BaseModel)`** — Input for adding a worklog to an issue.
- **`GetIssueTypesInput(BaseModel)`** — Input for listing issue types.
- **`SearchUsersInput(BaseModel)`** — Input for searching users.
- **`GetProjectsInput(BaseModel)`** — Input for listing projects.
- **`VerifyAuthInput(BaseModel)`** — Input for verifying Jira authentication.
- **`GetComponentsInput(BaseModel)`** — Input for listing project components.
- **`GetComponentByNameInput(BaseModel)`** — Input for finding a component by name.
- **`TicketIdInput(BaseModel)`** — Input for generic ticket operations.
- **`FindUserInput(BaseModel)`** — Input for finding a user.
- **`TagInput(BaseModel)`** — Input for tag operations.
- **`ChangeAssigneeInput(BaseModel)`** — Input for changing assignee.
- **`ListHistoryInput(BaseModel)`** — Input for listing history.
- **`ChangeReporterInput(BaseModel)`** — Input for changing the reporter of an issue.
- **`AddComponentInput(BaseModel)`** — Input for adding a component to an issue by name.
- **`AddWatcherInput(BaseModel)`** — Input for adding a watcher to an issue.
- **`SetAcceptanceCriteriaInput(BaseModel)`** — Input for setting acceptance criteria on an issue.
- **`ConfigureClientInput(BaseModel)`** — Input for re-configuring the Jira client.
- **`JiraToolkit(AbstractToolkit)`** — Toolkit for interacting with Jira via pycontribs/jira.
