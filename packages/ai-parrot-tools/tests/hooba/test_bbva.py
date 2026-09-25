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
    path = build_bbva_workbook(tmp_path / "bbva.xlsx")
    original_to_thread = asyncio.to_thread

    async def _passthrough(func, *args, **kwargs):
        assert func is _parse_bbva_sync
        return await original_to_thread(func, *args, **kwargs)

    with patch("parrot_tools.hooba.bank.bbva.asyncio.to_thread", side_effect=_passthrough) as mock_to_thread:
        await parse_bbva_statement(path)

    mock_to_thread.assert_called_once()


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
