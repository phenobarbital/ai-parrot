"""FEAT-603 TASK-3765 — the msgraph extra exists and is part of `all`."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _extras() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["optional-dependencies"]


def test_msgraph_extra_present_and_in_all():
    extras = _extras()
    assert extras["msgraph"] == [
        "azure-identity>=1.18.0",
        "msgraph-sdk>=1.8.0",
        "microsoft-kiota-authentication-azure>=1.2.0",
    ]
    self_ref = next(e for e in extras["all"] if e.startswith("ai-parrot["))
    assert "msgraph" in self_ref[len("ai-parrot[") : -1].split(",")


def test_agents_extra_keeps_its_graph_pins():
    extras = _extras()
    for pin in extras["msgraph"]:
        assert pin in extras["agents"]
