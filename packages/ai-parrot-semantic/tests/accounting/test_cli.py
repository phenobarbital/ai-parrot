"""FEAT-713 M8 — parrot finance CLI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
import pyarrow as pa
import pytest
import yaml
from click.testing import CliRunner

from parrot.auth.context import _pctx_var
from parrot.semantic.accounting import cli as finance_cli
from parrot.semantic.accounting.cli import finance
from parrot.semantic.accounting.models import ChartSnapshot

_FIXTURE_ASSERTION = '  - { expr: "gross_margin == revenue - cogs" }\n'


@pytest.fixture(autouse=True)
def _reset_pctx():
    """Isolate the module-level permission ContextVar between tests."""
    token = _pctx_var.set(None)
    yield
    _pctx_var.reset(token)


def _manifest(snapshot: ChartSnapshot, path: Path, extra: list[dict] | None = None) -> Path:
    """Write *snapshot* (plus *extra* account rows) as a YAML chart manifest."""
    rows = [
        {
            "account_id": account.account_id,
            "nature": account.nature,
            "parent_id": account.parent_id,
            "tags": list(account.tags),
        }
        for account in snapshot.accounts
    ]
    rows += extra or []
    path.write_text(yaml.safe_dump({"taken_at": snapshot.taken_at.isoformat(), "accounts": rows}), encoding="utf-8")
    return path


def _arrow_file(table: pa.Table, path: Path) -> Path:
    """Write *table* as an Arrow IPC file."""
    with pa.OSFile(str(path), "wb") as sink, pa.ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)
    return path


class _March2025(datetime):
    """Freezes the CLI clock at 2025-03-10 so the last closed month is February 2025 (has postings)."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return datetime(2025, 3, 10, 12, 0, tzinfo=tz)


def test_cli_validate_exit_codes(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    runner = CliRunner()
    manifest = _manifest(chart_snapshot, tmp_path / "chart.yaml")
    clean = runner.invoke(finance, ["validate", str(troc_pnl_yaml), "--snapshot", str(manifest)])
    assert clean.exit_code == 0, clean.output
    assert "structural validation passed" in clean.output
    assert "live column checks skipped" in clean.output

    broken_manifest = _manifest(
        chart_snapshot,
        tmp_path / "broken.yaml",
        extra=[{"account_id": "7000", "nature": "debit"}, {"account_id": "7100", "nature": "credit"}],
    )
    broken = runner.invoke(finance, ["validate", str(troc_pnl_yaml), "--snapshot", str(broken_manifest)])
    assert broken.exit_code == 1
    assert "unassigned_account" in broken.output
    assert "7000" in broken.output and "7100" in broken.output
    assert "interval" in broken.output
    assert "structural validation passed" not in broken.output


def test_cli_snapshot_inputs(troc_pnl_yaml, chart_snapshot, journal_frame, tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    missing = runner.invoke(finance, ["validate", str(troc_pnl_yaml)])
    assert missing.exit_code == 2
    assert "--snapshot" in missing.output

    manifest = _manifest(chart_snapshot, tmp_path / "chart.yaml")
    no_journal = runner.invoke(finance, ["validate", str(troc_pnl_yaml), "--snapshot", str(manifest), "--live"])
    assert no_journal.exit_code == 2
    assert "--journal-arrow" in no_journal.output

    bad_manifest = tmp_path / "chart.txt"
    bad_manifest.write_text("account_id\n4000\n", encoding="utf-8")
    bad = runner.invoke(finance, ["validate", str(troc_pnl_yaml), "--snapshot", str(bad_manifest)])
    assert bad.exit_code == 2
    assert "unsupported manifest suffix" in bad.output

    monkeypatch.setenv("FINANCE_AUDIT_MODE", "best_effort")
    monkeypatch.setattr(finance_cli, "datetime", _March2025)
    journal = _arrow_file(journal_frame, tmp_path / "journal.arrow")
    live = runner.invoke(
        finance,
        ["validate", str(troc_pnl_yaml), "--snapshot", str(manifest), "--live", "--journal-arrow", str(journal)],
    )
    assert live.exit_code == 0, live.output
    assert "chart drift: none" in live.output
    assert "assertion [passed] gross_margin == revenue - cogs" in live.output
    assert "2025-02-01 .. 2025-02-28" in live.output

    failing = troc_pnl_yaml.parent / "troc_fail.yaml"
    failing.write_text(
        troc_pnl_yaml.read_text(encoding="utf-8")
        .replace("model: troc_pnl\n", "model: troc_fail\n")
        .replace(_FIXTURE_ASSERTION, '  - { expr: "revenue == cogs", on_failure: flag }\n'),
        encoding="utf-8",
    )
    failed = runner.invoke(
        finance,
        ["validate", str(failing), "--snapshot", str(manifest), "--live", "--journal-arrow", str(journal)],
    )
    assert failed.exit_code == 1
    assert "assertion [failed] revenue == cogs" in failed.output


def test_cli_live_defaults_to_best_effort_audit(
    troc_pnl_yaml, chart_snapshot, journal_frame, tmp_path, monkeypatch
) -> None:
    """The CLI has no audit sink, so --live must not fail on the 'required' default unless the operator asks."""
    monkeypatch.delenv("FINANCE_AUDIT_MODE", raising=False)
    monkeypatch.setattr(finance_cli, "datetime", _March2025)
    manifest = _manifest(chart_snapshot, tmp_path / "chart.yaml")
    journal = _arrow_file(journal_frame, tmp_path / "journal.arrow")
    args = ["validate", str(troc_pnl_yaml), "--snapshot", str(manifest), "--live", "--journal-arrow", str(journal)]
    default = CliRunner().invoke(finance, args)
    assert default.exit_code == 0, default.output

    monkeypatch.setenv("FINANCE_AUDIT_MODE", "required")  # an explicit operator choice is honoured
    strict = CliRunner().invoke(finance, args)
    assert strict.exit_code == 1


def test_cli_explain(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    runner = CliRunner()
    manifest = _manifest(chart_snapshot, tmp_path / "chart.yaml")
    result = runner.invoke(finance, ["explain", str(troc_pnl_yaml), "gross_margin", "--snapshot", str(manifest)])
    assert result.exit_code == 0, result.output
    assert "Metric: gross_margin (model troc_pnl, tenant troc)" in result.output
    assert "Formula: revenue - cogs" in result.output
    assert "  - product_sales: 4000, 4010" in result.output
    assert "  - returns: 4900" in result.output
    cost_line = result.output.split("  - cost_of_sales: ")[1].split("\n")[0]
    assert "5000" in cost_line and "5900" not in cost_line
    assert "  - gross_margin == revenue - cogs" in result.output

    unknown = runner.invoke(finance, ["explain", str(troc_pnl_yaml), "nope", "--snapshot", str(manifest)])
    assert unknown.exit_code == 2
    assert "unknown metric 'nope'" in unknown.output

    missing = runner.invoke(finance, ["explain", str(troc_pnl_yaml), "revenue"])
    assert missing.exit_code == 2
    assert "--snapshot" in missing.output


def test_cli_lazy_registration() -> None:
    from parrot.cli import cli

    assert cli._lazy_commands["finance"] == "parrot.semantic.accounting.cli"
    assert "ai-parrot-semantic[duckdb]" in cli._lazy_extras["finance"]
    command = cli.get_command(click.Context(cli), "finance")
    assert command is finance
    assert isinstance(command, click.Group)
    assert {"validate", "explain"} <= set(command.commands)
