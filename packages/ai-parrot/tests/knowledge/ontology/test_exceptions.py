"""Unit tests for FEAT-159 ontology curation exception types."""
import pytest
from parrot.knowledge.ontology.exceptions import (
    OntologyError,
    FrameworkOverrideError,
    CycleError,
    SynonymConflictError,
    DryRunFailedError,
    InvalidTransitionError,
)


class TestFrameworkOverrideError:
    def test_inherits_ontology_error(self):
        err = FrameworkOverrideError("cannot override Employee")
        assert isinstance(err, OntologyError)

    def test_stores_entity_name(self):
        err = FrameworkOverrideError("msg", entity_name="Employee")
        assert err.entity_name == "Employee"

    def test_entity_name_optional(self):
        err = FrameworkOverrideError("msg")
        assert err.entity_name is None

    def test_message_preserved(self):
        err = FrameworkOverrideError("cannot override Employee", entity_name="Employee")
        assert "cannot override Employee" in str(err)


class TestCycleError:
    def test_inherits_ontology_error(self):
        err = CycleError("cycle detected")
        assert isinstance(err, OntologyError)

    def test_stores_cycle_path(self):
        err = CycleError("cycle", cycle_path=["A", "B", "A"])
        assert err.cycle_path == ["A", "B", "A"]

    def test_cycle_path_defaults_to_empty_list(self):
        err = CycleError("cycle detected")
        assert err.cycle_path == []

    def test_message_preserved(self):
        err = CycleError("cycle in DAG")
        assert "cycle in DAG" in str(err)


class TestSynonymConflictError:
    def test_inherits_ontology_error(self):
        err = SynonymConflictError("conflict")
        assert isinstance(err, OntologyError)

    def test_stores_conflict_details(self):
        err = SynonymConflictError("msg", synonym="commissions", existing_slug="sales_comp")
        assert err.synonym == "commissions"
        assert err.existing_slug == "sales_comp"

    def test_optional_fields_default_to_none(self):
        err = SynonymConflictError("conflict")
        assert err.synonym is None
        assert err.existing_slug is None

    def test_message_preserved(self):
        err = SynonymConflictError("synonym already taken")
        assert "synonym already taken" in str(err)


class TestDryRunFailedError:
    def test_inherits_ontology_error(self):
        err = DryRunFailedError("dry run failed", report={"ok": False})
        assert isinstance(err, OntologyError)

    def test_stores_report(self):
        report = {"ok": False, "checks": [], "error": "bad AQL"}
        err = DryRunFailedError("failed", report=report)
        assert err.report == report

    def test_report_optional(self):
        err = DryRunFailedError("failed")
        assert err.report is None

    def test_message_preserved(self):
        err = DryRunFailedError("dry run failed")
        assert "dry run failed" in str(err)


class TestInvalidTransitionError:
    def test_inherits_ontology_error(self):
        err = InvalidTransitionError("invalid transition")
        assert isinstance(err, OntologyError)

    def test_stores_state_info(self):
        err = InvalidTransitionError(
            "cannot approve from rejected",
            current_state="rejected",
            requested_action="approve",
        )
        assert err.current_state == "rejected"
        assert err.requested_action == "approve"

    def test_optional_fields_default_to_none(self):
        err = InvalidTransitionError("bad transition")
        assert err.current_state is None
        assert err.requested_action is None
