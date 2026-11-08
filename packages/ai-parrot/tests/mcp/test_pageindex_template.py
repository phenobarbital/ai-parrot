"""Packaged `pageindex` toolkit template and example (FEAT-842 M4/M5)."""

from __future__ import annotations

from pathlib import Path

import yaml

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections

_EXAMPLE_PATH = Path(__file__).resolve().parents[4] / "examples" / "pageindex-mcp.yaml"
_CLASS = "parrot.knowledge.pageindex.toolkit.PageIndexToolkit"


def test_template_metadata() -> None:
    """AC-7: requires_llm False, requires_dist (bm25s, pymupdf), requires_pip (ai-parrot[bookstore],)."""
    assert "pageindex" in available_templates()
    tpl = load_template("pageindex")
    assert tpl.requires_llm is False
    assert tpl.requires_dist == ("bm25s", "pymupdf")
    assert tpl.requires_pip == ("ai-parrot[bookstore]",)
    assert "{{repo_root}}" in tpl.body
    assert f"class: {_CLASS}" in tpl.body


def test_template_seeds_repo_scoped_storage(tmp_path: Path) -> None:
    """AC-7: seeding renders storage_dir under <root>/.parrot/pageindex with max_result_chars 24000."""
    result = seed_toolkit_sections(tmp_path, ["pageindex"])
    assert result.added == ["pageindex"]
    section = load_toolkits_config(tmp_path).toolkits["pageindex"]
    assert section.class_path == _CLASS
    assert section.llm is None
    assert not section.exclude
    assert section.kwargs["storage_dir"] == f"{tmp_path}/.parrot/pageindex"
    assert section.kwargs["max_result_chars"] == 24000
    written = (tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text(encoding="utf-8")
    assert "{{repo_root}}" not in written


def test_example_mirrors_template_with_llm() -> None:
    """The example is a standalone config with the same class and an active llm line."""
    assert _EXAMPLE_PATH.is_file()
    raw = yaml.safe_load(_EXAMPLE_PATH.read_text(encoding="utf-8"))["toolkits"]["pageindex"]
    assert raw["class"] == _CLASS
    assert raw["llm"]
    assert raw["kwargs"]["max_result_chars"] == 24000
    section = load_toolkits_config(_EXAMPLE_PATH.parent, config_path=_EXAMPLE_PATH).toolkits["pageindex"]
    assert section.llm
    assert section.class_path == _CLASS
