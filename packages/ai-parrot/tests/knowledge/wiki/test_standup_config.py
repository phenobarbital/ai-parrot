"""Regression cases for FEAT-627 standup configuration (TASK-4029)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

import parrot.knowledge.wiki.project as subject


def _write(root: Path, name: str, data: dict) -> None:
    (root / ".parrot").mkdir(exist_ok=True)
    (root / ".parrot" / name).write_text(json.dumps(data), encoding="utf-8")


def test_config_defaults_and_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults parse; base and overlay accept standup; overlay replaces whole field."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WIKI_ENV", raising=False)
    cfg = subject.StandupConfig()
    assert cfg.default_language == "en"
    assert cfg.horizon_days == 7
    assert cfg.week_start == "monday"
    assert cfg.timezone is None
    assert cfg.me.aliases == []
    assert cfg.ticket_status_map == subject.DEFAULT_TICKET_STATUS_MAP
    assert cfg.ticket_status_map is not subject.DEFAULT_TICKET_STATUS_MAP
    assert subject.WikiProjectConfig().standup == cfg
    assert subject.WikiEnvOverlay().standup is None

    _write(tmp_path, "wiki.json", {"standup": {"horizon_days": 3, "me": {"wiki": "human:a"}, "timezone": "UTC"}})
    _write(tmp_path, "wiki.test.json", {"standup": {"default_language": "es"}})
    eff = subject.load_effective_config(tmp_path, env="test")
    assert isinstance(eff.config.standup, subject.StandupConfig)
    assert eff.config.standup.default_language == "es"
    # whole-field replacement: base values are not merged in
    assert eff.config.standup.horizon_days == 7
    assert eff.config.standup.me.wiki is None

    base_only = subject.load_effective_config(tmp_path, env="nonexistent")
    assert base_only.config.standup.horizon_days == 3
    assert base_only.config.standup.me.wiki == "human:a"


@pytest.mark.parametrize(
    "bad",
    [
        {"timezone": "Not/AZone"},
        {"default_language": "fr"},
        {"week_start": "friday"},
        {"horizon_days": 0},
        {"horizon_days": 91},
        {"ticket_status_map": {"Weird": "nonsense"}},
        {"typo_key": 1},
        {"me": {"typo": "x"}},
    ],
)
def test_config_validation_rejects(bad: dict) -> None:
    """Invalid values and typo keys are rejected."""
    with pytest.raises(ValidationError):
        subject.StandupConfig.model_validate(bad)


def test_config_validation_overlay_rejects_and_accepts() -> None:
    """Overlay applies the same validation; valid custom map passes."""
    with pytest.raises(ValidationError):
        subject.WikiEnvOverlay.model_validate({"standup": {"week_start": "tuesday"}})
    ok = subject.StandupConfig(timezone="Europe/Madrid", ticket_status_map={"Triage": "open"})
    assert ok.timezone == "Europe/Madrid"


def test_config_import_budget() -> None:
    """Importing project must not import entities or standup packages."""
    code = (
        "import sys, parrot.knowledge.wiki.project;"
        "bad=[m for m in sys.modules if m.startswith('parrot.knowledge.wiki.standup') "
        "or m=='parrot.knowledge.wiki.entities'];"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
