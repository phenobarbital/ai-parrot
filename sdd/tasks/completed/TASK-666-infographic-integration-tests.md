# TASK-666: Integration Tests for Multi-Tab Infographic

**Feature**: Multi-Tab Infographic Template + New Component Blocks
**Spec**: `sdd/specs/multi-tab-infographic.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-659, TASK-660, TASK-661, TASK-662, TASK-663, TASK-664
**Assigned-to**: unassigned

---

## Context

This task creates comprehensive integration tests that validate the full pipeline: constructing multi-tab InfographicResponse objects with all new block types, rendering them to HTML, and verifying the output structure, interactivity scripts, CSS, and backward compatibility. Implements Spec Section 4 (Test Specification — Integration Tests).

---

## Scope

- Create `tests/test_infographic_multi_tab.py` with integration tests:
  - Full multi-tab InfographicResponse → render_to_html() → validate HTML
  - All new block types used together in a realistic multi-tab layout
  - Backward compatibility: all 6 existing templates produce identical output
  - Edge cases: empty tab panes, accordion with empty content, max depth exceeded
  - JS injection: verify tab JS present when TabViewBlock used, absent when not
  - JS injection: verify accordion JS present when AccordionBlock used
  - Print CSS: verify `@media print` rules in output
  - XSS: verify html_content sanitization in full pipeline
  - Theme integration: render with each built-in theme (light, dark, corporate)
- Ensure all existing tests in `test_infographic_html.py` still pass

**NOT in scope**: LLM integration tests (testing actual LLM responses). Mock-based auto-detection tests are in TASK-665.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_infographic_multi_tab.py` | CREATE | Integration tests for full multi-tab pipeline |
| `tests/test_infographic_html.py` | VERIFY | Confirm all existing tests still pass |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.infographic import (
    BlockType, InfographicBlock, InfographicResponse,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock,
    BulletListBlock, BulletListStyle, TableBlock, TableStyle, ColumnDef,
    AccordionBlock, AccordionItem,
    ChecklistBlock, ChecklistItem,
    TabViewBlock, TabPane,
    ImageBlock, QuoteBlock, CalloutBlock, DividerBlock, TimelineBlock, ProgressBlock,
)
from parrot.models.infographic_templates import infographic_registry
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
```

### Does NOT Exist
- All block models and renderers should exist by the time this task runs (all dependencies completed)
- ~~`bleach`~~ — NOT to be used, `nh3` is the sanitization library

---

## Implementation Notes

### Key Test Scenarios

1. **Full realistic multi-tab infographic**: Title + TabViewBlock with 3-4 tabs, each containing different block combinations (summary, bullets with columns, styled tables, accordions with nested blocks, checklists).
2. **Backward compat suite**: For each of the 6 existing templates (basic, executive, dashboard, comparison, timeline, minimal), construct a typical InfographicResponse and verify render_to_html produces valid HTML without errors.
3. **Theme rendering**: Render the same multi-tab response with light, dark, and corporate themes. Verify CSS variables are present.
4. **Edge cases**: TabPane with empty blocks list, AccordionItem with neither content_blocks nor html_content, deeply nested blocks at max_depth.
5. **Print CSS**: Search output HTML for `@media print` rules that hide tab nav and show all panes.

### Pattern to Follow
```python
# Use the multi_tab_response fixture pattern from the spec:
@pytest.fixture
def multi_tab_response():
    return InfographicResponse(
        template="multi_tab", theme="light",
        blocks=[
            TitleBlock(title="Test Report", subtitle="Integration Test"),
            TabViewBlock(tabs=[
                TabPane(id="overview", label="Overview", blocks=[...]),
                TabPane(id="details", label="Details", blocks=[...]),
                TabPane(id="qa", label="QA", blocks=[...]),
            ]),
        ],
    )
```

---

## Acceptance Criteria

- [ ] Full multi-tab infographic renders to valid HTML5 document
- [ ] All block types render without errors when nested in tabs
- [ ] All 6 existing templates still produce valid output (zero regressions)
- [ ] Tab switching JS (`showTab`) present in output when TabViewBlock used
- [ ] Accordion JS (`toggleAccordion`) present when AccordionBlock used
- [ ] Neither JS present when only flat blocks used
- [ ] Print CSS rules present in output
- [ ] XSS: html_content sanitized in full pipeline
- [ ] Themes: light, dark, corporate all produce valid output with CSS vars
- [ ] All new integration tests pass: `pytest tests/test_infographic_multi_tab.py -v`
- [ ] All existing tests pass: `pytest tests/test_infographic_html.py -v`

---

## Test Specification

```python
import pytest
from parrot.models.infographic import (
    InfographicResponse, TitleBlock, SummaryBlock, TabViewBlock, TabPane,
    AccordionBlock, AccordionItem, ChecklistBlock, ChecklistItem,
    BulletListBlock, BulletListStyle, TableBlock, TableStyle, ColumnDef,
    HeroCardBlock, ChartBlock, ChartDataSeries, ChartType,
    CalloutBlock, CalloutLevel, TimelineBlock, TimelineEvent,
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


@pytest.fixture
def multi_tab_response():
    return InfographicResponse(
        template="multi_tab",
        theme="light",
        blocks=[
            TitleBlock(title="AI Agent Methodology", subtitle="Implementation Guide"),
            TabViewBlock(tabs=[
                TabPane(id="overview", label="Overview", icon="📊", blocks=[
                    SummaryBlock(content="This guide covers the full methodology."),
                    BulletListBlock(
                        title="Key Areas", items=["LLMs", "RAG", "Agents", "Tools"],
                        color="#534AB7", columns=2, style=BulletListStyle.TITLED,
                    ),
                ]),
                TabPane(id="phases", label="Phases", blocks=[
                    AccordionBlock(items=[
                        AccordionItem(
                            title="Phase 1: Discovery", number=1, number_color="#534AB7",
                            badge="Weeks 1-2", badge_color="#e8e4f8",
                            content_blocks=[
                                TableBlock(
                                    columns=[
                                        ColumnDef(header="Input", align="left"),
                                        ColumnDef(header="Output", align="left"),
                                    ],
                                    rows=[["Requirements", "Scope doc"]],
                                    style=TableStyle.BORDERED,
                                ),
                            ],
                        ),
                        AccordionItem(title="Phase 2: Build", number=2, number_color="#2D9CDB"),
                    ]),
                ]),
                TabPane(id="qa", label="QA", blocks=[
                    ChecklistBlock(title="Acceptance Criteria", style="acceptance", items=[
                        ChecklistItem(text="All flows tested", checked=True),
                        ChecklistItem(text="Performance validated"),
                        ChecklistItem(text="Security review done", description="OWASP top 10"),
                    ]),
                ]),
            ]),
        ],
    )


class TestMultiTabIntegration:
    def test_full_render(self, renderer, multi_tab_response):
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "<!DOCTYPE html>" in html
        assert "AI Agent Methodology" in html
        assert "tab-view" in html
        assert "accordion" in html
        assert "checklist" in html

    def test_tab_js_injected(self, renderer, multi_tab_response):
        html = renderer.render_to_html(multi_tab_response)
        assert "showTab" in html

    def test_accordion_js_injected(self, renderer, multi_tab_response):
        html = renderer.render_to_html(multi_tab_response)
        assert "toggleAccordion" in html

    def test_print_css(self, renderer, multi_tab_response):
        html = renderer.render_to_html(multi_tab_response)
        assert "@media print" in html

    def test_all_themes(self, renderer, multi_tab_response):
        for theme in ("light", "dark", "corporate"):
            html = renderer.render_to_html(multi_tab_response, theme=theme)
            assert "<!DOCTYPE html>" in html
            assert "--primary" in html

    def test_xss_in_accordion_html_content(self, renderer):
        response = InfographicResponse(blocks=[
            TabViewBlock(tabs=[
                TabPane(id="a", label="A", blocks=[
                    AccordionBlock(items=[
                        AccordionItem(title="X", html_content="<script>alert(1)</script><p>Safe</p>"),
                    ]),
                ]),
                TabPane(id="b", label="B", blocks=[]),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "<script>" not in html
        assert "<p>Safe</p>" in html


class TestBackwardCompatibility:
    def test_basic_template_unaffected(self, renderer):
        response = InfographicResponse(
            template="basic",
            blocks=[
                TitleBlock(title="Simple"),
                SummaryBlock(content="Hello"),
                BulletListBlock(items=["A", "B"]),
            ],
        )
        html = renderer.render_to_html(response, theme="light")
        assert "<!DOCTYPE html>" in html
        assert "showTab" not in html  # no tab JS
        assert "toggleAccordion" not in html  # no accordion JS

    def test_existing_table_still_works(self, renderer):
        response = InfographicResponse(blocks=[
            TableBlock(columns=["Name", "Value"], rows=[["A", "1"]]),
        ])
        html = renderer.render_to_html(response, theme="light")
        assert "<th>" in html
        assert "A" in html


class TestEdgeCases:
    def test_empty_tab_pane(self, renderer):
        response = InfographicResponse(blocks=[
            TabViewBlock(tabs=[
                TabPane(id="a", label="A", blocks=[SummaryBlock(content="X")]),
                TabPane(id="b", label="B", blocks=[]),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "<!DOCTYPE html>" in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/multi-tab-infographic.spec.md`
2. **Check dependencies** — ALL prior tasks must be completed
3. **Run existing tests first**: `pytest tests/test_infographic_html.py -v` to establish baseline
4. **Create** `tests/test_infographic_multi_tab.py` with integration tests
5. **Verify** all tests pass (new and existing)
6. **Move to completed**, **update index**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
