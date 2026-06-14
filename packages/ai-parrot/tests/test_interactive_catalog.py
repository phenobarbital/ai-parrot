"""Unit tests for the interactive HTML artifact catalog (libraries + scaffolds)."""
from __future__ import annotations

import textwrap

import pytest

from parrot.tools.interactive.catalog_registry import (
    HEAD_MARKER,
    PLACEHOLDER_SRI_PREFIX,
    InteractiveCatalogRegistry,
    build_head,
    get_interactive_catalog,
)
from parrot.models.interactive import LibraryEntry, ScaffoldTemplate


# ---------------------------------------------------------------------------
# Bundled catalog
# ---------------------------------------------------------------------------

def test_bundled_catalog_loads_expected_entries():
    cat = get_interactive_catalog()
    template_names = {t.name for t in cat.list_templates()}
    library_names = {lib.name for lib in cat.list_libraries()}
    assert {"dashboard", "wizard", "diagram", "grid", "report"} <= template_names
    assert {"echarts", "mermaid", "gridjs", "stepper"} <= library_names


def test_template_slots_auto_derived_from_skeleton():
    cat = get_interactive_catalog()
    wizard = cat.get_template("wizard")
    assert "steps" in wizard.slots
    assert "title" in wizard.slots
    # Every skeleton must carry the head injection marker.
    assert HEAD_MARKER in wizard.html_skeleton


def test_inline_library_has_inline_source_and_no_url():
    cat = get_interactive_catalog()
    stepper = cat.get_library("stepper")
    assert stepper.bundle.scope == "inline"
    assert stepper.bundle.url is None
    assert "Stepper" in (stepper.bundle.inline or "")


def test_cdn_library_with_css_companion():
    cat = get_interactive_catalog()
    gridjs = cat.get_library("gridjs")
    assert gridjs.bundle.scope == "cdn"
    assert gridjs.css_bundle is not None
    assert gridjs.css_bundle.url.endswith(".css")
    # bundles() returns both script and stylesheet.
    assert len(gridjs.bundles()) == 2


def test_echarts_has_verified_sri():
    cat = get_interactive_catalog()
    echarts = cat.get_library("echarts")
    assert not echarts.bundle.sri_hash.startswith(PLACEHOLDER_SRI_PREFIX)


def test_unknown_lookups_raise_keyerror():
    cat = get_interactive_catalog()
    with pytest.raises(KeyError):
        cat.get_library("does-not-exist")
    with pytest.raises(KeyError):
        cat.get_template("does-not-exist")


def test_prompt_index_lists_templates_and_libraries():
    cat = get_interactive_catalog()
    index = cat.render_prompt_index()
    assert "<interactive_catalog>" in index
    assert '<template name="dashboard"' in index
    assert '<library name="echarts"' in index


# ---------------------------------------------------------------------------
# build_head
# ---------------------------------------------------------------------------

def test_build_head_emits_script_with_integrity_and_theme():
    cat = get_interactive_catalog()
    echarts = cat.get_library("echarts")
    head = build_head(echarts.bundles(), theme="dark")
    assert "echarts.min.js" in head
    assert f'integrity="{echarts.bundle.sri_hash}"' in head
    assert 'crossorigin="anonymous"' in head
    assert "#0f172a" in head  # dark theme override applied


def test_build_head_stylesheet_uses_link_tag():
    cat = get_interactive_catalog()
    gridjs = cat.get_library("gridjs")
    head = build_head(gridjs.bundles())
    assert '<link rel="stylesheet"' in head
    assert "<script" in head


def test_build_head_inline_bundle_inlined_without_src():
    cat = get_interactive_catalog()
    stepper = cat.get_library("stepper")
    head = build_head(stepper.bundles())
    assert "<script>" in head
    assert "src=" not in head.split("</style>")[-1]  # no external src for inline


# ---------------------------------------------------------------------------
# Custom catalog dir (malformed-entry resilience)
# ---------------------------------------------------------------------------

def _write_library(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def test_malformed_library_is_skipped_not_fatal(tmp_path):
    libs = tmp_path / "libraries"
    tmpls = tmp_path / "templates"
    tmpls.mkdir(parents=True)
    # one good inline library
    _write_library(
        libs / "good.md",
        """
        ---
        name: good
        description: good lib
        category: util
        scope: inline
        ---

        ## Inline
        ```js
        window.good = 1;
        ```
        """,
    )
    # one malformed library (cdn without url/sri)
    _write_library(
        libs / "bad.md",
        """
        ---
        name: bad
        description: bad lib
        category: util
        scope: cdn
        ---
        """,
    )
    reg = InteractiveCatalogRegistry(catalog_dir=tmp_path).load()
    names = {lib.name for lib in reg.list_libraries()}
    assert "good" in names
    assert "bad" not in names  # malformed entry skipped, load did not abort
