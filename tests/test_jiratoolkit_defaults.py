"""
Tests for JiraToolkit default fields for ticket creation (FEAT-052).

Covers:
- _parse_csv helper
- Default application in jira_create_issue
- Explicit overrides
- jira_get_components
- Due date offset calculation
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# Helper: _parse_csv
# ---------------------------------------------------------------------------

class TestParseCsv:
    """Unit tests for the _parse_csv helper function."""

    def _import(self):
        pytest.importorskip("jira")
        from parrot.tools.jiratoolkit import _parse_csv
        return _parse_csv

    def test_empty_string(self):
        _parse_csv = self._import()
        assert _parse_csv("") == []

    def test_none_like_empty(self):
        _parse_csv = self._import()
        assert _parse_csv("") == []

    def test_single_value(self):
        _parse_csv = self._import()
        assert _parse_csv("backend") == ["backend"]

    def test_multiple_values(self):
        _parse_csv = self._import()
        assert _parse_csv("backend,frontend") == ["backend", "frontend"]

    def test_whitespace_handling(self):
        _parse_csv = self._import()
        assert _parse_csv(" backend , frontend ") == ["backend", "frontend"]

    def test_trailing_comma(self):
        _parse_csv = self._import()
        assert _parse_csv("backend,") == ["backend"]

    def test_empty_segments_ignored(self):
        _parse_csv = self._import()
        assert _parse_csv("a,,b,,,c") == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Fixture: mocked JiraToolkit
# ---------------------------------------------------------------------------

@pytest.fixture
def make_toolkit():
    """Factory fixture that creates a JiraToolkit with mocked JIRA client and optional env vars."""
    pytest.importorskip("jira")

    def _factory(env_overrides=None):
        env = env_overrides or {}
        with patch("parrot.tools.jiratoolkit.JIRA") as mock_jira_cls, \
             patch.dict("os.environ", env, clear=False):
            mock_jira_cls.return_value = MagicMock()
            from parrot.tools.jiratoolkit import JiraToolkit
            toolkit = JiraToolkit(
                server_url="https://test.atlassian.net",
                auth_type="basic_auth",
                username="test@example.com",
                password="test-token",
            )
            return toolkit, mock_jira_cls.return_value

    return _factory


# ---------------------------------------------------------------------------
# Default application in jira_create_issue
# ---------------------------------------------------------------------------

class TestCreateIssueDefaults:
    """Test that configured defaults are applied when fields are omitted."""

    @pytest.mark.asyncio
    async def test_all_defaults_applied(self, make_toolkit):
        """AC-1, AC-2, AC-3, AC-5, AC-7, AC-8: All defaults applied when fields omitted."""
        env = {
            "JIRA_DEFAULT_PROJECT": "NAV",
            "JIRA_DEFAULT_ISSUE_TYPE": "Task",
            "JIRA_DEFAULT_LABELS": "backend,ai-parrot",
            "JIRA_DEFAULT_COMPONENTS": "10042",
            "JIRA_DEFAULT_DUE_DATE_OFFSET": "14",
            "JIRA_DEFAULT_ESTIMATE": "4h",
        }
        toolkit, mock_jira = make_toolkit(env)

        # Mock create_issue to capture the fields dict
        mock_issue = MagicMock()
        mock_issue.raw = {"id": "1", "key": "NAV-100", "fields": {"summary": "Test"}}
        mock_issue.id = "1"
        mock_issue.key = "NAV-100"
        mock_jira.create_issue.return_value = mock_issue

        await toolkit.jira_create_issue(summary="Test ticket")

        # Extract the fields dict passed to create_issue
        call_args = mock_jira.create_issue.call_args
        fields = call_args[1].get("fields") or call_args[0][0] if call_args[0] else call_args[1]["fields"]

        assert fields["project"] == {"key": "NAV"}
        assert fields["issuetype"] == {"name": "Task"}
        assert fields["labels"] == ["backend", "ai-parrot"]
        assert fields["components"] == [{"id": "10042"}]
        assert "duedate" in fields
        # Verify due date is ~14 days from now
        expected_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        assert fields["duedate"] == expected_date
        assert fields["timetracking"] == {"originalEstimate": "4h"}

    @pytest.mark.asyncio
    async def test_explicit_overrides_defaults(self, make_toolkit):
        """AC-9: Explicit values override all defaults."""
        env = {
            "JIRA_DEFAULT_PROJECT": "NAV",
            "JIRA_DEFAULT_ISSUE_TYPE": "Task",
            "JIRA_DEFAULT_LABELS": "backend,ai-parrot",
            "JIRA_DEFAULT_COMPONENTS": "10042",
            "JIRA_DEFAULT_ESTIMATE": "4h",
        }
        toolkit, mock_jira = make_toolkit(env)

        mock_issue = MagicMock()
        mock_issue.raw = {"id": "2", "key": "OTHER-1", "fields": {"summary": "Test"}}
        mock_issue.id = "2"
        mock_issue.key = "OTHER-1"
        mock_jira.create_issue.return_value = mock_issue

        await toolkit.jira_create_issue(
            project="OTHER",
            summary="Explicit test",
            issuetype="Bug",
            labels=["frontend"],
            components=["99999"],
            due_date="2026-12-31",
            original_estimate="8h",
        )

        fields = mock_jira.create_issue.call_args[1]["fields"]

        assert fields["project"] == {"key": "OTHER"}
        assert fields["issuetype"] == {"name": "Bug"}
        assert fields["labels"] == ["frontend"]
        assert fields["components"] == [{"id": "99999"}]
        assert fields["duedate"] == "2026-12-31"
        assert fields["timetracking"] == {"originalEstimate": "8h"}

    @pytest.mark.asyncio
    async def test_no_defaults_backward_compat(self, make_toolkit):
        """AC-10: No defaults set — only explicitly passed fields are in the dict."""
        # No JIRA_DEFAULT_* env vars — but we need to clear them if inherited
        env = {
            "JIRA_DEFAULT_LABELS": "",
            "JIRA_DEFAULT_COMPONENTS": "",
            "JIRA_DEFAULT_DUE_DATE_OFFSET": "",
            "JIRA_DEFAULT_ESTIMATE": "",
        }
        toolkit, mock_jira = make_toolkit(env)

        mock_issue = MagicMock()
        mock_issue.raw = {"id": "3", "key": "NAV-3", "fields": {"summary": "Test"}}
        mock_issue.id = "3"
        mock_issue.key = "NAV-3"
        mock_jira.create_issue.return_value = mock_issue

        await toolkit.jira_create_issue(
            project="NAV",
            summary="Backward compat test",
        )

        fields = mock_jira.create_issue.call_args[1]["fields"]

        assert fields["project"] == {"key": "NAV"}
        assert fields["summary"] == "Backward compat test"
        # These should NOT be present when no defaults and no explicit values
        assert "labels" not in fields
        assert "components" not in fields
        assert "duedate" not in fields
        assert "timetracking" not in fields

    @pytest.mark.asyncio
    async def test_components_converted_to_id_dicts(self, make_toolkit):
        """AC-4: Components parameter converts IDs to {"id": ...} format."""
        toolkit, mock_jira = make_toolkit()

        mock_issue = MagicMock()
        mock_issue.raw = {"id": "4", "key": "NAV-4", "fields": {"summary": "Test"}}
        mock_issue.id = "4"
        mock_issue.key = "NAV-4"
        mock_jira.create_issue.return_value = mock_issue

        await toolkit.jira_create_issue(
            project="NAV",
            summary="Component test",
            components=["10042", "10043"],
        )

        fields = mock_jira.create_issue.call_args[1]["fields"]
        assert fields["components"] == [{"id": "10042"}, {"id": "10043"}]


# ---------------------------------------------------------------------------
# jira_get_components
# ---------------------------------------------------------------------------

class TestGetComponents:
    """Test jira_get_components method."""

    @pytest.mark.asyncio
    async def test_returns_component_list(self, make_toolkit):
        """AC-6: jira_get_components returns list of dicts with id, name, description."""
        toolkit, mock_jira = make_toolkit()

        # Mock project_components to return component-like objects
        comp1 = MagicMock()
        comp1.id = "10042"
        comp1.name = "Backend"
        comp1.description = "Backend services"

        comp2 = MagicMock()
        comp2.id = "10043"
        comp2.name = "Frontend"
        comp2.description = "Frontend UI"

        mock_jira.project_components.return_value = [comp1, comp2]

        result = await toolkit.jira_get_components(project="NAV")

        assert len(result) == 2
        assert result[0] == {"id": "10042", "name": "Backend", "description": "Backend services"}
        assert result[1] == {"id": "10043", "name": "Frontend", "description": "Frontend UI"}
        mock_jira.project_components.assert_called_once_with("NAV")

    @pytest.mark.asyncio
    async def test_uses_default_project(self, make_toolkit):
        """jira_get_components falls back to default_project when project is omitted."""
        env = {"JIRA_DEFAULT_PROJECT": "MYPROJ"}
        toolkit, mock_jira = make_toolkit(env)

        mock_jira.project_components.return_value = []

        await toolkit.jira_get_components()

        mock_jira.project_components.assert_called_once_with("MYPROJ")

    @pytest.mark.asyncio
    async def test_raises_without_project(self, make_toolkit):
        """jira_get_components raises ValueError if no project and no default."""
        # Force no default project
        toolkit, mock_jira = make_toolkit()
        toolkit.default_project = None

        with pytest.raises(ValueError, match="Project key is required"):
            await toolkit.jira_get_components()

    @pytest.mark.asyncio
    async def test_component_without_description(self, make_toolkit):
        """jira_get_components handles components with no description attribute."""
        toolkit, mock_jira = make_toolkit()

        comp = MagicMock(spec=["id", "name"])  # no description attribute
        comp.id = "10044"
        comp.name = "Infra"

        mock_jira.project_components.return_value = [comp]

        result = await toolkit.jira_get_components(project="NAV")

        assert result[0]["description"] == ""


# ---------------------------------------------------------------------------
# Due date offset
# ---------------------------------------------------------------------------

class TestDueDateOffset:
    """Test due date offset calculation."""

    @pytest.mark.asyncio
    async def test_due_date_offset_applied(self, make_toolkit):
        """AC-7: Due date set to today + N days when offset configured."""
        env = {"JIRA_DEFAULT_DUE_DATE_OFFSET": "7"}
        toolkit, mock_jira = make_toolkit(env)

        mock_issue = MagicMock()
        mock_issue.raw = {"id": "5", "key": "NAV-5", "fields": {"summary": "Test"}}
        mock_issue.id = "5"
        mock_issue.key = "NAV-5"
        mock_jira.create_issue.return_value = mock_issue

        await toolkit.jira_create_issue(project="NAV", summary="Due date test")

        fields = mock_jira.create_issue.call_args[1]["fields"]
        expected = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        assert fields["duedate"] == expected

    @pytest.mark.asyncio
    async def test_invalid_offset_ignored(self, make_toolkit):
        """Invalid JIRA_DEFAULT_DUE_DATE_OFFSET is logged and ignored."""
        env = {"JIRA_DEFAULT_DUE_DATE_OFFSET": "not_a_number"}
        toolkit, mock_jira = make_toolkit(env)

        mock_issue = MagicMock()
        mock_issue.raw = {"id": "6", "key": "NAV-6", "fields": {"summary": "Test"}}
        mock_issue.id = "6"
        mock_issue.key = "NAV-6"
        mock_jira.create_issue.return_value = mock_issue

        # Should not raise
        await toolkit.jira_create_issue(project="NAV", summary="Invalid offset test")

        fields = mock_jira.create_issue.call_args[1]["fields"]
        assert "duedate" not in fields
