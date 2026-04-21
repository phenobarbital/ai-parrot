"""Unit tests for JiraWebhookHook._classify_event + _extract_assignee_change.

Covers the new ``assigned`` / ``unassigned`` branches added to support the
Jira → Telegram assignment-intake flow.
"""
from __future__ import annotations

import pytest

from parrot.core.hooks.jira_webhook import JiraWebhookHook


class TestClassifyEvent:
    def test_issue_created_without_assignee_is_created(self):
        payload = {
            "webhookEvent": "jira:issue_created",
            "issue": {"key": "NAV-1", "fields": {"assignee": None}},
        }
        assert JiraWebhookHook._classify_event(payload) == "created"

    def test_issue_created_with_assignee_is_assigned(self):
        payload = {
            "webhookEvent": "jira:issue_created",
            "issue": {
                "key": "NAV-1",
                "fields": {"assignee": {"accountId": "abc", "displayName": "Jane"}},
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "assigned"

    def test_issue_updated_assignee_changed_is_assigned(self):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [
                    {
                        "field": "assignee",
                        "from": None,
                        "to": "abc",
                        "fromString": None,
                        "toString": "Jane",
                    }
                ]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "assigned"

    def test_issue_updated_assignee_cleared_is_unassigned(self):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [
                    {
                        "field": "assignee",
                        "from": "abc",
                        "to": None,
                        "fromString": "Jane",
                        "toString": None,
                    }
                ]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "unassigned"

    def test_assignee_wins_over_status_change(self):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [
                    {
                        "field": "status",
                        "toString": "In Progress",
                    },
                    {
                        "field": "assignee",
                        "from": None,
                        "to": "abc",
                        "toString": "Jane",
                    },
                ]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "assigned"

    def test_status_closed_still_classified_when_no_assignee_change(self):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [{"field": "status", "toString": "Closed"}]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "closed"

    @pytest.mark.parametrize(
        "to_status",
        ["Ready For Test", "ready for test", "Ready for Testing", "READY FOR TESTING"],
    )
    def test_status_ready_for_test_is_classified(self, to_status):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [{"field": "status", "toString": to_status}]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "ready_for_test"

    def test_unknown_webhook_event_returns_none(self):
        assert JiraWebhookHook._classify_event({"webhookEvent": "jira:sprint_started"}) is None


class TestExtractAssigneeChange:
    def test_extracts_assignee_from_changelog(self):
        payload = {
            "changelog": {
                "items": [
                    {
                        "field": "assignee",
                        "from": "old-id",
                        "to": "new-id",
                        "fromString": "Old Dev",
                        "toString": "New Dev",
                    }
                ]
            }
        }
        prev, curr = JiraWebhookHook._extract_assignee_change(payload)
        assert prev == {"account_id": "old-id", "display_name": "Old Dev"}
        assert curr == {"account_id": "new-id", "display_name": "New Dev"}

    def test_created_event_has_no_previous(self):
        payload = {
            "issue": {
                "fields": {
                    "assignee": {"accountId": "abc", "displayName": "Jane"}
                }
            }
        }
        prev, curr = JiraWebhookHook._extract_assignee_change(payload)
        assert prev is None
        assert curr == {"account_id": "abc", "display_name": "Jane"}

    def test_returns_none_pair_when_nothing_present(self):
        assert JiraWebhookHook._extract_assignee_change({}) == (None, None)
