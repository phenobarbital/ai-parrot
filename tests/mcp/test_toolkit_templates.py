"""Every packaged toolkit template is well-formed (FEAT-570, TASK-3370)."""

from __future__ import annotations

import importlib

import pytest
import yaml

from parrot.mcp.toolkit_seed import available_templates, load_template  # verified: toolkit_seed.py:47,61

EXPECTED = {
    "bounded-source",
    "targeted-writer",
    "sdd-coder",
    "querysource",
    "database-query",
    "scraping",
    "browsing",
    "memory",
}


def test_all_expected_templates_ship():
    assert EXPECTED <= set(available_templates())


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_template_parses_and_declares_class(name):
    """Body splices under `toolkits:` and names an importable dotted path."""
    tpl = load_template(name)
    parsed = yaml.safe_load("toolkits:\n" + tpl.body.replace("{{repo_root}}", "/tmp/x"))
    section = parsed["toolkits"][name]
    assert section["class"].count(".") >= 2
    # The module half of `class` is importable ONLY when tpl.requires_dist is
    # empty — a template for an optional distribution must not fail this
    # suite on a bare install; bounded by AC3.
    if not tpl.requires_dist:
        module_path = section["class"].rsplit(".", 1)[0]
        importlib.import_module(module_path)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_template_ships_no_secret(name):
    """AC6: no template carries a populated env: block."""
    tpl = load_template(name)
    parsed = yaml.safe_load("toolkits:\n" + tpl.body.replace("{{repo_root}}", "/tmp/x"))
    assert parsed["toolkits"][name].get("env", {}) == {}


def test_querysource_requires_dist_parses_as_tuple():
    """A multi-value `requires_dist:` header parses into an ordered tuple."""
    tpl = load_template("querysource")
    assert tpl.requires_dist == ("parrot_tools", "querysource")


def test_memory_requires_dist_defaults_to_empty_tuple():
    """An empty `requires_dist:` header (core-only toolkit) yields `()`."""
    tpl = load_template("memory")
    assert tpl.requires_dist == ()


def test_database_query_template_has_no_forbidden_kwargs():
    """DatabaseQueryToolkit accepts only output_dir/static_dir — no write/dsn knobs."""
    tpl = load_template("database-query")
    parsed = yaml.safe_load("toolkits:\n" + tpl.body.replace("{{repo_root}}", "/tmp/x"))
    kwargs = parsed["toolkits"]["database-query"].get("kwargs", {})
    for forbidden in ("allow_write", "allow_raw_sql", "dsn", "credentials"):
        assert forbidden not in kwargs
