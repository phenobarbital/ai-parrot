"""FEAT-715 assets: the .gitignore whitelist (AC16) and the base Jira template."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import jinja2
import pytest

REPO = Path(__file__).resolve().parents[4]
TEMPLATE_DIR = REPO / "agents" / "fireflies_insights" / "templates"
PARAMS = {
    "meeting_title": "Weekly sync", "meeting_date": "2026-10-22", "meeting_id": "01KZ",
    "action_title": "Ship the importer", "owner": None, "due_date": None,
    "evidence": "Ana: I will ship it", "decisions": ["Go"], "risks": [], "wiki_url": None,
}


def _ignored(repo: Path, rel: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", rel], check=False).returncode == 0


def test_gitignore_whitelists_only_this_agent(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    shutil.copy(REPO / ".gitignore", tmp_path / ".gitignore")
    for rel in ("agents/fireflies_insights/skills/s/SKILL.md", "agents/fireflies_insights/templates/x.j2",
                "agents/fireflies_insights/secret_runtime.json", "agents/porygon/skills/x.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    assert not _ignored(tmp_path, "agents/fireflies_insights/skills/s/SKILL.md")
    assert not _ignored(tmp_path, "agents/fireflies_insights/templates/x.j2")
    assert _ignored(tmp_path, "agents/fireflies_insights/secret_runtime.json")
    assert _ignored(tmp_path, "agents/porygon/skills/x.md")


def _env() -> jinja2.Environment:
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)), undefined=jinja2.StrictUndefined)


def test_template_renders_with_full_contract() -> None:
    text = _env().get_template("fireflies/action_item.j2").render(**PARAMS)
    assert "Ship the importer" in text and "{quote}Ana: I will ship it{quote}" in text
    assert "*Owner:*" not in text and "Wiki page" not in text


def test_template_fails_when_a_contract_key_is_missing() -> None:
    params = dict(PARAMS)
    params.pop("wiki_url")
    with pytest.raises(jinja2.UndefinedError):
        _env().get_template("fireflies/action_item.j2").render(**params)
