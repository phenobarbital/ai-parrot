import pytest
import yaml
from importlib.resources import files

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import (
    SeedResult,
    available_templates,
    load_template,
    preflight_seed,
    remove_section,
    seed_toolkit_sections,
    set_section_enabled,
)

# A hand-edited config with operator comments and inline trailing comments —
# the worst case for AC10 (comments/formatting must survive a toggle/remove).
COMMENTED = """toolkits:
  # operator note that must survive
  memory:
    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit
    enabled: true
    kwargs: {}  # trailing comment
  bounded-source:
    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit
"""


def test_available_templates_lists_packaged_names():
    assert set(available_templates()) == {
        "sdd-coder",
        "bounded-source",
        "targeted-writer",
        "querysource",
        "database-query",
        "scraping",
        "browsing",
        "memory",
    }


def test_templates_resolve_from_package_not_repo():
    """load_template must read package data, not a repo-relative path."""
    # Verify that templates can be loaded via importlib.resources
    template_dir = files("parrot.mcp") / "_toolkit_templates"
    assert template_dir.is_dir()

    # Verify that each template exists in the package
    for template_name in available_templates():
        template_path = template_dir / f"{template_name}.yaml"
        assert template_path.is_file(), f"Template {template_name} not found in package"

        # Verify we can load it
        template = load_template(template_name)
        assert template.name == template_name
        assert len(template.body) > 0


def test_seed_creates_yaml_when_absent(tmp_path):
    result = seed_toolkit_sections(tmp_path, ["bounded-source"])
    assert result.created_file is True
    data = yaml.safe_load((tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text())
    assert "bounded-source" in data["toolkits"]


def test_seed_appends_without_touching_existing_sections(tmp_path):
    # Pre-write a file with an operator section
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "toolkits:\n" "  operator-section:\n" "    class: some.custom.Toolkit\n" "    enabled: true\n"
    )

    # Seed another name
    result = seed_toolkit_sections(tmp_path, ["bounded-source"])

    # Assert the operator section's text is unchanged and listed in .skipped
    content = config_path.read_text()
    assert "operator-section:" in content
    assert "some.custom.Toolkit" in content

    # The operator section should be in skipped since we didn't try to add it
    # But the new section should be added
    assert "bounded-source" in result.added
    assert result.created_file is False  # File existed already


def test_seed_renders_repo_root_placeholder(tmp_path):
    seed_toolkit_sections(tmp_path, ["bounded-source"])
    text = (tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text()
    assert "{{repo_root}}" not in text and str(tmp_path) in text


def test_requires_llm_section_seeded_disabled(tmp_path):
    seed_toolkit_sections(tmp_path, ["targeted-writer"])
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits["targeted-writer"].enabled is False


def test_seed_unknown_name_raises_before_writing_new_sections(tmp_path):
    # S4/AC8: all-or-nothing now — the pre-FEAT-570 behavior of seeding the
    # valid names anyway (reporting "nope" in `.unknown`) is gone.
    with pytest.raises(ValueError, match="No packaged template"):
        seed_toolkit_sections(tmp_path, ["bounded-source", "nope"])
    assert not (tmp_path / ".parrot" / "mcp-toolkits.yaml").exists()


def test_load_template_parses_metadata():
    template = load_template("bounded-source")
    assert template.name == "bounded-source"
    assert "Bounded source reading" in template.summary
    assert template.requires_llm is False

    template = load_template("targeted-writer")
    assert template.name == "targeted-writer"
    assert "Patch generation" in template.summary
    assert template.requires_llm is True


def test_seed_skips_existing_sections(tmp_path):
    # Create initial config with a section
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "toolkits:\n"
        "  bounded-source:\n"
        "    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n"
        "    kwargs:\n"
        "      repo_root: /some/path\n"
    )

    # Try to seed the same section again
    result = seed_toolkit_sections(tmp_path, ["bounded-source"])

    # Should be skipped
    assert result.skipped == ["bounded-source"]
    assert result.added == []


def test_seed_roundtrip_validation(tmp_path):
    result = seed_toolkit_sections(tmp_path, ["sdd-coder"])
    assert result.added == ["sdd-coder"]

    # Should be able to load the config successfully
    cfg = load_toolkits_config(tmp_path)
    assert "sdd-coder" in cfg.toolkits
    assert cfg.toolkits["sdd-coder"].class_path == "parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit"


# --- TASK-3369: preflight, atomicity, comment-preserving toggle/remove ---


def test_preflight_rejects_unknown_name_before_write(tmp_path):
    with pytest.raises(ValueError, match="No packaged template"):
        preflight_seed(tmp_path, ["definitely-not-a-template"])


def test_preflight_rejects_malformed_yaml(tmp_path):
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    # Missing the required `class` key — fails ToolkitSection validation.
    config_path.write_text("toolkits:\n  bad-section:\n    not_class: true\n")
    before = config_path.read_bytes()

    with pytest.raises(ValueError, match="bad-section"):
        preflight_seed(tmp_path, ["bounded-source"])

    # preflight must not touch the file even though "bounded-source" is valid.
    assert config_path.read_bytes() == before


def test_seed_unknown_name_leaves_file_byte_identical(tmp_path):
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(COMMENTED)
    before = config_path.read_bytes()

    with pytest.raises(ValueError, match="No packaged template"):
        seed_toolkit_sections(tmp_path, ["sdd-coder", "nope"])

    assert config_path.read_bytes() == before


def test_set_section_enabled_preserves_comments(tmp_path):
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(COMMENTED)

    changed = set_section_enabled(tmp_path, "memory", False)

    assert changed is True
    text = config_path.read_text()
    assert "# operator note that must survive" in text
    assert "kwargs: {}  # trailing comment" in text
    assert "    enabled: false" in text
    # The neighbouring section is untouched.
    assert "  bounded-source:\n" in text
    assert "    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n" in text


def test_remove_section_preserves_neighbours(tmp_path):
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(COMMENTED)

    changed = remove_section(tmp_path, "memory")

    assert changed is True
    text = config_path.read_text()
    assert "memory:" not in text
    assert "operator note that must survive" not in text
    # The neighbouring section and the root key survive intact.
    assert text.startswith("toolkits:\n")
    assert "  bounded-source:\n" in text
    assert "    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n" in text


def test_set_enabled_returns_false_for_absent_section(tmp_path):
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(COMMENTED)
    before = config_path.read_bytes()

    assert set_section_enabled(tmp_path, "does-not-exist", True) is False
    assert remove_section(tmp_path, "does-not-exist") is False
    # Neither helper wrote anything for an absent section.
    assert config_path.read_bytes() == before
