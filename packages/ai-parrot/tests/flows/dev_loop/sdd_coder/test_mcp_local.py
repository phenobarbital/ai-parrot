"""`parrot mcp-local sdd-coder` builds from the tracked example yaml (FEAT-549 AC-3)."""

from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop.sdd_coder import roster as roster_mod
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

EXPECTED = {
    f"coder_{n}"
    for n in (
        "plan",
        "run_chunk",
        "prepare_native",
        "merge",
        "wait",
        "status",
        "cleanup",
        "record_feedback",
        "record_review",
        "feedback_report",
        # FEAT-559 M4: the three new execution lifecycle/suspension tools.
        "begin_execution",
        "end_execution",
        "suspend_model",
        # FEAT-584 TASK-3560: native coders observe their own delivery events.
        "record_native_observation",
    )
}


def test_mcp_local_serves_sdd_coder(monkeypatch, tmp_path):
    async def fake_probe(self, roster):  # all seats available, no network
        return [
            roster_mod.SeatProbeResult(
                label=s.label, kind=s.kind, backend=s.backend, available=True, model_used=s.model
            )
            for s in roster.seats
        ]

    monkeypatch.setattr(roster_mod.RosterProbe, "probe", fake_probe)

    repo_root = Path(__file__).resolve().parents[6]
    config_path = repo_root / "examples" / "sdd-coder-mcp.yaml"
    assert config_path.is_file(), config_path

    server = create_toolkit_mcp_server("sdd-coder", root=tmp_path, config_path=str(config_path))
    assert set(server.tools) == EXPECTED


def test_mcp_local_starts_without_probe(monkeypatch, tmp_path):
    """FEAT-559: startup/registration must never probe before an execution reads history.

    Injects a probe that raises if ever called; constructing the server (tool
    registration, `_generate_tools()`) must not trigger it -- `auto_open`'s
    probe only fires lazily on the FIRST actual tool call, which never
    happens here.
    """

    async def _raising_probe(self, roster):
        raise AssertionError("probe must not be called before an execution begins")

    monkeypatch.setattr(roster_mod.RosterProbe, "probe", _raising_probe)

    repo_root = Path(__file__).resolve().parents[6]
    config_path = repo_root / "examples" / "sdd-coder-mcp.yaml"
    assert config_path.is_file(), config_path

    server = create_toolkit_mcp_server("sdd-coder", root=tmp_path, config_path=str(config_path))
    assert set(server.tools) == EXPECTED
