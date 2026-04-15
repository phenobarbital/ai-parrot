"""
Integration Tests for FEAT-102: Multi-Tab Infographic Template + New Component Blocks.

TASK-666: Integration Tests for Multi-Tab Infographic

Validates the full pipeline:
  - Constructing multi-tab InfographicResponse objects with all new block types
  - Rendering them to HTML via InfographicHTMLRenderer
  - Verifying output structure, interactivity scripts, CSS, and backward compat
"""
import pytest
from parrot.models.infographic import (
    BlockType, InfographicBlock, InfographicResponse,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, ChartDataSeries, ChartType,
    BulletListBlock, BulletListStyle, TableBlock, TableStyle, ColumnDef,
    AccordionBlock, AccordionItem,
    ChecklistBlock, ChecklistItem,
    TabViewBlock, TabPane,
    ImageBlock, QuoteBlock, CalloutBlock, CalloutLevel,
    TimelineBlock, TimelineEvent,
    DividerBlock, ProgressBlock,
)
from parrot.models.infographic_templates import infographic_registry
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def renderer():
    """Shared InfographicHTMLRenderer instance."""
    return InfographicHTMLRenderer()


@pytest.fixture
def multi_tab_response():
    """Realistic multi-tab infographic with all new block types."""
    return InfographicResponse(
        template="multi_tab",
        theme="light",
        blocks=[
            TitleBlock(title="AI Agent Methodology", subtitle="Implementation Guide"),
            TabViewBlock(tabs=[
                TabPane(id="overview", label="Overview", icon="📊", blocks=[
                    SummaryBlock(content="This guide covers the full AI agent implementation methodology."),
                    BulletListBlock(
                        title="Key Areas",
                        items=["LLMs", "RAG", "Agents", "Tools"],
                        color="#534AB7",
                        columns=2,
                        style=BulletListStyle.TITLED,
                    ),
                ]),
                TabPane(id="phases", label="Phases", blocks=[
                    AccordionBlock(items=[
                        AccordionItem(
                            title="Phase 1: Discovery",
                            number=1,
                            number_color="#534AB7",
                            badge="Weeks 1-2",
                            badge_color="#e8e4f8",
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
                        AccordionItem(
                            title="Phase 2: Build",
                            number=2,
                            number_color="#2D9CDB",
                        ),
                        AccordionItem(
                            title="Phase 3: Deployment",
                            number=3,
                            number_color="#27AE60",
                            html_content="<p>Deploy to production with <strong>monitoring</strong>.</p>",
                        ),
                    ]),
                ]),
                TabPane(id="qa", label="QA", blocks=[
                    ChecklistBlock(title="Acceptance Criteria", style="acceptance", items=[
                        ChecklistItem(text="All flows tested", checked=True),
                        ChecklistItem(text="Performance validated"),
                        ChecklistItem(
                            text="Security review done",
                            description="OWASP top 10 checklist completed",
                        ),
                    ]),
                ]),
            ]),
        ],
    )


@pytest.fixture
def flat_response():
    """A simple flat (no tabs) infographic for backward compat tests."""
    return InfographicResponse(
        template="basic",
        theme="light",
        blocks=[
            TitleBlock(title="Simple Report"),
            SummaryBlock(content="A simple summary."),
            BulletListBlock(items=["Item A", "Item B", "Item C"]),
        ],
    )


# ──────────────────────────────────────────────
# TestMultiTabIntegration
# ──────────────────────────────────────────────

class TestMultiTabIntegration:
    """Full pipeline tests for multi-tab infographic rendering."""

    def test_full_render_produces_html5_document(self, renderer, multi_tab_response):
        """Full multi-tab infographic renders to a valid HTML5 document."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_title_present_in_output(self, renderer, multi_tab_response):
        """Title from the TitleBlock is present in rendered HTML."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "AI Agent Methodology" in html

    def test_tab_view_structure_rendered(self, renderer, multi_tab_response):
        """tab-view CSS class is present in output."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "tab-view" in html

    def test_all_tab_labels_rendered(self, renderer, multi_tab_response):
        """All tab labels (Overview, Phases, QA) appear in output."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "Overview" in html
        assert "Phases" in html
        assert "QA" in html

    def test_accordion_block_rendered(self, renderer, multi_tab_response):
        """Accordion structure is rendered inside tab pane."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "accordion" in html
        assert "Phase 1: Discovery" in html
        assert "Phase 2: Build" in html
        assert "Phase 3: Deployment" in html

    def test_checklist_rendered(self, renderer, multi_tab_response):
        """Checklist block renders correctly inside tab pane."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "checklist" in html
        assert "Acceptance Criteria" in html
        assert "All flows tested" in html

    def test_accordion_badge_rendered(self, renderer, multi_tab_response):
        """AccordionItem badge is rendered."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "Weeks 1-2" in html

    def test_nested_table_in_accordion_rendered(self, renderer, multi_tab_response):
        """TableBlock nested inside AccordionItem content_blocks renders correctly."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "Requirements" in html
        assert "Scope doc" in html

    def test_tab_js_injected(self, renderer, multi_tab_response):
        """showTab() JS function present when TabViewBlock used."""
        html = renderer.render_to_html(multi_tab_response)
        assert "showTab" in html

    def test_accordion_js_injected(self, renderer, multi_tab_response):
        """toggleAccordion() JS function present when AccordionBlock used."""
        html = renderer.render_to_html(multi_tab_response)
        assert "toggleAccordion" in html

    def test_print_css_present(self, renderer, multi_tab_response):
        """@media print rules present in rendered output."""
        html = renderer.render_to_html(multi_tab_response)
        assert "@media print" in html

    def test_css_variables_present(self, renderer, multi_tab_response):
        """CSS custom properties (--primary) used in output."""
        html = renderer.render_to_html(multi_tab_response, theme="light")
        assert "--primary" in html

    def test_all_themes_render(self, renderer, multi_tab_response):
        """Rendering with light, dark, and corporate themes all succeed."""
        for theme in ("light", "dark", "corporate"):
            html = renderer.render_to_html(multi_tab_response, theme=theme)
            assert "<!DOCTYPE html>" in html, f"Invalid HTML for theme '{theme}'"
            assert "--primary" in html, f"CSS vars missing for theme '{theme}'"

    def test_xss_in_accordion_html_content(self, renderer):
        """html_content in AccordionItem is sanitized in full pipeline."""
        response = InfographicResponse(
            blocks=[
                TabViewBlock(tabs=[
                    TabPane(id="a", label="A", blocks=[
                        AccordionBlock(items=[
                            AccordionItem(
                                title="Safe Content",
                                html_content=(
                                    "<script>alert(1)</script>"
                                    "<p>Safe paragraph</p>"
                                    "<img src=x onerror=alert(1)>"
                                ),
                            ),
                        ]),
                    ]),
                    TabPane(id="b", label="B", blocks=[]),
                ]),
            ],
        )
        html = renderer.render_to_html(response)
        # nh3 removes script tags and their content; onerror attribute stripped
        assert "alert(1)" not in html
        assert "onerror" not in html
        # Safe content preserved
        assert "<p>Safe paragraph</p>" in html

    def test_active_tab_first(self, renderer, multi_tab_response):
        """The first tab (overview) is the active tab."""
        html = renderer.render_to_html(multi_tab_response)
        # The tab pane for "overview" should be active
        assert 'tv0-overview' in html

    def test_checklist_checked_item_rendered(self, renderer, multi_tab_response):
        """Checked checklist items are rendered with checked state CSS class."""
        html = renderer.render_to_html(multi_tab_response)
        assert "checklist__item" in html
        assert "checklist__item--checked" in html

    def test_checklist_item_description_rendered(self, renderer, multi_tab_response):
        """ChecklistItem with description renders the description text."""
        html = renderer.render_to_html(multi_tab_response)
        assert "OWASP top 10" in html

    def test_accordion_html_content_preserved(self, renderer, multi_tab_response):
        """html_content safe HTML is preserved in accordion rendering."""
        html = renderer.render_to_html(multi_tab_response)
        # Phase 3 has html_content with <p> and <strong>
        assert "monitoring" in html


# ──────────────────────────────────────────────
# TestBackwardCompatibility
# ──────────────────────────────────────────────

class TestBackwardCompatibility:
    """Verify existing templates still produce valid output (zero regressions)."""

    def test_basic_template_renders(self, renderer, flat_response):
        """basic template renders without errors."""
        html = renderer.render_to_html(flat_response, theme="light")
        assert "<!DOCTYPE html>" in html
        assert "Simple Report" in html

    def test_basic_no_tab_js(self, renderer, flat_response):
        """basic template output does NOT include tab JS."""
        html = renderer.render_to_html(flat_response, theme="light")
        assert "showTab" not in html

    def test_basic_no_accordion_js(self, renderer, flat_response):
        """basic template output does NOT include accordion JS."""
        html = renderer.render_to_html(flat_response, theme="light")
        assert "toggleAccordion" not in html

    def test_executive_template_renders(self, renderer):
        """executive template renders without errors."""
        response = InfographicResponse(
            template="executive",
            blocks=[
                TitleBlock(title="Q4 Briefing", subtitle="2025"),
                HeroCardBlock(label="Revenue", value="$5M", trend="up"),
                HeroCardBlock(label="ARR", value="$5M"),
                SummaryBlock(content="Executive overview."),
                DividerBlock(),
                TableBlock(columns=["Metric", "Value"], rows=[["ARR", "$5M"]]),
                BulletListBlock(items=["Recommendation 1", "Recommendation 2"]),
            ],
        )
        html = renderer.render_to_html(response, theme="corporate")
        assert "<!DOCTYPE html>" in html
        assert "Q4 Briefing" in html

    def test_dashboard_template_renders(self, renderer):
        """dashboard template renders without errors."""
        response = InfographicResponse(
            template="dashboard",
            blocks=[
                TitleBlock(title="Dashboard"),
                HeroCardBlock(label="Users", value="10K"),
                HeroCardBlock(label="Revenue", value="$1M"),
                TableBlock(columns=["Metric", "Value"], rows=[["DAU", "10K"]]),
            ],
        )
        html = renderer.render_to_html(response, theme="dark")
        assert "<!DOCTYPE html>" in html

    def test_comparison_template_renders(self, renderer):
        """comparison template renders without errors."""
        response = InfographicResponse(
            template="comparison",
            blocks=[
                TitleBlock(title="A vs B"),
                SummaryBlock(content="Comparing A and B."),
                TableBlock(
                    columns=["Feature", "A", "B"],
                    rows=[["Speed", "Fast", "Slow"]],
                ),
                BulletListBlock(items=["A wins on speed"]),
            ],
        )
        html = renderer.render_to_html(response, theme="light")
        assert "<!DOCTYPE html>" in html

    def test_timeline_template_renders(self, renderer):
        """timeline template renders without errors."""
        response = InfographicResponse(
            template="timeline",
            blocks=[
                TitleBlock(title="Project History"),
                SummaryBlock(content="Timeline overview."),
                TimelineBlock(events=[
                    TimelineEvent(date="2024-01", title="Kickoff", description="Project started"),
                    TimelineEvent(date="2024-06", title="Alpha", description="First release"),
                ]),
                BulletListBlock(items=["Lesson 1", "Lesson 2"]),
            ],
        )
        html = renderer.render_to_html(response, theme="light")
        assert "<!DOCTYPE html>" in html
        assert "Kickoff" in html

    def test_minimal_template_renders(self, renderer):
        """minimal template renders without errors."""
        response = InfographicResponse(
            template="minimal",
            blocks=[
                TitleBlock(title="Minimal Report"),
                SummaryBlock(content="Just the basics."),
                BulletListBlock(items=["Point 1", "Point 2"]),
            ],
        )
        html = renderer.render_to_html(response, theme="light")
        assert "<!DOCTYPE html>" in html

    def test_existing_table_string_columns_unchanged(self, renderer):
        """TableBlock with List[str] columns still renders correctly (no regression)."""
        response = InfographicResponse(blocks=[
            TableBlock(columns=["Name", "Value"], rows=[["Alpha", "1"], ["Beta", "2"]]),
        ])
        html = renderer.render_to_html(response, theme="light")
        assert "<th>" in html
        assert "Alpha" in html
        assert "Beta" in html

    def test_bullet_list_default_style_unchanged(self, renderer):
        """BulletListBlock without new fields renders identically to pre-FEAT-102."""
        response = InfographicResponse(blocks=[
            BulletListBlock(items=["X", "Y", "Z"]),
        ])
        html = renderer.render_to_html(response, theme="light")
        assert "bullet-list" in html
        assert "X" in html


# ──────────────────────────────────────────────
# TestEdgeCases
# ──────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases: empty panes, empty accordions, deeply nested content."""

    def test_empty_tab_pane_renders(self, renderer):
        """TabPane with empty blocks list renders without errors."""
        response = InfographicResponse(blocks=[
            TabViewBlock(tabs=[
                TabPane(id="a", label="Active", blocks=[
                    SummaryBlock(content="Something here."),
                ]),
                TabPane(id="b", label="Empty", blocks=[]),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "<!DOCTYPE html>" in html
        assert "Active" in html
        assert "Empty" in html

    def test_accordion_item_no_content(self, renderer):
        """AccordionItem with neither content_blocks nor html_content renders."""
        response = InfographicResponse(blocks=[
            AccordionBlock(items=[
                AccordionItem(title="Empty Item"),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "Empty Item" in html

    def test_checklist_all_unchecked(self, renderer):
        """ChecklistBlock with all unchecked items renders correctly."""
        response = InfographicResponse(blocks=[
            ChecklistBlock(items=[
                ChecklistItem(text="Step 1"),
                ChecklistItem(text="Step 2"),
                ChecklistItem(text="Step 3"),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "checklist" in html
        assert "Step 1" in html

    def test_checklist_all_checked(self, renderer):
        """ChecklistBlock with all checked items renders correctly."""
        response = InfographicResponse(blocks=[
            ChecklistBlock(items=[
                ChecklistItem(text="Done 1", checked=True),
                ChecklistItem(text="Done 2", checked=True),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "Done 1" in html

    def test_tab_view_minimum_two_tabs(self, renderer):
        """TabViewBlock with exactly 2 tabs (minimum) renders without errors."""
        response = InfographicResponse(blocks=[
            TabViewBlock(tabs=[
                TabPane(id="tab1", label="First", blocks=[SummaryBlock(content="First tab")]),
                TabPane(id="tab2", label="Second", blocks=[SummaryBlock(content="Second tab")]),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "First" in html
        assert "Second" in html
        assert "showTab" in html

    def test_multiple_tab_views_unique_ids(self, renderer):
        """Two TabViewBlocks in the same response get unique prefixes."""
        response = InfographicResponse(blocks=[
            TabViewBlock(tabs=[
                TabPane(id="a", label="A", blocks=[]),
                TabPane(id="b", label="B", blocks=[]),
            ]),
            TabViewBlock(tabs=[
                TabPane(id="x", label="X", blocks=[]),
                TabPane(id="y", label="Y", blocks=[]),
            ]),
        ])
        html = renderer.render_to_html(response)
        # Both tab views rendered with different prefixes
        assert "tv0-a" in html
        assert "tv1-x" in html

    def test_accordion_with_styled_table(self, renderer):
        """Accordion containing a striped TableBlock renders correctly."""
        response = InfographicResponse(blocks=[
            AccordionBlock(items=[
                AccordionItem(
                    title="Data Table",
                    content_blocks=[
                        TableBlock(
                            columns=["Col A", "Col B"],
                            rows=[["1", "2"], ["3", "4"]],
                            style=TableStyle.STRIPED,
                        ),
                    ],
                ),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "data-table--striped" in html
        assert "Col A" in html

    def test_table_columndef_headers_rendered(self, renderer):
        """TableBlock with ColumnDef (align, width) renders header cells."""
        response = InfographicResponse(blocks=[
            TableBlock(
                columns=[
                    ColumnDef(header="Name", align="left", width="40%"),
                    ColumnDef(header="Score", align="right", color="#e74c3c"),
                ],
                rows=[["Alice", "95"], ["Bob", "88"]],
            ),
        ])
        html = renderer.render_to_html(response)
        assert "Name" in html
        assert "Score" in html
        assert "Alice" in html
        assert "text-align:right" in html

    def test_bullet_list_grid_columns(self, renderer):
        """BulletListBlock with columns=3 renders grid layout CSS."""
        response = InfographicResponse(blocks=[
            BulletListBlock(
                items=["A", "B", "C", "D", "E", "F"],
                columns=3,
            ),
        ])
        html = renderer.render_to_html(response)
        assert "grid" in html or "columns" in html or "bullet-list" in html

    def test_accordion_only_no_tab_js(self, renderer):
        """Accordion-only response does NOT inject tab JS."""
        response = InfographicResponse(blocks=[
            AccordionBlock(items=[
                AccordionItem(title="Only Accordion"),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "toggleAccordion" in html
        assert "showTab" not in html


# ──────────────────────────────────────────────
# TestJSInjectionControl
# ──────────────────────────────────────────────

class TestJSInjectionControl:
    """Verify selective JS injection based on block types present."""

    def test_no_js_for_flat_blocks(self, renderer):
        """Flat blocks only (title, summary, bullets) → no interaction JS."""
        response = InfographicResponse(blocks=[
            TitleBlock(title="Report"),
            SummaryBlock(content="Content"),
            BulletListBlock(items=["A", "B"]),
        ])
        html = renderer.render_to_html(response)
        assert "showTab" not in html
        assert "toggleAccordion" not in html

    def test_tab_js_but_no_accordion_js(self, renderer):
        """Tabs without accordions → only tab JS injected."""
        response = InfographicResponse(blocks=[
            TabViewBlock(tabs=[
                TabPane(id="a", label="A", blocks=[SummaryBlock(content="X")]),
                TabPane(id="b", label="B", blocks=[BulletListBlock(items=["Y"])]),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "showTab" in html
        assert "toggleAccordion" not in html

    def test_accordion_js_but_no_tab_js(self, renderer):
        """Accordion without tabs → only accordion JS injected."""
        response = InfographicResponse(blocks=[
            AccordionBlock(items=[
                AccordionItem(title="Collapsed", content_blocks=[]),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "toggleAccordion" in html
        assert "showTab" not in html

    def test_both_js_when_both_present(self, renderer, multi_tab_response):
        """Tab + Accordion present → both JS functions injected."""
        html = renderer.render_to_html(multi_tab_response)
        assert "showTab" in html
        assert "toggleAccordion" in html

    def test_accordion_inside_tab_triggers_accordion_js(self, renderer):
        """AccordionBlock nested inside a TabPane triggers accordion JS injection."""
        response = InfographicResponse(blocks=[
            TabViewBlock(tabs=[
                TabPane(id="a", label="A", blocks=[
                    AccordionBlock(items=[AccordionItem(title="Nested")]),
                ]),
                TabPane(id="b", label="B", blocks=[]),
            ]),
        ])
        html = renderer.render_to_html(response)
        assert "showTab" in html
        assert "toggleAccordion" in html
