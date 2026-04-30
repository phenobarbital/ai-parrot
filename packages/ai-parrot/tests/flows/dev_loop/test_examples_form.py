"""Tests for examples/dev_loop/server.py::_build_brief_from_form (TASK-902).

Loads the server module via importlib so the test does not require
``parrot_tools`` or a real Redis — only the pure form-builder function
is exercised.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_server():
    """Load examples/dev_loop/server.py via importlib without package import.

    Test file is at:
        packages/ai-parrot/tests/flows/dev_loop/test_examples_form.py
    parents[5] resolves to the repository root, then examples/ lives at:
        <repo_root>/examples/dev_loop/server.py
    """
    server_path = (
        Path(__file__).resolve().parents[5] / "examples" / "dev_loop" / "server.py"
    )
    spec = importlib.util.spec_from_file_location("dev_loop_server", server_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def server_module():
    return _load_server()


def _form_kwargs() -> dict:
    """Minimal valid form submission (no kind — tests that default applies)."""
    return {
        "summary": "Customer sync drops the last row when input has >1000 rows",
        "description": "Reproduce: upload 1500-row CSV.",
        "affected_component": "etl/customers/sync.yaml",
        "acceptance_criteria": ["ruff check ."],
        "reporter": "reporter@example.com",
        "escalation_assignee": "oncall@example.com",
    }


class TestKindNormalisation:
    """FEAT-132: kind field normalisation in _build_brief_from_form."""

    @pytest.mark.parametrize("label, expected", [
        ("Bug", "bug"),
        ("Enhancement", "enhancement"),
        ("New Feature", "new_feature"),
        ("BUG", "bug"),
        ("ENHANCEMENT", "enhancement"),
        ("new feature", "new_feature"),
        ("New feature", "new_feature"),
    ])
    def test_known_labels_normalise(self, server_module, label, expected):
        """Labels submitted by the UI radio group normalise to snake_case."""
        payload = server_module._build_brief_from_form(
            {**_form_kwargs(), "kind": label}
        )
        assert payload["kind"] == expected

    def test_default_kind_is_bug(self, server_module):
        """When kind is absent, the form-builder defaults to 'bug'."""
        payload = server_module._build_brief_from_form(_form_kwargs())
        assert payload["kind"] == "bug"

    def test_empty_kind_defaults_to_bug(self, server_module):
        """An explicitly empty kind string falls back to 'bug'."""
        payload = server_module._build_brief_from_form(
            {**_form_kwargs(), "kind": ""}
        )
        assert payload["kind"] == "bug"

    def test_unknown_kind_falls_back_to_bug(self, server_module):
        """An unrecognised kind value warns and defaults to 'bug'."""
        payload = server_module._build_brief_from_form(
            {**_form_kwargs(), "kind": "story"}
        )
        assert payload["kind"] == "bug"

    def test_none_kind_defaults_to_bug(self, server_module):
        """A None kind value defaults to 'bug'."""
        payload = server_module._build_brief_from_form(
            {**_form_kwargs(), "kind": None}
        )
        assert payload["kind"] == "bug"


class TestPayloadContainsKind:
    """kind key is always present in the returned payload."""

    def test_payload_always_has_kind(self, server_module):
        payload = server_module._build_brief_from_form(_form_kwargs())
        assert "kind" in payload

    def test_bug_kind_in_payload(self, server_module):
        payload = server_module._build_brief_from_form(
            {**_form_kwargs(), "kind": "Bug"}
        )
        assert payload["kind"] == "bug"
