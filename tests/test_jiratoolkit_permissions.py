"""
Tests for JiraToolkit permission annotations.

Verifies that the @requires_permission decorator is correctly applied to
JiraToolkit methods based on their read/write/admin classification.
"""
import pytest


class TestJiraToolkitPermissions:
    """Test that JiraToolkit methods have correct permission annotations."""

    @pytest.fixture
    def toolkit(self):
        """Create a JiraToolkit instance for testing.

        Uses mock credentials since we're only testing permission metadata,
        not actual Jira connectivity.
        """
        # Import here to avoid import errors if jira package not installed
        pytest.importorskip("jira")

        from unittest.mock import MagicMock, patch

        # Patch the JIRA client to avoid actual connection
        with patch("parrot.tools.jiratoolkit.JIRA") as mock_jira:
            mock_jira.return_value = MagicMock()
            from parrot.tools.jiratoolkit import JiraToolkit

            toolkit = JiraToolkit(
                server_url="https://test.atlassian.net",
                auth_type="basic_auth",
                username="test@example.com",
                password="test-token",
            )
            yield toolkit

    # ── Read-only methods — should have NO permission requirement ────────────

    def test_jira_get_issue_unrestricted(self, toolkit):
        """jira_get_issue is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_get_issue", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_search_issues_unrestricted(self, toolkit):
        """jira_search_issues is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_search_issues", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_get_transitions_unrestricted(self, toolkit):
        """jira_get_transitions is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_get_transitions", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_get_issue_types_unrestricted(self, toolkit):
        """jira_get_issue_types is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_get_issue_types", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_get_projects_unrestricted(self, toolkit):
        """jira_get_projects is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_get_projects", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_search_users_unrestricted(self, toolkit):
        """jira_search_users is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_search_users", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_find_issues_by_assignee_unrestricted(self, toolkit):
        """jira_find_issues_by_assignee is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_find_issues_by_assignee", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_count_issues_unrestricted(self, toolkit):
        """jira_count_issues is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_count_issues", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_list_tags_unrestricted(self, toolkit):
        """jira_list_tags is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_list_tags", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_find_user_unrestricted(self, toolkit):
        """jira_find_user is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_find_user", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_list_transitions_unrestricted(self, toolkit):
        """jira_list_transitions is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_list_transitions", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    def test_jira_list_assignees_unrestricted(self, toolkit):
        """jira_list_assignees is read-only and has no permission requirement."""
        method = getattr(toolkit, "jira_list_assignees", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", None)
        assert perms is None or perms == frozenset()

    # ── Write methods — should require jira.write permission ─────────────────

    def test_jira_create_issue_requires_write(self, toolkit):
        """jira_create_issue requires jira.write permission."""
        method = getattr(toolkit, "jira_create_issue", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_update_issue_requires_write(self, toolkit):
        """jira_update_issue requires jira.write permission."""
        method = getattr(toolkit, "jira_update_issue", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_transition_issue_requires_write(self, toolkit):
        """jira_transition_issue requires jira.write permission."""
        method = getattr(toolkit, "jira_transition_issue", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_add_comment_requires_write(self, toolkit):
        """jira_add_comment requires jira.write permission."""
        method = getattr(toolkit, "jira_add_comment", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_add_worklog_requires_write(self, toolkit):
        """jira_add_worklog requires jira.write permission."""
        method = getattr(toolkit, "jira_add_worklog", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_add_attachment_requires_write(self, toolkit):
        """jira_add_attachment requires jira.write permission."""
        method = getattr(toolkit, "jira_add_attachment", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_assign_issue_requires_write(self, toolkit):
        """jira_assign_issue requires jira.write permission."""
        method = getattr(toolkit, "jira_assign_issue", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_update_ticket_requires_write(self, toolkit):
        """jira_update_ticket requires jira.write permission."""
        method = getattr(toolkit, "jira_update_ticket", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_change_assignee_requires_write(self, toolkit):
        """jira_change_assignee requires jira.write permission."""
        method = getattr(toolkit, "jira_change_assignee", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_add_tag_requires_write(self, toolkit):
        """jira_add_tag requires jira.write permission."""
        method = getattr(toolkit, "jira_add_tag", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    def test_jira_remove_tag_requires_write(self, toolkit):
        """jira_remove_tag requires jira.write permission."""
        method = getattr(toolkit, "jira_remove_tag", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.write" in perms

    # ── Admin methods — should require jira.admin permission ─────────────────

    def test_jira_configure_client_requires_admin(self, toolkit):
        """jira_configure_client requires jira.admin permission."""
        method = getattr(toolkit, "jira_configure_client", None)
        assert method is not None
        perms = getattr(method, "_required_permissions", frozenset())
        assert "jira.admin" in perms


class TestJiraToolkitPermissionCoverage:
    """Test that permission coverage is comprehensive."""

    @pytest.fixture
    def toolkit_class(self):
        """Get the JiraToolkit class for inspection."""
        pytest.importorskip("jira")
        from parrot.tools.jiratoolkit import JiraToolkit

        return JiraToolkit

    def test_write_methods_annotated(self, toolkit_class):
        """Verify all expected write methods have jira.write permission."""
        write_methods = [
            "jira_create_issue",
            "jira_update_issue",
            "jira_transition_issue",
            "jira_add_comment",
            "jira_add_worklog",
            "jira_add_attachment",
            "jira_assign_issue",
            "jira_update_ticket",
            "jira_change_assignee",
            "jira_add_tag",
            "jira_remove_tag",
        ]

        for method_name in write_methods:
            method = getattr(toolkit_class, method_name, None)
            if method:
                perms = getattr(method, "_required_permissions", frozenset())
                assert "jira.write" in perms, (
                    f"{method_name} should require jira.write permission"
                )

    def test_admin_methods_annotated(self, toolkit_class):
        """Verify all expected admin methods have jira.admin permission."""
        admin_methods = [
            "jira_configure_client",
        ]

        for method_name in admin_methods:
            method = getattr(toolkit_class, method_name, None)
            if method:
                perms = getattr(method, "_required_permissions", frozenset())
                assert "jira.admin" in perms, (
                    f"{method_name} should require jira.admin permission"
                )

    def test_read_methods_not_restricted(self, toolkit_class):
        """Verify read-only methods have no permission restrictions."""
        read_methods = [
            "jira_get_issue",
            "jira_search_issues",
            "jira_get_transitions",
            "jira_get_issue_types",
            "jira_get_projects",
            "jira_search_users",
            "jira_find_issues_by_assignee",
            "jira_count_issues",
            "jira_list_tags",
            "jira_find_user",
            "jira_list_transitions",
            "jira_list_assignees",
            "jira_aggregate_data",
        ]

        for method_name in read_methods:
            method = getattr(toolkit_class, method_name, None)
            if method:
                perms = getattr(method, "_required_permissions", None)
                assert perms is None or perms == frozenset(), (
                    f"{method_name} should be unrestricted (read-only)"
                )
