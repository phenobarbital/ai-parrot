"""Unit tests for managed Google Antigravity mcp_config.json toolkit entries."""

import json
from pathlib import Path

import pytest
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.installer import (
    _install_mcp,
    uninstall_google_integration,
)


@pytest.fixture
def mcp_config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "global_mcp/mcp_config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture
def tmp_root_with_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mcp_config_path: Path) -> Path:
    """Project root with the 3 builtins disabled + one custom enabled toolkit."""
    monkeypatch.setattr(assets, "default_mcp_config_path", lambda: mcp_config_path)
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir(parents=True, exist_ok=True)
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  scraping:\n"
        "    class: parrot_tools.scraping.toolkit.WebScrapingToolkit\n"
        "    enabled: false\n"
        "  browsing:\n"
        "    class: parrot_tools.browsing.toolkit.WebBrowsingToolkit\n"
        "    enabled: false\n"
        "  memory:\n"
        "    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit\n"
        "    enabled: false\n"
        "  stub:\n"
        "    class: tests.mcp.stub_toolkit.StubToolkit\n"
        "    env:\n"
        "      FOO: bar\n",
        encoding="utf-8",
    )
    return tmp_path


def _config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_install_writes_toolkit_entries(tmp_root_with_config: Path, mcp_config_path: Path):
    root = tmp_root_with_config
    _install_mcp(root, mcp_path=mcp_config_path)

    doc = _config(mcp_config_path)
    servers = doc["mcpServers"]
    assert "wikitoolkit" in servers
    stub = servers["parrot-stub"]
    assert stub["command"] == assets.resolve_binary(root, "parrot")
    assert stub["args"] == ["mcp-local", "stub"]
    assert stub["env"] == {"FOO": "bar"}
    assert "parrot-scraping" not in servers
    assert "parrot-browsing" not in servers
    assert "parrot-memory" not in servers


def test_install_is_idempotent(tmp_root_with_config: Path, mcp_config_path: Path):
    root = tmp_root_with_config
    _install_mcp(root, mcp_path=mcp_config_path)
    before = mcp_config_path.read_bytes()

    _install_mcp(root, mcp_path=mcp_config_path)
    assert mcp_config_path.read_bytes() == before


def test_disabled_section_table_removed_on_rerun(tmp_root_with_config: Path, mcp_config_path: Path):
    root = tmp_root_with_config
    _install_mcp(root, mcp_path=mcp_config_path)
    assert "parrot-stub" in _config(mcp_config_path)["mcpServers"]

    cfg_path = root / ".parrot" / "mcp-toolkits.yaml"
    text = cfg_path.read_text(encoding="utf-8").replace(
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    env:\n      FOO: bar\n",
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: false\n    env:\n      FOO: bar\n",
    )
    cfg_path.write_text(text, encoding="utf-8")

    _install_mcp(root, mcp_path=mcp_config_path)
    assert "parrot-stub" not in _config(mcp_config_path)["mcpServers"]


def test_foreign_colliding_toolkit_preserved(tmp_root_with_config: Path, mcp_config_path: Path, capsys):
    root = tmp_root_with_config
    mcp_config_path.write_text(
        json.dumps({
            "mcpServers": {
                "parrot-stub": {
                    "command": "foreign_parrot",
                    "args": ["foreign_arg"],
                }
            }
        }),
        encoding="utf-8",
    )

    _install_mcp(root, mcp_path=mcp_config_path)
    servers = _config(mcp_config_path)["mcpServers"]
    assert servers["parrot-stub"]["command"] == "foreign_parrot"
    stderr = capsys.readouterr().err
    assert "already exists and was not written by `parrot google install`" in stderr
