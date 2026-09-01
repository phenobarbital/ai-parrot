"""Unit tests for MCP toolkit configuration loader.

FEAT-485: Tests for toolkit_config.py — config models, built-in defaults,
and YAML loading + merging.
"""

import pytest
from parrot.mcp.toolkit_config import (
    MCPToolkitsConfig,
    ToolkitSection,
    load_toolkits_config,
)


def test_no_file_returns_builtins(tmp_path):
    """load_toolkits_config with no file returns exactly the 3 builtins."""
    cfg = load_toolkits_config(tmp_path)
    assert set(cfg.toolkits.keys()) == {"scraping", "browsing", "memory"}
    assert cfg.toolkits["memory"].class_path == "parrot.tools.working_memory.tool.WorkingMemoryToolkit"


def test_file_overrides_builtin(tmp_path):
    """File section with a built-in name replaces it entirely (kwargs not merged)."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n"
        "  memory:\n"
        "    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit\n"
        "    kwargs:\n"
        "      max_rows: 25\n"
    )
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits["memory"].kwargs == {"max_rows": 25}
    assert cfg.toolkits["scraping"].class_path == "parrot_tools.scraping.toolkit.WebScrapingToolkit"


def test_new_section_added(tmp_path):
    """New sections in file are appended alongside builtins."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n" "  custom:\n" "    class: my.custom.Toolkit\n" "    kwargs:\n" "      param: value\n"
    )
    cfg = load_toolkits_config(tmp_path)
    assert "scraping" in cfg.toolkits  # builtins still present
    assert "custom" in cfg.toolkits
    assert cfg.toolkits["custom"].class_path == "my.custom.Toolkit"


def test_bad_yaml_named_error(tmp_path):
    """Malformed YAML raises error naming the file path."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text("toolkits: [invalid yaml structure {")
    with pytest.raises(ValueError, match=str(config_file)):
        load_toolkits_config(tmp_path)


def test_enabled_false_retained(tmp_path):
    """Disabled sections (enabled: false) are retained in the config."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n"
        "  memory:\n"
        "    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit\n"
        "    enabled: false\n"
    )
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits["memory"].enabled is False


def test_unknown_top_level_key_raises(tmp_path):
    """Unknown top-level keys raise ValueError naming them."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text("toolkits: {}\n" "bad_key: value\n")
    with pytest.raises(ValueError, match="Unknown top-level keys"):
        load_toolkits_config(tmp_path)


def test_non_mapping_toolkits_raises(tmp_path):
    """Non-mapping 'toolkits:' value raises ValueError."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text("toolkits: [item1, item2]\n")
    with pytest.raises(ValueError, match="to be a mapping"):
        load_toolkits_config(tmp_path)


def test_builtin_defaults_match(tmp_path):
    """Built-in defaults are correctly initialized."""
    cfg = load_toolkits_config(tmp_path)

    # Scraping
    scraping = cfg.toolkits["scraping"]
    assert scraping.class_path == "parrot_tools.scraping.toolkit.WebScrapingToolkit"
    assert scraping.kwargs["headless"] is True
    assert ".parrot/scraping_plans" in scraping.kwargs["plans_dir"]
    assert scraping.enabled is True

    # Browsing
    browsing = cfg.toolkits["browsing"]
    assert browsing.class_path == "parrot_tools.browsing.toolkit.WebBrowsingToolkit"
    assert browsing.kwargs["headless"] is True
    assert ".parrot/browsing_catalog" in browsing.kwargs["catalog_dir"]
    assert browsing.enabled is True

    # Memory
    memory = cfg.toolkits["memory"]
    assert memory.class_path == "parrot.tools.working_memory.tool.WorkingMemoryToolkit"
    assert memory.kwargs == {}
    assert memory.enabled is True


def test_class_alias_yaml(tmp_path):
    """'class' alias in YAML is correctly parsed."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text("toolkits:\n" "  test:\n" "    class: test.Module\n")
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits["test"].class_path == "test.Module"


def test_toolkit_section_defaults(tmp_path):
    """ToolkitSection has correct defaults."""
    section = ToolkitSection(class_path="test.Toolkit")
    assert section.enabled is True
    assert section.kwargs == {}
    assert section.include is None
    assert section.exclude is None
    assert section.llm is None
    assert section.env == {}


def test_mcp_config_defaults(tmp_path):
    """MCPToolkitsConfig defaults to empty toolkits dict."""
    cfg = MCPToolkitsConfig()
    assert cfg.toolkits == {}


def test_explicit_config_path_override(tmp_path):
    """FEAT-485 fix: an explicit config_path is read INSTEAD of
    <root>/.parrot/mcp-toolkits.yaml (previously a documented no-op)."""
    elsewhere = tmp_path / "custom-toolkits.yaml"
    elsewhere.write_text("toolkits:\n" "  custom:\n" "    class: test.CustomToolkit\n")
    # A decoy default-path file proves the override actually wins.
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "mcp-toolkits.yaml").write_text("toolkits:\n" "  decoy:\n" "    class: test.Decoy\n")

    cfg = load_toolkits_config(tmp_path, config_path=elsewhere)

    assert "custom" in cfg.toolkits
    assert "decoy" not in cfg.toolkits


def test_explicit_config_path_missing_raises(tmp_path):
    """An explicitly named file that is absent is operator error — unlike
    the default path, whose absence silently falls back to built-ins."""
    with pytest.raises(ValueError, match="not found"):
        load_toolkits_config(tmp_path, config_path=tmp_path / "nope.yaml")
