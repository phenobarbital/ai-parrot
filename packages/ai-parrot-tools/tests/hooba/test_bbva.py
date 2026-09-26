"""FEAT-602 TASK-3739 — BBVA parser and manifest."""

import asyncio
import stat
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import openpyxl
import pytest

from parrot_tools.hooba.bank import (
    ImportManifest,
    load_manifest,
    manifest_path_for,
    parse_bbva_statement,
    parse_es_amount,
    parse_es_date,
    reconcile,
    write_manifest,
)
from parrot_tools.hooba.bank.bbva import _parse_bbva_sync
from .fixtures.make_bbva_fixture import build_bbva_workbook


async def test_parse_bbva_fixture(tmp_path):
    path = build_bbva_workbook(tmp_path / "bbva.xlsx")

    statement = await parse_bbva_statement(path)

    assert statement.header_row == 6
    assert len(statement.rows) == 5
    assert statement.skipped == 2
    assert statement.row_count == 7

    digest_first = statement.digest
    statement_again = await parse_bbva_statement(path)
    assert statement_again.digest == digest_first


def test_parse_bbva_spanish_amounts_and_dates():
    assert parse_es_amount("-1.234,56") == Decimal("-1234.56")
    assert parse_es_amount("1.234,56 €") == Decimal("1234.56")
    assert parse_es_amount(-45.50) == Decimal("-45.5")
    assert parse_es_amount(None) is None
    assert parse_es_amount("") is None

    assert parse_es_date("03/09/2026") == date(2026, 9, 3)
    assert parse_es_date(datetime(2026, 9, 3)) == date(2026, 9, 3)
    assert parse_es_date(None) is None


async def test_parse_bbva_header_not_found(tmp_path):
    path = tmp_path / "no_header.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["not", "a", "bbva", "header"])
    ws.append(["still", "no", "match"])
    wb.save(path)

    with pytest.raises(ValueError):
        await parse_bbva_statement(path)


async def test_parse_bbva_runs_off_event_loop(tmp_path):
    """Both the primary parse and the ExcelLoader row-count cross-check run off the event loop.

    Regression: the ExcelLoader cross-check used to call ``await loader.load(...)`` directly
    on the caller's event loop (ExcelLoader._load_row_mode calls the blocking pd.read_excel()
    with no internal offloading) -- fixed by isolating that call in its own thread+loop too.
    """
    path = build_bbva_workbook(tmp_path / "bbva.xlsx")
    original_to_thread = asyncio.to_thread
    called_funcs = []

    async def _passthrough(func, *args, **kwargs):
        called_funcs.append(func)
        return await original_to_thread(func, *args, **kwargs)

    with patch("parrot_tools.hooba.bank.bbva.asyncio.to_thread", side_effect=_passthrough) as mock_to_thread:
        await parse_bbva_statement(path)

    assert mock_to_thread.call_count == 2
    assert called_funcs[0] is _parse_bbva_sync
    # The second offloaded call is a local closure (the ExcelLoader cross-check wrapper),
    # not a top-level importable symbol -- assert by name instead of identity.
    assert called_funcs[1].__name__ == "_load_documents_sync"


def test_manifest_permissions_and_reconcile(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_STATE_DIR", str(tmp_path))

    manifest = ImportManifest(
        statement_digest="abc123",
        period="2026-09",
        started_at=datetime.now(timezone.utc),
        row_count=7,
        completed={"abc123:0": 1, "abc123:1": 2},
        skipped={"abc123:5": "credit"},
    )

    written_path = write_manifest(manifest)

    assert stat.S_IMODE(written_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(written_path.parent.stat().st_mode) == 0o700

    loaded = load_manifest("abc123")
    assert loaded == manifest
    assert load_manifest("does-not-exist") is None

    result = reconcile(manifest, planned_rows=7)
    assert result == {"rows_in": 7, "drafts_out": 2, "skipped": 1, "delta": 4, "reconciled": False}


def test_manifest_path_scoped_by_account_id_never_collides(tmp_path, monkeypatch):
    """Regression: two different Hooba accounts sharing one $PARROT_STATE_DIR must never

    collide on the same manifest file, even when they import byte-identical statement
    content (same digest). Unscoped (``account_id=None``) stays the legacy path.
    """
    monkeypatch.setenv("PARROT_STATE_DIR", str(tmp_path))

    unscoped_path = manifest_path_for("same-digest")
    account_a_path = manifest_path_for("same-digest", account_id="111")
    account_b_path = manifest_path_for("same-digest", account_id="222")

    assert len({unscoped_path, account_a_path, account_b_path}) == 3  # all three distinct

    manifest_a = ImportManifest(
        statement_digest="same-digest",
        period="2026-09",
        started_at=datetime.now(timezone.utc),
        row_count=5,
        completed={"same-digest:0": 1},
    )
    manifest_b = manifest_a.model_copy(update={"completed": {"same-digest:0": 999}})

    write_manifest(manifest_a, account_id="111")
    write_manifest(manifest_b, account_id="222")

    assert load_manifest("same-digest", account_id="111") == manifest_a
    assert load_manifest("same-digest", account_id="222") == manifest_b
    assert load_manifest("same-digest") is None  # the unscoped path was never written


def test_reconcile_uses_manifest_row_count_not_this_runs_planned_rows():
    """Regression: a resumed/re-run must reconcile against the WHOLE statement, not just

    the remainder this particular run had left to plan. ``manifest.completed``/``.skipped``
    are cumulative across every run, but ``planned_rows`` reflects only this run's remainder
    (often 0 once everything is done) — using it for ``rows_in`` would make a fully and
    correctly completed resume falsely report ``reconciled=False``.
    """
    manifest = ImportManifest(
        statement_digest="resumed-run",
        period="2026-09",
        started_at=datetime.now(timezone.utc),
        row_count=3,  # the whole statement, set once when the manifest was first created
        completed={"resumed-run:0": 1, "resumed-run:1": 2, "resumed-run:2": 3},  # all 3 done, across prior runs
        skipped={},
    )

    # This run had nothing left to plan (everything was already completed by prior runs).
    result = reconcile(manifest, planned_rows=0)

    assert result == {"rows_in": 3, "drafts_out": 3, "skipped": 0, "delta": 0, "reconciled": True}
