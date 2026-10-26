"""Install-metadata template headers (FEAT-633, TASK-4077)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.mcp import toolkit_seed
from parrot.mcp.toolkit_seed import ToolkitTemplate, available_templates, load_template


@pytest.fixture
def fake_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `load_template` at a tmp `_toolkit_templates/` dir (it reads `files(pkg) / TEMPLATE_DIR`)."""
    template_dir = tmp_path / toolkit_seed.TEMPLATE_DIR
    template_dir.mkdir()
    monkeypatch.setattr(toolkit_seed, "files", lambda _pkg: tmp_path)
    return template_dir


def _write(template_dir: Path, name: str, header: str) -> None:
    (template_dir / f"{name}.yaml").write_text(f"{header}\n  {name}:\n    class: x.Y\n", encoding="utf-8")


def test_template_new_headers_parse(fake_templates: Path) -> None:
    """requires_pip (repeatable, commas kept) / post_install (shlex) / requires_env (csv) round-trip."""
    _write(
        fake_templates,
        "demo",
        "# parrot:requires_pip: pkg[a,b]>=1.0\n"
        "# parrot:requires_pip: other; python_version >= '3.11'\n"
        "# parrot:post_install: python -m tool install 'two words'\n"
        "# parrot:requires_env: A, B,,",
    )
    tpl = load_template("demo")
    assert tpl.requires_pip == ("pkg[a,b]>=1.0", "other; python_version >= '3.11'")
    assert tpl.post_install == ("python", "-m", "tool", "install", "two words")
    assert tpl.requires_env == ("A", "B")


def test_template_unknown_keys_ignored(fake_templates: Path) -> None:
    """Forward-compat: an unknown `# parrot:` key is skipped, the rest still parses."""
    _write(
        fake_templates,
        "demo",
        "# parrot:summary: s\n# parrot:future_key: x\n# parrot:requires_pip: pkg\n# parrot:requires_env: A",
    )
    tpl = load_template("demo")
    assert tpl.summary == "s"
    assert tpl.requires_pip == ("pkg",)
    assert tpl.requires_env == ("A",)
    assert tpl.body.lstrip().startswith("demo:")


def test_malformed_post_install_is_ignored(fake_templates: Path) -> None:
    """Unbalanced quotes never make the parser fatal."""
    _write(fake_templates, "demo", "# parrot:post_install: python -c 'oops")
    assert load_template("demo").post_install == ()


def test_old_templates_default_empty() -> None:
    """Templates without the new keys keep `()` defaults (memory ships none)."""
    tpl = load_template("memory")
    assert (tpl.requires_pip, tpl.post_install, tpl.requires_env) == ((), (), ())


@pytest.mark.parametrize("name", ["browsing", "scraping"])
def test_browser_templates_ship_playwright_install(name: str) -> None:
    tpl = load_template(name)
    assert tpl.requires_pip == ("ai-parrot-tools[scraping]",)
    assert tpl.post_install == ("python", "-m", "playwright", "install", "chromium")


def test_lsp_and_querysource_metadata() -> None:
    lsp = load_template("lsp")
    assert lsp.requires_pip == ("ai-parrot-tools",)
    assert lsp.post_install == ()
    qs = load_template("querysource")
    assert qs.requires_pip == ("ai-parrot-tools[db]",)
    assert qs.requires_env == ("PG_USER", "PG_PWD")
    assert qs.requires_dist == ("parrot_tools", "querysource")


@pytest.mark.parametrize("name", ["bounded-source", "targeted-writer"])
def test_tool_optimization_templates_declare_ai_parrot_tools(name: str) -> None:
    """Spec rev 0.5 C24 — both declare requires_dist parrot_tools + requires_pip ai-parrot-tools."""
    tpl = load_template(name)
    assert tpl.requires_dist == ("parrot_tools",)
    assert tpl.requires_pip == ("ai-parrot-tools",)
    assert tpl.post_install == ()


def test_every_shipped_template_still_loads() -> None:
    for name in available_templates():
        assert isinstance(load_template(name), ToolkitTemplate)


@pytest.mark.parametrize("name", ["../_toolkit_templates/lsp", "sub/../lsp", "..", "/etc/passwd", "a/b", "lsp/../lsp", "", "nope"])
def test_load_template_rejects_non_catalogue_names(name: str) -> None:
    """Only bare packaged-catalogue names resolve; traversal / absolute / unknown raise KeyError."""
    from parrot.mcp.toolkit_seed import load_template

    with pytest.raises(KeyError):
        load_template(name)
