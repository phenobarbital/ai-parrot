"""Tests for the swarm example docs/config — FEAT-463 TASK-2487."""
import pathlib

from parrot.integrations.matrix.crew.config import MatrixCrewConfig

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_swarm_example_loads(monkeypatch):
    for k, v in {
        "MATRIX_AS_TOKEN": "a",
        "MATRIX_HS_TOKEN": "h",
        "MATRIX_GENERAL_ROOM_ID": "!g:parrot.local",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = MatrixCrewConfig.from_yaml(str(ROOT / "examples/matrix_crew/swarm_crew.yaml"))
    assert [c.name for c in cfg.channels] == ["general", "finance"]
    assert cfg.channel("general").answer_policy == "swarm"
    assert cfg.tunnels.ttl_minutes == 120
    assert cfg.space.enabled is False


def test_docs_exist():
    for f in ("docs/integrations/matrix/CLIENTS.md", "docs/integrations/matrix/BRIDGES.md"):
        text = (ROOT / f).read_text().lower()
        assert text
    assert "notificationmixin" in (ROOT / "docs/integrations/matrix/BRIDGES.md").read_text()
    assert "element x" in (ROOT / "docs/integrations/matrix/CLIENTS.md").read_text().lower()
