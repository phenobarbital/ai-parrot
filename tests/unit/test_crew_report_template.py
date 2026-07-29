"""
Unit tests for the `crew_report` infographic template variant (FEAT-308).

TASK-1775: Register `crew_report` Infographic Template Variant

Verifies that `crew_report` is registered on `infographic_registry` with a
bound-relaxed `TAB_VIEW` block (no `min_items`/`max_items`), and that the
existing `multi_tab` template is left unchanged.
"""
from parrot.models.infographic_templates import infographic_registry, BlockType


class TestCrewReportTemplate:
    def test_crew_report_template_registered(self):
        """crew_report is discoverable in the registry."""
        tpl = infographic_registry.get("crew_report")
        assert tpl is not None
        assert tpl.name == "crew_report"

    def test_tab_view_no_clamp(self):
        """TAB_VIEW block has no min_items / max_items."""
        tpl = infographic_registry.get("crew_report")
        tab_spec = next(s for s in tpl.block_specs if s.block_type == BlockType.TAB_VIEW)
        assert tab_spec.min_items is None
        assert tab_spec.max_items is None

    def test_has_required_title_block(self):
        """crew_report requires a TITLE block."""
        tpl = infographic_registry.get("crew_report")
        title_spec = next(s for s in tpl.block_specs if s.block_type == BlockType.TITLE)
        assert title_spec.required is True

    def test_multi_tab_unchanged(self):
        """Existing multi_tab template retains its 3-7 clamp."""
        tpl = infographic_registry.get("multi_tab")
        tab_spec = next(s for s in tpl.block_specs if s.block_type == BlockType.TAB_VIEW)
        assert tab_spec.min_items == 3
        assert tab_spec.max_items == 7

    def test_crew_report_listed(self):
        """crew_report appears in list_templates()."""
        assert "crew_report" in infographic_registry.list_templates()
