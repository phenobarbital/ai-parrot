"""Unit tests for layout-report.css / layout-print.css (FEAT-493, TASK-2708)."""
import re
from pathlib import Path

import pytest
from parrot.models.infographic import theme_registry
from parrot.outputs.formats.assets.design_system import DesignSystem

_SELECTOR_RE = re.compile(r"^\s*([^{}@/]+?)\s*\{", re.MULTILINE)

#: Frozen snapshot of every top-level selector the legacy
#: ``infographic_html.BASE_CSS`` declared, taken BEFORE TASK-2712 deleted
#: that constant (its job — being the exact source `layout-report.css` was
#: migrated from — was done once, at migration time). Kept here, rather
#: than re-reading the (now-gone) constant, so this parity guard keeps
#: working after TASK-2712's `test_no_base_css_constant` requirement that
#: `BASE_CSS` no longer exists on the module.
_LEGACY_SELECTORS: frozenset[str] = frozenset(
    {
        ".accordion",
        ".accordion__arrow",
        ".accordion__badge",
        ".accordion__body",
        ".accordion__header",
        ".accordion__header:hover",
        ".accordion__item",
        ".accordion__item-title",
        ".accordion__item.open .accordion__arrow",
        ".accordion__item.open .accordion__body",
        ".accordion__number",
        ".accordion__subtitle",
        ".accordion__title",
        ".bullet-list--compact li",
        ".bullet-list--grid",
        ".bullet-list--grid-2",
        ".bullet-list--grid-3",
        ".bullet-list--grid-4",
        ".bullet-list--titled .bullet-list__header",
        ".bullet-list-block",
        ".bullet-list-block h3",
        ".bullet-list-block li",
        ".bullet-list-block ul, .bullet-list-block ol",
        ".bullet-list__dot",
        ".bullet-list__item-dot",
        ".callout-block",
        ".callout-block h3",
        ".callout-block.error",
        ".callout-block.error h3",
        ".callout-block.info",
        ".callout-block.info h3",
        ".callout-block.success",
        ".callout-block.success h3",
        ".callout-block.tip",
        ".callout-block.tip h3",
        ".callout-block.warning",
        ".callout-block.warning h3",
        ".card-grid",
        ".card-grid-wrapper",
        ".card-grid__body",
        ".card-grid__card",
        ".card-grid__card-title",
        ".card-grid__title",
        ".chain",
        ".chain--vertical",
        ".chain--vertical .chain__connector",
        ".chain__connector",
        ".chain__desc",
        ".chain__label",
        ".chain__node",
        ".chain__title",
        ".chart-container",
        ".chart-container h3",
        ".checklist",
        ".checklist--acceptance .checklist__title",
        ".checklist--compact .checklist__checkbox",
        ".checklist--compact .checklist__item",
        ".checklist__checkbox",
        ".checklist__desc",
        ".checklist__item",
        ".checklist__item--checked .checklist__checkbox",
        ".checklist__items",
        ".checklist__title",
        ".chip",
        ".code-block",
        ".code-block-wrapper",
        ".code-block__line--highlight",
        ".code-block__title",
        ".component-ref",
        ".container",
        ".data-table caption",
        ".data-table--bordered",
        ".data-table--bordered td, .data-table--bordered th",
        ".data-table--compact td, .data-table--compact th",
        ".data-table--comparison td:first-child",
        ".data-table--responsive",
        ".data-table--striped tbody tr:nth-child(even)",
        ".doc-bar",
        ".doc-changelog",
        ".doc-changelog__date",
        ".doc-changelog__entry",
        ".doc-changelog__entry:last-child",
        ".doc-changelog__summary",
        ".doc-changelog__title",
        ".doc-changelog__version",
        ".doc-footer",
        ".doc-pill",
        ".doc-pill--status",
        ".empty-message",
        ".hero",
        ".hero .meta",
        ".hero h1",
        ".hero p",
        ".i18n",
        ".i18n--default",
        ".image-block",
        ".image-block .caption",
        ".image-block img",
        ".kpi-card",
        ".kpi-grid",
        ".kpi-label",
        ".kpi-trend",
        ".kpi-trend.down",
        ".kpi-trend.flat",
        ".kpi-trend.up",
        ".kpi-value",
        ".method-badge",
        ".method-badge--delete",
        ".method-badge--get",
        ".method-badge--head",
        ".method-badge--options",
        ".method-badge--patch",
        ".method-badge--post",
        ".method-badge--put",
        ".progress-block",
        ".progress-block h3",
        ".progress-fill",
        ".progress-header",
        ".progress-item",
        ".progress-label",
        ".progress-target",
        ".progress-track",
        ".progress-value",
        ".section-title",
        ".section-title::after",
        ".steps",
        ".steps--icon .steps__marker",
        ".steps__desc",
        ".steps__item",
        ".steps__label",
        ".steps__marker",
        ".steps__title",
        ".summary-block",
        ".summary-block h3",
        ".summary-block.highlight",
        ".tab-view",
        ".tab-view__btn",
        ".tab-view__btn.active",
        ".tab-view__btn:hover",
        ".tab-view__nav",
        ".tab-view__nav--boxed .tab-view__btn",
        ".tab-view__nav--underline",
        ".tab-view__nav--underline .tab-view__btn",
        ".tab-view__nav--underline .tab-view__btn.active",
        ".tab-view__pane",
        ".tab-view__pane.active",
        ".table-container",
        ".table-container h3",
        ".timeline-block",
        ".timeline-block h3",
        ".timeline-content",
        ".timeline-content .desc",
        ".timeline-content .title",
        ".timeline-date",
        ".timeline-event",
        ".timeline-event::after",
        ".timeline-event::before",
        ".timeline-event:last-child::after",
        "blockquote.quote-block",
        "blockquote.quote-block .attribution",
        "body",
        "footer.infographic-footer",
        "hr.divider",
        "hr.divider.dashed",
        "hr.divider.dotted",
        "hr.divider.gradient",
        "hr.divider.solid",
        "table",
        "td",
        "th",
        "tr:hover",
        "tr:nth-child(even)",
    }
)


def _legacy_selectors() -> set[str]:
    return set(_LEGACY_SELECTORS)


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
