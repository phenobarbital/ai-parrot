"""Unit tests for MCP toolkit configuration loader.

FEAT-485: Tests for toolkit_config.py — config models, built-in defaults,
and YAML loading + merging.
"""

from pathlib import Path

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


# --------------------------------------------------------------------------- #
# FEAT-543: llm_kwargs
# --------------------------------------------------------------------------- #
def test_llm_kwargs_defaults_to_empty():
    """Existing sections are unchanged: the new field defaults to empty."""
    section = ToolkitSection.model_validate({"class": "x.Y"})
    assert section.llm_kwargs == {}
    assert section.llm is None


def test_llm_kwargs_parses_with_llm():
    """A section may carry trusted client construction kwargs."""
    section = ToolkitSection.model_validate(
        {
            "class": "x.Y",
            "llm": "bedrock-converse:qwen3-coder-480b-a35b",
            "llm_kwargs": {"fallback_model": None, "max_retries": 1, "read_timeout": 120},
        }
    )
    assert section.llm_kwargs["fallback_model"] is None
    assert section.llm_kwargs["max_retries"] == 1


def test_llm_kwargs_requires_llm(tmp_path):
    """llm_kwargs without llm is a configuration error naming the section."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  w:\n    class: x.Y\n    llm_kwargs: {fallback_model: null}\n"
    )
    with pytest.raises(ValueError, match="'w'"):
        load_toolkits_config(tmp_path)


def test_llm_kwargs_rejects_llm_key():
    """An `llm` key inside llm_kwargs would collide with the factory argument."""
    with pytest.raises(ValueError, match="must not contain"):
        ToolkitSection.model_validate({"class": "x.Y", "llm": "openai:gpt", "llm_kwargs": {"llm": "z"}})


def test_example_tool_optimizations_config_loads():
    """The shipped FEAT-543 example is valid and pins the no-fallback setting."""
    example = Path(__file__).resolve().parents[2] / "examples" / "tool-optimizations-mcp.yaml"
    assert example.is_file(), f"missing example config at {example}"

    config = load_toolkits_config(example.parent, config_path=example)
    assert set(config.toolkits) >= {"local-git", "bounded-source", "targeted-writer"}

    writer = config.toolkits["targeted-writer"]
    assert writer.class_path == "parrot_tools.tool_optimizations.writer.TargetedWriterToolkit"
    assert writer.llm == "bedrock-converse:qwen3-coder-480b-a35b"
    # Explicit null, not merely absent — an absent key would let the Bedrock
    # client apply its own fallback default.
    assert "fallback_model" in writer.llm_kwargs
    assert writer.llm_kwargs["fallback_model"] is None
    assert writer.kwargs["expected_model_ids"] == ["qwen.qwen3-coder-480b-a35b-v1:0"]

    # The deterministic toolkits configure no model at all.
    for name in ("local-git", "bounded-source"):
        assert config.toolkits[name].llm is None
        assert config.toolkits[name].llm_kwargs == {}
