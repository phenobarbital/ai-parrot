"""FEAT-784 M9a — wiki_spec_consequences operation, wiring and registration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.models import ADR_PATH_OUTSIDE_ROOT, ADR_SOURCE_UNAVAILABLE
from parrot.knowledge.wiki.decisions.operations import SpecConsequencesInput, op_spec_consequences
from parrot.knowledge.wiki.decisions.spec_audit import is_configured, open_consequence_service
from parrot.knowledge.wiki.project import WikiProjectConfig

from .._tool_surface import LOCAL_NO_LEDGER

_SPEC = "---\ntype: feature\n---\n# Spec\n\nBody.\n"


def _write_spec(root: Path, rel: str = "sdd/specs/demo.spec.md") -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SPEC, encoding="utf-8")
    return rel


def test_mcp_tool_registered():
    assert "wiki_spec_consequences" in LOCAL_NO_LEDGER


def test_is_configured(tmp_path: Path):
    assert not is_configured(tmp_path)
    (tmp_path / "sdd/taxonomy").mkdir(parents=True)
    (tmp_path / "sdd/taxonomy/subsystems.yaml").write_text("subsystems: []\n")
    assert is_configured(tmp_path)


def test_is_configured_by_approvals(tmp_path: Path):
    (tmp_path / "sdd/decisions").mkdir(parents=True)
    (tmp_path / "sdd/decisions/approvals.jsonl").write_text("")
    assert is_configured(tmp_path)


async def test_unconfigured_spec_is_skipped(tmp_path, adr_store):
    rel = _write_spec(tmp_path)
    result = await op_spec_consequences(
        adr_store, SpecConsequencesInput(spec_path=rel), root=tmp_path, config=WikiProjectConfig()
    )
    assert not result.is_error, result.text
    assert result.data["status"] == "skipped"
    assert result.data["check"] == "current"
    # The operation is read-only: the spec bytes are unchanged.
    assert (tmp_path / rel).read_text(encoding="utf-8") == _SPEC


async def test_check_data_equals_evaluator_report(tmp_path, adr_store):
    rel = _write_spec(tmp_path)
    config = WikiProjectConfig()
    service = open_consequence_service(tmp_path, store=adr_store, config=config)
    report = await service.evaluate(Path(rel))
    result = await op_spec_consequences(adr_store, SpecConsequencesInput(spec_path=rel), root=tmp_path, config=config)
    data = dict(result.data)
    data.pop("check")
    assert data == report.model_dump(mode="json")


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.spec.md", "sdd/../../x.md", ""])
async def test_rejects_path_outside_root(tmp_path, adr_store, bad):
    result = await op_spec_consequences(
        adr_store, SpecConsequencesInput(spec_path=bad), root=tmp_path, config=WikiProjectConfig()
    )
    assert result.is_error
    assert result.text.startswith(ADR_PATH_OUTSIDE_ROOT)


async def test_rejects_symlink_escape(tmp_path, adr_store):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.spec.md").write_text(_SPEC)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "link").symlink_to(outside)
    result = await op_spec_consequences(
        adr_store, SpecConsequencesInput(spec_path="link/x.spec.md"), root=root, config=WikiProjectConfig()
    )
    assert result.is_error and result.text.startswith(ADR_PATH_OUTSIDE_ROOT)


async def test_requires_root(adr_store):
    result = await op_spec_consequences(adr_store, SpecConsequencesInput(spec_path="a.md"))
    assert result.is_error


async def test_unbuilt_wiki_is_error_not_crash(tmp_path):
    (tmp_path / "sdd/taxonomy").mkdir(parents=True)
    (tmp_path / "sdd/taxonomy/subsystems.yaml").write_text("subsystems: []\n")
    rel = _write_spec(tmp_path)
    result = await op_spec_consequences(None, SpecConsequencesInput(spec_path=rel), root=tmp_path)
    assert result.is_error
    assert result.text.startswith(ADR_SOURCE_UNAVAILABLE)


async def test_operation_never_constructs_llm(tmp_path, adr_store, monkeypatch):
    from parrot.clients.factory import LLMFactory

    def _boom(*args, **kwargs):
        raise AssertionError("LLMFactory.create must never be called")

    monkeypatch.setattr(LLMFactory, "create", staticmethod(_boom))
    rel = _write_spec(tmp_path)
    for mode in ("check", "governing"):
        result = await op_spec_consequences(
            adr_store,
            SpecConsequencesInput(spec_path=rel, mode=mode),
            root=tmp_path,
            config=WikiProjectConfig(),
        )
        assert not result.is_error, result.text


def test_transport_import_is_lazy():
    code = (
        "import sys, parrot.knowledge.wiki.transport; "
        "assert 'parrot.knowledge.wiki.decisions.consequences' not in sys.modules; "
        "assert 'parrot.knowledge.wiki.decisions.spec_audit' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
