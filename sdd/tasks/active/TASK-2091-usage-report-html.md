# TASK-2091: Self-contained HTML usage report

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2090
**Assigned-to**: unassigned

---

## Context

Implements **Module 7b** of the spec — the human-facing half of the usage report.
`render_usage_markdown` (TASK-2090) covers the terminal and the run bundle; this
task adds `render_usage_html`, producing the standalone artifact an operator can
open in a browser to compare a MiniMax dev seat against an Opus 5 reviewer at a
glance.

Both renderers consume the same `UsageReport`, which is what guarantees the two
views cannot disagree.

---

## Scope

- Implement `render_usage_html(report: UsageReport) -> str` in
  `dev_loop/usage_report.py`.
- Write `usage.html` alongside `usage.json` at run end.
- Render: one row per agent seat (seat, backend, model, rounds, input/output/
  cache tokens, duration), a run-totals row, and a per-node timeline.
- The page must be **fully self-contained**: inline CSS, no external stylesheet,
  script, font or image. No CDN references of any kind.
- Honour the same no-fake-zeros rule — unreported values render `—`.
- Escape all interpolated values (model ids and seat names reach the page as
  data).
- Write unit tests.

**NOT in scope**: the `UsageReport` model, `build_usage_report`, `usage.json` or
the markdown renderer (all TASK-2090); charts or JS interactivity (a static
table is sufficient); any pricing/cost display.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` | MODIFY | Add `render_usage_html` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py` | MODIFY | Write `usage.html` beside `usage.json` |
| `packages/ai-parrot/tests/flows/dev_loop/test_usage_report_html.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from html import escape          # stdlib — use for ALL interpolated values
from parrot.flows.dev_loop.usage_report import AgentUsage, UsageReport  # TASK-2090
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py  (created by TASK-2090)
class AgentUsage(_Frozen):
    seat: str
    node_id: str
    backend: str
    model: str
    rounds: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    duration_seconds: Optional[float] = None

class UsageReport(_Frozen):
    run_id: str
    generated_at: float
    agents: List[AgentUsage]
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None
    total_rounds: Optional[int] = None

def render_usage_markdown(report: UsageReport) -> str: ...   # the sibling renderer

# packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py
def _format_tokens(input_tokens, output_tokens) -> str: ...  # line 365
# returns "—" when both are None — the no-fake-zeros contract (RunTotals docstring, lines 120-123)
```

### Does NOT Exist

- ~~`render_usage_html`~~ — this task creates it
- ~~A templating engine in this package~~ — there is no Jinja2 dependency for dev_loop output; build the HTML with f-strings/`str.join`, do not add a dependency
- ~~Any existing HTML renderer in `dev_loop/`~~ — `run_bundle.py` renders markdown only
- ~~A CSS or asset file to link~~ — inline everything; there is no static-asset pipeline here
- ~~Charting libraries~~ — no `plotly`/`chart.js`; a static table is the deliverable

---

## Implementation Notes

### Pattern to Follow

```python
def render_usage_html(report: UsageReport) -> str:
    """Render a fully self-contained HTML usage report.

    The page inlines all styling and references no external asset, so it can be
    opened from disk or attached to a PR comment without breaking.
    """
    rows = "\n".join(_html_row(a) for a in report.agents)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Dev-loop usage — {escape(report.run_id)}</title>
<style>/* inline only */</style>
</head><body>
<table>{rows}</table>
</body></html>"""
```

### Key Constraints

- **Self-contained is a hard requirement** and is an acceptance criterion with a
  test: no `src=`, `href=` to any external host, no `@import`, no CDN.
- `escape()` every interpolated value. Model ids and seat names are data.
- Unreported values render `—`, matching the markdown renderer exactly.
- Prefer semantic, minimal HTML — a table plus a totals row. No JS required.
- Keep the two renderers consistent: if a column exists in markdown it should
  exist in HTML, and vice versa.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py:365-420` — the markdown
  table this mirrors, and the `—` convention
- `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` — the sibling
  renderer created by TASK-2090; match its column set

---

## Acceptance Criteria

- [ ] `render_usage_html(report)` returns a complete HTML document
      (`<!doctype html>` … `</html>`)
- [ ] **The output contains no external references** — no `http://`, `https://`,
      `//cdn`, or `@import` in `src`/`href`/CSS
- [ ] One row per agent seat with seat, backend, model, rounds, tokens, duration
- [ ] A run-totals row is present
- [ ] Unreported values render `—`, never `0`
- [ ] All interpolated values are HTML-escaped (verified with a hostile model id)
- [ ] `usage.html` is written beside `usage.json` at run end
- [ ] Column set matches `render_usage_markdown`
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_usage_report_html.py -v` passes
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_usage_report_html.py
import re
import pytest
from parrot.flows.dev_loop.usage_report import (
    AgentUsage, UsageReport, render_usage_html,
)


@pytest.fixture
def report():
    return UsageReport(
        run_id="run-1", generated_at=0.0,
        agents=[
            AgentUsage(seat="dev-agent-1", node_id="development", backend="nova",
                       model="minimax.minimax-m2.5", rounds=7,
                       input_tokens=1000, output_tokens=250),
            AgentUsage(seat="adversarial", node_id="qa", backend="nova",
                       model="us.anthropic.claude-opus-5", rounds=1),
        ],
    )


class TestSelfContained:
    def test_no_external_references(self, report):
        html = render_usage_html(report)
        assert "http://" not in html and "https://" not in html
        assert "@import" not in html and "//cdn" not in html

    def test_is_complete_document(self, report):
        html = render_usage_html(report)
        assert html.lstrip().lower().startswith("<!doctype html>")
        assert html.rstrip().endswith("</html>")


class TestContent:
    def test_row_per_agent(self, report):
        html = render_usage_html(report)
        assert "dev-agent-1" in html and "adversarial" in html

    def test_dash_for_unreported(self, report):
        html = render_usage_html(report)
        assert "—" in html
        assert ">0<" not in html, "must never fabricate zeros"

    def test_escapes_hostile_values(self):
        rep = UsageReport(run_id="r", generated_at=0.0, agents=[
            AgentUsage(seat="<script>alert(1)</script>", node_id="n",
                       backend="nova", model="m"),
        ])
        html = render_usage_html(rep)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_no_pricing(self, report):
        assert "$" not in render_usage_html(report)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (Module 7, §5 Acceptance Criteria)
2. **Check dependencies** — verify TASK-2090 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `AgentUsage`/`UsageReport`'s final field set as TASK-2090 shipped it
   - Read `render_usage_markdown` so the column sets match
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2091-usage-report-html.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
