"""``parrot manuals`` click CLI (FEAT-601 M13)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from parrot.knowledge.manuals.export import ExportReport
from parrot_tools.procedures.cli import manuals

from ._doubles import FakeCatalog, make_card

BASE = ["--tenant", "t1", "--user", "op1"]


class _CliCatalog(FakeCatalog):
    """``FakeCatalog`` extended with the ``close()``/``verification_queue()`` the CLI needs."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.closed = False

    async def verification_queue(self, *, limit: int = 50) -> list[Any]:
        return []

    async def close(self) -> None:
        self.closed = True


class FakeLibrary:
    """Async ``ManualLibrary`` double; write commands record their calls for assertions."""

    def __init__(self, *, cards: list[Any] | None = None) -> None:
        self.catalog = _CliCatalog(cards=cards)
        self.file_manager = object()
        self.adapter = None
        self.graph_loader = None
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def add_manual(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("add_manual", args, kwargs))
        return {"status": "created"}

    async def add_video(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("add_video", args, kwargs))
        return {"status": "aligned"}

    async def refresh(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("refresh", args, kwargs))
        return {"status": "updated"}

    async def verify_procedure(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("verify_procedure", args, kwargs))
        return {"status": "verified"}


def _factory(library: Any) -> Any:
    return lambda **_: library


def test_help_lists_commands():
    result = CliRunner().invoke(manuals, ["--help"])
    for name in ("add", "add-video", "refresh", "verify", "queue", "relink-tips", "export", "spike"):
        assert name in result.output


def test_cli_export_is_curator_only(tmp_path):
    """technician context ⇒ AuthorizationDenied (non-zero exit, reason printed)."""
    lib = FakeLibrary()
    result = CliRunner().invoke(
        manuals, [*BASE, "--role", "technician", "export", "m1", "--out", str(tmp_path)], obj={"factory": _factory(lib)}
    )
    assert result.exit_code != 0 and "manual_curator" in result.output


def test_cli_export_with_curator_calls_export_bundle(tmp_path, monkeypatch):
    """curator context ⇒ export_bundle is called once and its report is printed as JSON."""
    from parrot.knowledge.manuals import export as export_module

    card = make_card(manual_id="m1")
    lib = FakeLibrary(cards=[card])
    mock_export = AsyncMock(return_value=ExportReport(bundle_dir=tmp_path / "m1.bundle"))
    monkeypatch.setattr(export_module, "export_bundle", mock_export)

    result = CliRunner().invoke(
        manuals,
        [*BASE, "--role", "manual_curator", "export", "m1", "--out", str(tmp_path)],
        obj={"factory": _factory(lib)},
    )

    assert result.exit_code == 0, result.output
    mock_export.assert_awaited_once()
    _, kwargs = mock_export.await_args
    assert kwargs["file_manager"] is lib.file_manager
    assert kwargs["out_dir"] == tmp_path
    assert kwargs["tips"] == ()
    assert str(tmp_path / "m1.bundle") in result.output


def test_cli_export_unknown_manual_reports_cleanly(tmp_path):
    """A curator exporting a manual the catalog does not have ⇒ non-zero exit, no export_bundle call."""
    lib = FakeLibrary()
    result = CliRunner().invoke(
        manuals,
        [*BASE, "--role", "manual_curator", "export", "missing", "--out", str(tmp_path)],
        obj={"factory": _factory(lib)},
    )
    assert result.exit_code != 0
    assert "missing" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["add", ".", "--equipment", "x", "--revision", "r1"],
        ["queue"],
        ["relink-tips", "m1"],
    ],
)
def test_cli_denies_technician_for_write_commands(args: list[str]):
    """Every write command shares the same curator-only gate as ``export`` (AC22)."""
    lib = FakeLibrary()
    result = CliRunner().invoke(manuals, [*BASE, "--role", "technician", *args], obj={"factory": _factory(lib)})
    assert result.exit_code != 0
    assert "manual_curator" in result.output


def test_cli_add_with_curator_calls_add_manual(tmp_path):
    lib = FakeLibrary()
    result = CliRunner().invoke(
        manuals,
        [*BASE, "--role", "manual_curator", "add", ".", "--equipment", "eq-x", "--revision", "A"],
        obj={"factory": _factory(lib)},
    )
    assert result.exit_code == 0, result.output
    assert lib.calls[0][0] == "add_manual"
