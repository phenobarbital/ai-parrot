"""FEAT-877 Module 4 — seeding and installing agent sections."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, load_toolkits_config
from parrot.mcp.toolkit_seed import seed_agent_sections, seed_toolkit_sections


def _config(root: Path) -> Path:
    return root / ".parrot" / "mcp-toolkits.yaml"


def test_seed_agent_section_written(tmp_path: Path) -> None:
    result = seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    assert result.created_file and result.added == ["agent-finance"]
    section = load_toolkits_config(tmp_path).toolkits["agent-finance"]
    assert section.class_path == AGENT_TOOLKIT_CLASS_PATH
    assert section.kwargs == {"agent": "finance"}

    original = _config(tmp_path).read_bytes()
    repeated = seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    assert repeated.skipped == ["agent-finance"]
    assert _config(tmp_path).read_bytes() == original

    seed_toolkit_sections(tmp_path, ["memory"])
    with_template = _config(tmp_path).read_text(encoding="utf-8")
    _config(tmp_path).write_text(f"{with_template}# operator comment\n", encoding="utf-8")
    seed_agent_sections(tmp_path, {"agent-research": "research"})
    updated = _config(tmp_path).read_text(encoding="utf-8")
    assert "# operator comment" in updated
    config = load_toolkits_config(tmp_path)
    assert "memory" in config.toolkits
    assert config.toolkits["agent-research"].kwargs == {"agent": "research"}


def test_seed_agent_section_conflict(tmp_path: Path) -> None:
    seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    original = _config(tmp_path).read_bytes()
    with pytest.raises(ValueError, match="agent-finance"):
        seed_agent_sections(tmp_path, {"agent-finance": "other"})
    assert _config(tmp_path).read_bytes() == original

    other_root = tmp_path / "other"
    path = _config(other_root)
    path.parent.mkdir(parents=True)
    path.write_text(
        "toolkits:\n" "  agent-x:\n" "    class: parrot.mcp.other.OtherToolkit\n" "    kwargs:\n" "      agent: x\n",
        encoding="utf-8",
    )
    other_original = path.read_bytes()
    with pytest.raises(ValueError, match="agent-x"):
        seed_agent_sections(other_root, {"agent-x": "x"})
    assert path.read_bytes() == other_original


def test_seed_agent_section_malformed_file(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("toolkits: [invalid", encoding="utf-8")
    original = path.read_bytes()

    with pytest.raises(ValueError):
        seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    assert path.read_bytes() == original
