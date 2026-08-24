"""Tests for bank-statement Excel ingestion (FEAT-453, Module 9, G7).

FEAT-453 TASK-2392. ``TestResumeWithoutDuplicates`` was added during the
feature's code-review remediation pass (AC-12): closes the gap where a
mid-run kill had no mechanism preventing a naive re-run from re-registering
every row. See the module docstring's "Resume-without-duplicates" section
and TASK-2392's completion-note addendum for the full rationale.
"""

import json
import stat

import pandas as pd
import pytest
from parrot_tools.business_automation.ingest import (
    build_import_plan,
    checkpoint_dir_for,
    compute_statement_digest,
    make_import_progress_listener,
    reconcile,
)


def _write_xlsx(path, rows):
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


@pytest.fixture
def three_row_xlsx(tmp_path):
    return _write_xlsx(
        tmp_path / "statement.xlsx",
        [
            {"client": "ACME", "amount": "100.00"},
            {"client": "Beta Corp", "amount": "42.50"},
            {"client": "Gamma LLC", "amount": "7.25"},
        ],
    )


@pytest.fixture
def xlsx_a(tmp_path):
    return _write_xlsx(tmp_path / "a.xlsx", [{"client": "ACME", "amount": "100.00"}])


@pytest.fixture
def xlsx_b(tmp_path):
    return _write_xlsx(tmp_path / "b.xlsx", [{"client": "Beta Corp", "amount": "42.50"}])


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    """Every test gets its own $PARROT_STATE_DIR so checkpoint state never
    leaks between tests or touches the real home directory."""
    state_dir = tmp_path / "state"
    monkeypatch.setenv("PARROT_STATE_DIR", str(state_dir))
    return state_dir


@pytest.fixture
def checkpoint_dir(isolated_state_dir):
    return isolated_state_dir / "business_automation" / "checkpoints" / "register_expense"


class TestIngest:
    async def test_one_node_per_row(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert len(bundle.plan.nodes) == 3
        assert bundle.row_count == 3

    async def test_nodes_carry_correct_values(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        clients = [n.args["params"]["client"] for n in bundle.plan.nodes]
        assert clients == ["ACME", "Beta Corp", "Gamma LLC"]

    async def test_nodes_are_chained_sequentially(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        nodes = bundle.plan.nodes
        assert nodes[0].depends_on == []
        assert nodes[1].depends_on == [nodes[0].id]
        assert nodes[2].depends_on == [nodes[1].id]

    async def test_max_parallel_tasks_is_one(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert bundle.plan.metadata.max_parallel_tasks == 1

    async def test_checkpoint_token_differs_per_statement(self, xlsx_a, xlsx_b):
        a = await build_import_plan(xlsx_a, period="2026-Q1")
        b = await build_import_plan(xlsx_b, period="2026-Q1")
        assert a.import_run.statement_digest != b.import_run.statement_digest
        assert a.plan.name != b.plan.name

    async def test_same_file_same_digest(self, three_row_xlsx):
        a = await build_import_plan(three_row_xlsx, period="2026-Q1")
        b = await build_import_plan(three_row_xlsx, period="2026-Q2")
        # Same bytes -> same digest, even across different periods.
        assert a.import_run.statement_digest == b.import_run.statement_digest

    async def test_checkpoint_permissions(self, three_row_xlsx, checkpoint_dir):
        await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert stat.S_IMODE(checkpoint_dir.stat().st_mode) == 0o700

    async def test_manifest_file_permissions(self, three_row_xlsx, checkpoint_dir):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        manifest = checkpoint_dir / f"{bundle.plan.name}.import.json"
        assert manifest.exists()
        assert stat.S_IMODE(manifest.stat().st_mode) == 0o600

    async def test_missing_column_raises(self, tmp_path):
        path = _write_xlsx(tmp_path / "bad.xlsx", [{"customer": "ACME", "total": "1"}])
        with pytest.raises(ValueError, match="Missing required column"):
            await build_import_plan(path, period="2026-Q1")

    def test_checkpoint_dir_outside_default_locations(self, isolated_state_dir):
        path = checkpoint_dir_for("register_expense")
        assert "obsidian" not in str(path).lower()
        assert "wiki" not in str(path).lower()
        assert str(path).startswith(str(isolated_state_dir))

    async def test_reconcile_matches(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        result = reconcile(bundle, registrations_out=3)
        assert result == {
            "rows_in": 3,
            "registrations_out": 3,
            "delta": 0,
            "reconciled": True,
        }

    async def test_reconcile_reports_shortfall(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        result = reconcile(bundle, registrations_out=2)
        assert result["delta"] == 1
        assert result["reconciled"] is False

    def test_digest_is_deterministic(self, three_row_xlsx):
        assert compute_statement_digest(three_row_xlsx) == compute_statement_digest(three_row_xlsx)


class TestResumeWithoutDuplicates:
    """AC-12: a mid-run kill must resume without re-registering rows."""

    async def test_listener_records_completed_row(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        digest = bundle.import_run.statement_digest
        listener = make_import_progress_listener("register_expense", digest)

        listener("node_completed", bundle.plan.nodes[0].id, {})

        rebuilt = await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert rebuilt.already_completed_rows == 1
        assert rebuilt.remaining_row_count == 2
        assert len(rebuilt.plan.nodes) == 2

    async def test_listener_ignores_other_events(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        digest = bundle.import_run.statement_digest
        listener = make_import_progress_listener("register_expense", digest)

        listener("node_started", bundle.plan.nodes[0].id, {})
        listener("node_failed", bundle.plan.nodes[1].id, {})

        rebuilt = await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert rebuilt.already_completed_rows == 0
        assert len(rebuilt.plan.nodes) == 3

    async def test_listener_ignores_a_different_digest(self, three_row_xlsx, xlsx_a):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        other_bundle = await build_import_plan(xlsx_a, period="2026-Q1")
        listener = make_import_progress_listener(
            "register_expense", other_bundle.import_run.statement_digest
        )

        # A node id from a DIFFERENT statement's plan must never mark this
        # statement's rows as completed.
        listener("node_completed", bundle.plan.nodes[0].id, {})

        rebuilt = await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert rebuilt.already_completed_rows == 0

    async def test_resumed_plan_preserves_dependency_chain(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        digest = bundle.import_run.statement_digest
        listener = make_import_progress_listener("register_expense", digest)
        listener("node_completed", bundle.plan.nodes[0].id, {})

        rebuilt = await build_import_plan(three_row_xlsx, period="2026-Q1")
        # Row 0 is gone; the first remaining node (row 1) must not depend on
        # the now-skipped row 0.
        assert rebuilt.plan.nodes[0].depends_on == []
        assert rebuilt.plan.nodes[1].depends_on == [rebuilt.plan.nodes[0].id]

    async def test_all_rows_completed_returns_no_plan(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        digest = bundle.import_run.statement_digest
        listener = make_import_progress_listener("register_expense", digest)
        for node in bundle.plan.nodes:
            listener("node_completed", node.id, {})

        rebuilt = await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert rebuilt.plan is None
        assert rebuilt.fully_completed is True
        assert rebuilt.already_completed_rows == 3
        assert rebuilt.remaining_row_count == 0

    async def test_reconcile_accounts_for_prior_completions(self, three_row_xlsx):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        digest = bundle.import_run.statement_digest
        listener = make_import_progress_listener("register_expense", digest)
        listener("node_completed", bundle.plan.nodes[0].id, {})

        rebuilt = await build_import_plan(three_row_xlsx, period="2026-Q1")
        # 1 already completed + 2 registered in this (resumed) run == 3 total.
        result = reconcile(rebuilt, registrations_out=2)
        assert result == {
            "rows_in": 3,
            "registrations_out": 3,
            "delta": 0,
            "reconciled": True,
        }

    async def test_manifest_survives_rebuild_without_losing_completions(
        self, three_row_xlsx, checkpoint_dir
    ):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        digest = bundle.import_run.statement_digest
        listener = make_import_progress_listener("register_expense", digest)
        listener("node_completed", bundle.plan.nodes[0].id, {})

        # Rebuilding the plan (simulating a restart) must not reset the
        # manifest's completed_rows back to empty.
        await build_import_plan(three_row_xlsx, period="2026-Q1")

        manifest = checkpoint_dir / f"{bundle.plan.name}.import.json"
        data = json.loads(manifest.read_text())
        assert data["completed_rows"] == [0]

    async def test_listener_survives_corrupt_manifest(self, three_row_xlsx, checkpoint_dir):
        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1")
        digest = bundle.import_run.statement_digest
        manifest = checkpoint_dir / f"{bundle.plan.name}.import.json"
        manifest.write_text("{not valid json")

        listener = make_import_progress_listener("register_expense", digest)
        # Must not raise — telemetry must never break the run.
        listener("node_completed", bundle.plan.nodes[0].id, {})
