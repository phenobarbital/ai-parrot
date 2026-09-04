"""Unit tests for parrot_variant/parrot_role semantic classes + (theme, layout)
resolution precedence (FEAT-493, TASK-2710)."""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.models import (
    Component,
    ComponentMetadata,
    CreateSurface,
)
from parrot.outputs.a2ui_renderers.interactive_html import (
    InteractiveHTMLRenderer,
)
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer
from parrot.outputs.formats.assets.design_system import DesignSystem

RENDERERS = [InteractiveHTMLRenderer, SSRHTMLRenderer]


def _kpi_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="kpi",
        catalogId="c",
        components=[
            Component(
                id="root",
                component="KPICard",
                label="Revenue",
                value="1234",
                unit="USD",
                delta="+4.2%",
                trend="up",
            )
        ],
        dataModel={},
    )


@pytest.mark.parametrize("renderer_cls", RENDERERS)
class TestSemanticClasses:
    pytestmark = pytest.mark.asyncio

    async def test_kpicard_variant_honoured(self, renderer_cls):
        doc = (await renderer_cls().render(_kpi_envelope())).content.decode()
        assert "kpi-card" in doc
        assert "kpi-label" in doc
        assert "kpi-value" in doc
        assert 'data-trend="up"' in doc
        assert "kpi-unit" in doc

    async def test_legacy_classes_preserved(self, renderer_cls):
        doc = (await renderer_cls().render(_kpi_envelope())).content.decode()
        assert "a2ui-card" in doc  # never replaced, only appended to
        assert "a2ui-value" in doc


@pytest.mark.parametrize("renderer_cls", RENDERERS)
class TestKpiGrid:
    pytestmark = pytest.mark.asyncio

    async def test_kpi_row_becomes_grid(self, renderer_cls):
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[
                Component(id="root", component="Row", children=["k1", "k2"]),
                Component(id="k1", component="KPICard", label="A", value=1),
                Component(id="k2", component="KPICard", label="B", value=2),
            ],
            dataModel={},
        )
        doc = (await renderer_cls().render(env)).content.decode()
        # Checked against the wrapping element's class, not a bare substring
        # search — the composed stylesheet legitimately defines a `.kpi-grid`
        # CSS rule, which would make a naive "kpi-grid" in doc check vacuous.
        assert 'class="a2ui-row kpi-grid"' in doc

    async def test_mixed_row_is_not_a_grid(self, renderer_cls):
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[
                Component(id="root", component="Row", children=["k1", "c2"]),
                Component(id="k1", component="KPICard", label="A", value=1),
                Component(id="c2", component="Card", child="t2"),
                Component(id="t2", component="Text", text="hi"),
            ],
            dataModel={},
        )
        doc = (await renderer_cls().render(env)).content.decode()
        assert 'class="a2ui-row kpi-grid"' not in doc


class TestResolutionPrecedence:
    def _envelope(self, *, metadata=None, infographic_theme=None) -> CreateSurface:
        if infographic_theme is not None:
            components = [
                Component(id="root", component="Infographic", title="t", theme=infographic_theme, sections=[])
            ]
        else:
            components = [Component(id="root", component="Text", text="hi")]
        return CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=components,
            dataModel={},
            metadata=metadata,
        )

    def test_envelope_extensions_win(self):
        env = self._envelope(
            metadata=ComponentMetadata(extensions={"parrot_theme": "dark", "parrot_layout": "print"}),
            infographic_theme="corporate",
        )
        theme, layout = DesignSystem.resolve(env, theme_default="midnight", layout_default="report")
        assert (theme, layout) == ("dark", "print")

    def test_infographic_theme_prop_is_second(self):
        env = self._envelope(infographic_theme="corporate")
        theme, layout = DesignSystem.resolve(env, theme_default="midnight", layout_default="report")
        assert theme == "corporate"
        assert layout == "report"  # no envelope/infographic layout hint -> constructor kwarg

    def test_constructor_is_third(self):
        env = self._envelope()
        theme, layout = DesignSystem.resolve(env, theme_default="midnight", layout_default="report")
        assert (theme, layout) == ("midnight", "report")

    def test_class_default_is_last(self):
        env = self._envelope()
        theme, layout = DesignSystem.resolve(env)
        assert (theme, layout) == (DesignSystem.DEFAULT_THEME, DesignSystem.DEFAULT_LAYOUT)

    def test_unknown_value_warns_and_falls_back(self, caplog):
        env = self._envelope(
            metadata=ComponentMetadata(extensions={"parrot_theme": "not-a-theme", "parrot_layout": "not-a-layout"})
        )
        with caplog.at_level(logging.WARNING):
            theme, layout = DesignSystem.resolve(env, theme_default="midnight", layout_default="report")
        assert (theme, layout) == ("midnight", "report")
        assert any("design-system theme" in rec.message for rec in caplog.records)
        assert any("design-system layout" in rec.message for rec in caplog.records)


#: Repo/worktree root, anchored to THIS file — some third-party import in
#: this test suite's dependency chain (navconfig's settings bootstrap) does
#: an `os.chdir()` as a side effect, which persists for the rest of the
#: pytest PROCESS. A bare relative `git diff` call would then silently run
#: against whatever directory that left the process in (observed: the main
#: repo checkout, NOT this worktree) instead of raising — passing
#: vacuously on an empty diff. Anchoring with `cwd=` makes this reliable
#: regardless of ambient cwd mutations elsewhere in the test session.
_REPO_ROOT = Path(__file__).resolve().parents[5]


class TestGoldensUntouched:
    def test_no_catalog_file_modified(self):
        """Guard the spec's hard constraint: this feature never edits a lower()."""
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "origin/dev",
                "--",
                "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/",
                "packages/ai-parrot/tests/outputs/a2ui/golden/",
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=_REPO_ROOT,
        ).stdout.split()
        # filterbar.py + its golden are the ONLY permitted additions
        # (TASK-2715); catalog/parrot/__init__.py registering the new
        # `filterbar` module in its import list is the one other
        # unavoidable touch — every new catalog component requires it.
        #
        # FEAT-527 permits three further, explicit, spec-sanctioned classes
        # of change:
        # 1. TASK-2859/2860: "FEAT-493 froze them for its scope; this
        #    feature legitimately changes lower() output for
        #    Infographic/Chart/KPICard/DataTable" (spec §7 "Golden
        #    fixtures"). Presentation-parity props (chart types/layout,
        #    KPICard icon/color, DataTable style, Infographic half-width Row
        #    grouping) are additive and gated on the value being present, so
        #    none of the FROZEN goldens actually changed byte-for-byte —
        #    only the `lower()` source allowing the new behavior did.
        # 2. TASK-2862: the generic `tool_only` registration gate
        #    (`catalog/base.py`, `catalog/__init__.py`) — additive, mirrors
        #    the existing `requires_actions` gate mechanism.
        # 3. TASK-2863: a brand-new component, `HtmlDocument` (spec G5) —
        #    same "new component" precedent as `filterbar.py`.
        _FEAT_527_FROZEN_LOWER_FILES = (
            "catalog/parrot/chart.py",
            "catalog/parrot/datatable.py",
            "catalog/parrot/infographic.py",
            "catalog/parrot/kpicard.py",
        )
        _FEAT_527_TOOL_ONLY_GATE_FILES = (
            "catalog/base.py",
            "catalog/__init__.py",
        )
        assert all(
            "filterbar" in c
            or "htmldocument" in c
            or c.endswith("catalog/parrot/__init__.py")
            or c.endswith(_FEAT_527_FROZEN_LOWER_FILES)
            or c.endswith(_FEAT_527_TOOL_ONLY_GATE_FILES)
            for c in changed
        ), changed


class TestTailwindCoverageIntegration:
    """FEAT-522 TASK-2790: DesignSystem.stylesheet() folds in the generated
    Tailwind CSS (design_system/tailwind.generated.css, TASK-2789's output)."""

    def test_stylesheet_includes_tailwind_generated_rules(self):
        sheet = DesignSystem.stylesheet()
        assert ".a2ui-col" in sheet  # a known base-primitive selector from TASK-2789's output

    def test_stylesheet_degrades_gracefully_if_tailwind_css_missing(self, monkeypatch):
        """`_read_asset()`'s existing missing-file contract (None -> `""`)
        must keep `stylesheet()` returning a normal, non-empty sheet — never
        raising — even if `tailwind.generated.css` is absent."""
        import parrot.outputs.formats.assets.design_system as design_system_module

        monkeypatch.setattr(design_system_module, "_TAILWIND_CSS", "")
        DesignSystem._cache.clear()
        try:
            sheet = DesignSystem.stylesheet()
            assert sheet  # base/components CSS + theme vars still present
            assert ".a2ui-col" not in sheet  # the Tailwind-only rule is gone
        finally:
            DesignSystem._cache.clear()


def _generate_a2ui_css_module():
    """Import `scripts/generate_a2ui_css.py` as a module (FEAT-522 TASK-2793).

    `scripts/` isn't part of any installed package's import path — mirrors
    `tests/scripts/test_generate_tool_registry.py`'s own
    `sys.path.insert(0, str(Path(__file__).resolve().parents[N] / "scripts"))`
    pattern so this test reuses the REAL AST-scanning logic (never a
    hand-duplicated copy that could drift from the actual generator).
    """
    scripts_dir = str(_REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import generate_a2ui_css

    return generate_a2ui_css


class TestTailwindClassCoverage:
    """FEAT-522 TASK-2793: coverage-audit — every class
    `interactive_html.py` can emit has a real CSS rule somewhere in
    `DesignSystem.stylesheet()`'s output (not necessarily from the
    Tailwind-generated file specifically — `kpi-grid` is deliberately
    excluded from Tailwind generation, TASK-2788's follow-up fix, but is
    still covered via `components.css`/`layout-*.css`)."""

    def test_all_a2ui_classes_have_css_rule(self):
        gen = _generate_a2ui_css_module()
        # Post-review fix: union in the curated `a2ui-<role>` classes too
        # (`_render_prim_Text`'s `f"a2ui-{role}"` is a dynamically-
        # interpolated, non-literal class the plain AST scan alone can
        # never see — see `scan_dynamic_role_classes()`'s docstring).
        # Without this union, this test would be self-referentially blind
        # to the exact same gap `generate_a2ui_css.py`'s generator has,
        # rather than actually verifying the renderer's real output.
        classes = gen.scan_classes(gen.INTERACTIVE_HTML_PATH) | gen.scan_dynamic_role_classes(gen.SEMANTICS_PATH)
        sheet = DesignSystem.stylesheet()
        missing = sorted(cls for cls in classes if f".{cls}" not in sheet)
        assert not missing, f"Classes with no CSS rule in DesignSystem.stylesheet(): {missing}"
