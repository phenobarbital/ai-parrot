"""Shared raw-Jira payloads for the FEAT-454 test suites.

Plain functions, not pytest fixtures, so any test package can import them:
``from tests.fixtures.jira_payloads import raw_issue_payload``. Each package's
conftest wraps them in fixtures.
"""

from typing import Any


def raw_issue_payload() -> dict[str, Any]:
    """Raw Jira JSON for NAV-9372 with expand=renderedFields,changelog.

    Deliberately exercises every projection branch AND carries
    ``emailAddress`` on assignee, reporter and a changelog author so the
    G9 boundary is provable. Shared with TASK-2400/2401/2403.
    """
    return {
        "id": "184220",
        "key": "NAV-9372",
        "self": "https://example.atlassian.net/rest/api/2/issue/184220",
        "fields": {
            "project": {"key": "NAV", "name": "Navigator"},
            "issuetype": {"name": "Bug"},
            "status": {"name": "In Progress"},
            "resolution": None,
            "priority": {"name": "High"},
            "summary": "Forms lose the tenant when it is only in the URL",
            "assignee": {
                "accountId": "5f8a:abc-123",
                "displayName": "Jesus Lara",
                "emailAddress": "jlara@example.com",  # MUST be dropped
            },
            "reporter": {
                "accountId": "5f8a:def-456",
                "displayName": "Ana Ruiz",
                "emailAddress": "aruiz@example.com",  # MUST be dropped
            },
            "labels": ["multitenant", "forms"],
            "components": [{"name": "navigator-forms"}, {"name": "api"}],
            "parent": {"key": "NAV-9000"},
            "customfield_10014": "NAV-8000",  # epic link
            "subtasks": [{"key": "NAV-9373"}, {"key": "NAV-9374"}],
            "issuelinks": [
                {
                    "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                    "outwardIssue": {"key": "NAV-9400"},
                },
                {
                    "type": {"name": "Duplicate", "inward": "is duplicated by", "outward": "duplicates"},
                    "inwardIssue": {"key": "NAV-9111"},
                },
                {
                    "type": {"name": "Mitigates", "inward": "is mitigated by", "outward": "mitigates"},  # UNKNOWN type
                    "outwardIssue": {"key": "NAV-9500"},
                },
            ],
            "created": "2026-07-01T09:14:22.000+0000",
            "updated": "2026-08-20T16:02:07.000+0000",
            "resolutiondate": None,
            "attachment": [
                {
                    "filename": "trace.har",
                    "size": 20481,
                    "mimeType": "application/json",
                    "content": "https://example.atlassian.net/secure/attachment/1/trace.har",
                },
            ],
            "customfield_10101": "Given a tenant in the URL, when the form " "posts, then the tenant is preserved.",
        },
        "renderedFields": {
            "description": "<p>The form <code>POST</code> drops " "<strong>tenant</strong>.</p>",
            "customfield_10101": "<p>Given a tenant in the URL...</p>",
        },
        "changelog": {
            "histories": [
                {
                    "created": "2026-08-20T16:02:07.000+0000",
                    "author": {
                        "accountId": "5f8a:abc-123",
                        "displayName": "Jesus Lara",
                        "emailAddress": "jlara@example.com",
                    },
                    "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}],
                },
                {
                    "created": "2026-07-02T11:00:00.000+0000",
                    "author": {"accountId": "5f8a:def-456", "displayName": "Ana Ruiz"},
                    "items": [{"field": "priority", "fromString": "Medium", "toString": "High"}],
                },
            ]
        },
    }


def remote_links_payload() -> list[dict[str, Any]]:
    """Raw /remotelink payload (fetched separately by TASK-2400)."""
    return [{"object": {"title": "Runbook", "url": "https://wiki/runbook"}}]
