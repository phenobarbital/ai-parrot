"""Tests for bank-statement Excel ingestion (FEAT-453, Module 9, G7).

FEAT-453 TASK-2392.
"""

import stat

import pandas as pd
import pytest
from parrot_tools.business_automation.ingest import (
    build_import_plan,
    checkpoint_dir_for,
    compute_statement_digest,
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
