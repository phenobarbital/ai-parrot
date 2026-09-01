"""Unit tests for layout-report.css / layout-print.css (FEAT-493, TASK-2708)."""
import re
from pathlib import Path

import pytest
from parrot.models.infographic import theme_registry
from parrot.outputs.formats.assets.design_system import DesignSystem
from parrot.outputs.formats.infographic_html import BASE_CSS

_SELECTOR_RE = re.compile(r"^\s*([^{}@/]+?)\s*\{", re.MULTILINE)


def _legacy_selectors() -> set[str]:
    return {s.strip() for s in _SELECTOR_RE.findall(BASE_CSS) if s.strip()}


def _top_level_selectors(css: str) -> set[str]:
    """Extract only TOP-LEVEL rule selectors (never a nested @media override).

    A selector like ``.kpi-grid`` legitimately reappears inside a narrow
    ``@media`` breakpoint override without that being "the same rule
    restated" — this walks brace depth so an @media block's *contents*
    are treated as opaque, matching how layout-report.css was migrated.
    """
    selectors: set[str] = set()
    i = 0
    n = len(css)
    last_end = 0
    while i < n:
        if css[i] == "{":
            header = css[last_end:i].strip()
            depth = 1
            j = i + 1
            while depth > 0 and j < n:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            if header and not header.startswith("@"):
                selectors.add(header)
            last_end = j
            i = j
        else:
            i += 1
    return selectors


class TestReportLayoutParity:
    def test_report_layout_matches_legacy_selectors(self):
        """Every legacy selector survives the migration — mechanically checked."""
        composed = DesignSystem.stylesheet("light", "report")
        missing = sorted(s for s in _legacy_selectors() if s not in composed)
        assert not missing, f"selectors lost in migration: {missing}"

    def test_report_layout_does_not_duplicate_components(self):
        """layout-report.css must not restate a TOP-LEVEL rule already in
        components.css. A selector legitimately reappearing inside a
        narrow @media breakpoint override (e.g. ``.kpi-grid`` collapsing
        to one column under 560px) is not "the same rule restated"."""
        import parrot.outputs.formats.assets.design_system as ds_pkg
        from parrot.outputs.formats.assets.design_system import _COMPONENTS_CSS

        components_selectors = _top_level_selectors(_COMPONENTS_CSS)
        report_path = Path(ds_pkg.__file__).parent / "layout-report.css"
        report_text = report_path.read_text(encoding="utf-8")
        report_selectors = _top_level_selectors(report_text)
        overlap = components_selectors & report_selectors
        assert not overlap, (
            f"duplicated rules between components.css and layout-report.css: {overlap}"
        )


class TestPrintLayout:
    def test_no_shadows(self):
        css = DesignSystem.stylesheet("light", "print")
        assert "--shadow: none" in css or "box-shadow: none" in css

    def test_no_auto_fit(self):
        css = DesignSystem.stylesheet("light", "print")
        assert "auto-fit" not in css
        assert "minmax" not in css

    def test_page_rules_present(self):
        css = DesignSystem.stylesheet("light", "print")
        assert "@page" in css
        assert "break-inside" in css


@pytest.mark.parametrize("theme", sorted(theme_registry.list_themes()))
@pytest.mark.parametrize("layout", ["report", "analytics", "print"])
def test_all_theme_layout_pairs_compose(theme, layout):
    css = DesignSystem.stylesheet(theme, layout)
    assert css.strip()
    assert "@import" not in css
    assert "url(http" not in css
