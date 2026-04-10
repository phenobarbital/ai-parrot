# TASK-648: Infographic HTML Output Tests

**Feature**: infographic-html-output
**Spec**: `sdd/specs/infographic-html-output.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-644, TASK-645, TASK-646, TASK-647
**Assigned-to**: unassigned

---

## Context

> Implements Module 5 from the spec. Comprehensive test suite covering all
> components of the infographic HTML output feature: theme system, block
> renderers, ECharts mapping, content negotiation, and full round-trip rendering.
> Individual tasks include inline test specs, but this task creates the
> consolidated, production-quality test file.

---

## Scope

- Create `tests/test_infographic_html.py` with comprehensive tests:
  - **Theme tests**: ThemeConfig defaults, custom values, to_css_variables(),
    ThemeRegistry built-ins, custom registration, unknown theme error.
  - **Block renderer tests**: One test per block type verifying correct HTML output.
    Test XSS prevention, markdown rendering, empty/missing fields.
  - **ECharts tests**: Option generation for each ChartType, series colors,
    stacked mode, legend, axis labels. Verify inline JS in document.
  - **Document structure tests**: Full HTML5 document, doctype, CSS variables,
    responsive breakpoints, print styles.
  - **Content negotiation tests**: Accept header routing (text/html default,
    application/json returns JSON).
  - **Edge case tests**: Empty blocks, unknown block types, missing optional fields,
    very long text content, special characters in all text fields.
  - **Integration test**: `render_to_html()` with a complete InfographicResponse
    containing all 12 block types, verify output is valid HTML.
- Create fixtures for reusable test data (sample responses, themes, individual blocks).
- Verify reference HTML patterns: rendered output structure should match the patterns
  in `docs/infographic-1775694709159.html` (class names, element hierarchy).

**NOT in scope**:
- Visual regression testing (screenshot comparison)
- Performance benchmarks
- LLM integration tests (require live LLM)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_infographic_html.py` | CREATE | Comprehensive test suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Theme system (created by TASK-644)
from parrot.models.infographic import ThemeConfig, ThemeRegistry, theme_registry

# Block models (verified: infographic.py)
from parrot.models.infographic import (
    InfographicResponse, InfographicBlock, BlockType, ChartType,
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, ChartDataSeries,
    BulletListBlock, TableBlock, ImageBlock, QuoteBlock, CalloutBlock,
    DividerBlock, TimelineBlock, TimelineEvent, ProgressBlock, ProgressItem,
    TrendDirection, CalloutLevel,
)

# HTML renderer (created by TASK-645)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer

# Test framework
import pytest  # verified: installed, used throughout tests/
```

### Does NOT Exist
- ~~`parrot.tests.fixtures.infographic`~~ — no shared fixtures module; create fixtures in test file
- ~~`InfographicHTMLRenderer.validate_html()`~~ — no validation method; test HTML via string assertions

---

## Implementation Notes

### Fixture: All 12 Block Types
```python
@pytest.fixture
def full_infographic_response():
    """InfographicResponse with all 12 block types for integration testing."""
    return InfographicResponse(
        template="executive",
        theme="light",
        blocks=[
            TitleBlock(type="title", title="Full Test Report", subtitle="All Block Types",
                      author="Test", date="2026-04-10"),
            HeroCardBlock(type="hero_card", label="Revenue", value="$1.2M",
                         trend=TrendDirection.UP, trend_value="+15%", color="#10b981"),
            HeroCardBlock(type="hero_card", label="Users", value="50K",
                         trend=TrendDirection.DOWN, trend_value="-3%"),
            HeroCardBlock(type="hero_card", label="NPS", value="72",
                         trend=TrendDirection.FLAT),
            SummaryBlock(type="summary", title="Executive Summary",
                        content="**Strong** quarter with *notable* growth in key metrics."),
            DividerBlock(type="divider", style="gradient"),
            ChartBlock(type="chart", chart_type=ChartType.BAR, title="Quarterly Revenue",
                      labels=["Q1", "Q2", "Q3", "Q4"],
                      series=[ChartDataSeries(name="2025", values=[100, 200, 150, 300])],
                      x_axis_label="Quarter", y_axis_label="Revenue ($K)"),
            ChartBlock(type="chart", chart_type=ChartType.PIE, title="Market Share",
                      labels=["Product A", "Product B", "Product C"],
                      series=[ChartDataSeries(name="Share", values=[45, 30, 25])]),
            TableBlock(type="table", title="Top Performers",
                      columns=["Name", "Revenue", "Growth"],
                      rows=[["Alpha", "$500K", "+20%"], ["Beta", "$400K", "+15%"]],
                      highlight_first_column=True),
            BulletListBlock(type="bullet_list", title="Key Recommendations",
                           items=["Expand into new markets", "Increase R&D investment",
                                  "Optimize supply chain"], ordered=True),
            CalloutBlock(type="callout", level=CalloutLevel.SUCCESS,
                        title="Milestone", content="Achieved 100K customer milestone"),
            ImageBlock(type="image", url="https://example.com/chart.png",
                      alt="Overview chart", caption="Figure 1: Overview"),
            QuoteBlock(type="quote", text="Innovation distinguishes leaders from followers.",
                      author="Steve Jobs"),
            TimelineBlock(type="timeline", title="Project Milestones", events=[
                TimelineEvent(date="2026-01", title="Phase 1", description="Research"),
                TimelineEvent(date="2026-03", title="Phase 2", description="Development"),
                TimelineEvent(date="2026-06", title="Phase 3", description="Launch"),
            ]),
            ProgressBlock(type="progress", title="OKR Progress", items=[
                ProgressItem(label="Revenue Target", value=75, target=100, color="#10b981"),
                ProgressItem(label="User Growth", value=90, color="#6366f1"),
            ]),
        ],
    )
```

### Key Test Patterns
- Use `renderer.render_to_html(response)` for full document tests
- Use `renderer._render_<type>(block)` for individual block tests
- Assert HTML structure via string containment (`assert "<table" in html`)
- Assert XSS via `assert "<script>" not in html` for user content
- Assert CSS variables via `assert "--primary:" in html`

### Key Constraints
- Tests must be runnable with `pytest tests/test_infographic_html.py -v`
- No external dependencies beyond what's already installed
- No network calls (all data is fixture-based)
- Use `pytest.mark.asyncio` for async tests if needed

---

## Acceptance Criteria

- [ ] Test file runs successfully: `pytest tests/test_infographic_html.py -v`
- [ ] Coverage: every block type has at least one dedicated test
- [ ] Coverage: every ChartType has at least one ECharts mapping test
- [ ] XSS prevention tested for title, summary, table cells, chart labels
- [ ] Edge cases tested: empty blocks, unknown type, missing optional fields
- [ ] Full integration test with all 12 block types produces valid HTML
- [ ] Theme tests cover built-in themes and custom registration
- [ ] Content negotiation tests verify HTML default and JSON override

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/infographic-html-output.spec.md`
2. **Check dependencies** — verify TASK-644 through TASK-647 are in `tasks/completed/`
3. **Read the implementation** — review the actual code in `infographic_html.py` and
   `infographic.py` to see exact method names and signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the test file following the scope above
6. **Run tests**: `pytest tests/test_infographic_html.py -v`
7. **Fix any failures** in the implementation code if tests reveal bugs
8. **Move this file** to `tasks/completed/TASK-648-tests.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
