"""FEAT-608 TASK-3809 — the gdrive extra exists and is part of `all`."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _extras() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["optional-dependencies"]


def test_gdrive_extra_present_and_in_all():
    extras = _extras()
    assert extras["gdrive"] == ["aiogoogle>=5.17,<6", "aiofiles>=23.0"]
    self_ref = next(e for e in extras["all"] if e.startswith("ai-parrot["))
    assert "gdrive" in self_ref[len("ai-parrot[") : -1].split(",")


def test_agents_extra_keeps_its_aiogoogle_pin():
    assert "aiogoogle==5.17.0" in _extras()["agents"]
