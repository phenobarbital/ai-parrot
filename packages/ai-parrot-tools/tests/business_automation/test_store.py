"""Tests for PlanDirectoryStore (FEAT-453, Module 6, Goal G4).

FEAT-453 TASK-2391. No test in this file (or anywhere else in the feature)
may reference a real site — the fixture domain is a fictional "acme-books".
"""

import json
import shutil
import time
from pathlib import Path

import pytest
from parrot_tools.business_automation.store import PlanDirectoryStore

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "acme-books"


@pytest.fixture
def fixture_plans_dir(tmp_path: Path) -> Path:
    """A writable copy of the anonymized acme-books fixtures."""
    dest = tmp_path / "plans"
    shutil.copytree(FIXTURES_DIR, dest)
    return dest


class TestPlanDirectoryStore:
    def test_loads_fixture_dir(self, fixture_plans_dir):
        store = PlanDirectoryStore(fixture_plans_dir)
        store.load()
        assert "register_expense" in store.operations
        assert "list_clients" in store.operations
        assert "expense_flow" in store.templates
        assert "expense_flow" in store.flows

    def test_loaded_operation_kinds(self, fixture_plans_dir):
        store = PlanDirectoryStore(fixture_plans_dir)
        store.load()
        assert store.operations["register_expense"].kind.value == "submit"
        assert store.operations["list_clients"].kind.value == "read"

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            PlanDirectoryStore(tmp_path / "does-not-exist").load()

    def test_malformed_json_rejects_whole_dir(self, fixture_plans_dir):
        (fixture_plans_dir / "broken.operation.json").write_text("{ not json")
        with pytest.raises(ValueError, match="broken.operation.json"):
            PlanDirectoryStore(fixture_plans_dir).load()

    def test_malformed_rejection_leaves_prior_state_untouched(self, fixture_plans_dir):
        store = PlanDirectoryStore(fixture_plans_dir)
        store.load()
        assert "register_expense" in store.operations

        (fixture_plans_dir / "broken.operation.json").write_text("{ not json")
        with pytest.raises(ValueError):
            store.load()

        # The previously good state survives a failed reload.
        assert "register_expense" in store.operations

    def test_schema_violation_names_file_and_reason(self, fixture_plans_dir):
        (fixture_plans_dir / "invalid.operation.json").write_text(
            json.dumps({"name": "x"})  # missing required fields: description, kind, flow_ref
        )
        with pytest.raises(ValueError, match="invalid.operation.json"):
            PlanDirectoryStore(fixture_plans_dir).load()

    def test_literal_password_rejected(self, fixture_plans_dir):
        (fixture_plans_dir / "leaky.template.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "url_template": "http://x/",
                    "objective_template": "o",
                    "steps_template": [{"action": "authenticate", "username": "u", "password": "hunter2"}],
                }
            )
        )
        with pytest.raises(ValueError, match="password"):
            PlanDirectoryStore(fixture_plans_dir).load()

    def test_literal_password_never_appears_in_error(self, fixture_plans_dir):
        (fixture_plans_dir / "leaky.template.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "url_template": "http://x/",
                    "objective_template": "o",
                    "steps_template": [{"action": "authenticate", "username": "u", "password": "hunter2"}],
                }
            )
        )
        with pytest.raises(ValueError) as excinfo:
            PlanDirectoryStore(fixture_plans_dir).load()
        assert "hunter2" not in str(excinfo.value)

    def test_credential_provider_template_is_clean(self, fixture_plans_dir):
        (fixture_plans_dir / "clean_auth.template.json").write_text(
            json.dumps(
                {
                    "name": "clean_auth",
                    "url_template": "http://x/",
                    "objective_template": "o",
                    "steps_template": [{"action": "authenticate", "credential_provider": "acme-books"}],
                }
            )
        )
        # Must not raise — no literal password present.
        store = PlanDirectoryStore(fixture_plans_dir)
        store.load()
        assert "clean_auth" in store.templates

    def test_hot_reload_picks_up_change(self, fixture_plans_dir):
        store = PlanDirectoryStore(fixture_plans_dir)
        store.load()
        assert "new_operation" not in store.operations

        # Ensure a detectable mtime change on fast filesystems.
        time.sleep(0.01)
        (fixture_plans_dir / "new_operation.operation.json").write_text(
            json.dumps(
                {
                    "name": "new_operation",
                    "description": "Added after initial load",
                    "kind": "draft",
                    "flow_ref": "expense_flow",
                }
            )
        )

        changed = store.reload_if_changed()
        assert changed is True
        assert "new_operation" in store.operations

    def test_hot_reload_no_change_returns_false(self, fixture_plans_dir):
        store = PlanDirectoryStore(fixture_plans_dir)
        store.load()
        assert store.reload_if_changed() is False

    def test_fixtures_contain_no_site_reference(self):
        """AC: fixtures reference a fictional 'acme-books' site — never a
        real site (e.g. the vendor named in the spec's motivating example)."""
        for path in FIXTURES_DIR.glob("*.json"):
            content = path.read_text().lower()
            assert "hooba" not in content
