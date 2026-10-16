# F001 — JiraToolkit method coverage vs Atlassian MCP
Source: packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py (4344 lines), public `async def jira_*`.
Present: jira_get_issue:1600, jira_create_issue:2528, jira_update_issue:2713, jira_search_issues:3512,
jira_search_users:3280, jira_get_issue_types:2956 (proj.issueTypes only, no fields), jira_get_transitions:2841 /
jira_list_transitions:4242, jira_add_comment:2856 (add only), jira_get_projects:3142.
Absent (grep issue_link|createmeta|edit comment|accessible-resources → 0 hits in toolkit):
issue linking, createmeta fields per issue type, comment edit, cloud-id resolution as a tool.
