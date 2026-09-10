"""`parrot mcp-local sdd-coder` builds from the tracked example yaml (FEAT-549 AC-3)."""
from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop.sdd_coder import roster as roster_mod
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

EXPECTED = {f"coder_{n}" for n in ("plan", "run_chunk", "prepare_native", "merge", "wait", "status", "cleanup")}


def test_mcp_local_serves_sdd_coder(monkeypatch, tmp_path):
    async def fake_probe(self, roster):  # all seats available, no network
        return [
            roster_mod.SeatProbeResult(label=s.label, kind=s.kind, backend=s.backend, available=True, model_used=s.model)
            for s in roster.seats
        ]

    monkeypatch.setattr(roster_mod.RosterProbe, "probe", fake_probe)

    repo_root = Path(__file__).resolve().parents[6]
    config_path = repo_root / "examples" / "sdd-coder-mcp.yaml"
    assert config_path.is_file(), config_path

    server = create_toolkit_mcp_server("sdd-coder", root=tmp_path, config_path=str(config_path))
    assert set(server.tools) == EXPECTED
