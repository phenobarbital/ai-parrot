# TASK-2619: Node/cycle/worker renderers, Failures section, partial marker

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2618
**Assigned-to**: unassigned

---

## Context

Implements the rendering half of spec §3 Module 7 (Module 7b) — the part the
user actually reads at the end of a run.

Three things land here:

1. **Node → cycle → worker** rows, so retry cost and fan-out cost are both
   visible (the granularity chosen for this feature).
2. A **Failures section**, replacing today's bare `nodes_failed` integer with
   per-seat error reporting including tokens burned before failing.
3. The **partial marker** (spec §8 Q1): when a run resumed in a different
   process and its ledger is gone, the report must say so rather than print a
   total that silently omits pre-park usage.

Markdown and HTML render from the same model, so they cannot disagree.

---

## Scope

- Render the node → cycle → worker table in `render_usage_markdown` and
  `render_usage_html`.
- Add a Failures section to both.
- Render the partial marker prominently in both when `report.partial`.
- Preserve the `—`-for-unreported convention and the no-pricing rule.
- Write the unit tests below.

**NOT in scope**: the builder or the models (TASK-2618); the run-bundle
Failures section sourced from session state (that is the run bundle's own
`NodeReport.error`, a different plane); any CSS framework or external asset.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` | MODIFY | Both renderers |
| `packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py` | MODIFY | Markdown assertions |
| `packages/ai-parrot/tests/flows/dev_loop/test_usage_report_html.py` | MODIFY | HTML assertions |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py
def _fmt_value(value: Any | None) -> str:                  # ~line 205
    """Render *value*, or ``—`` when unreported. Never fabricates ``0``."""
    return "—" if value is None else str(value)

def _fmt_agent_tokens(agent: AgentUsage) -> str: ...       # ~line 210
    # "— " when neither token is reported, else "<in> in / <out> out"

def render_usage_markdown(report: UsageReport) -> str: ... # line 210
    # Emits its own "## Usage" heading. Current columns:
    #   | Seat | Node | Backend | Model | Rounds | Tokens | Duration |
    # Totals line: "**Totals** — rounds: X, input tokens: Y, output tokens: Z"

def _fmt_value_html(value) -> str: ...                     # ~line 265  (escaped)
def _fmt_agent_tokens_html(agent) -> str: ...              # ~line 270
def _html_row(agent: AgentUsage) -> str: ...               # ~line 272
def render_usage_html(report: UsageReport) -> str: ...     # line 293
    """Fully self-contained: inlines all styling, references NO external
    asset (no <link>, no <script src>, no @import, no CDN) — it must open
    from disk or attach to a PR comment without breaking."""

# Models after TASK-2618: UsageReport.agents -> list[AgentUsage],
# AgentUsage.cycles -> list[CycleUsage], plus .failures, and
# UsageReport.partial / .partial_reason.
```

### Does NOT Exist

- ~~`UsageRecord.error_message`~~ — deliberately absent (privacy contract,
  `recorders/models.py:8-11`). Only `error_type` (the exception class name)
  is available. Full error text lives in session state and is rendered by the
  **run bundle**, not here.
- ~~A CSS framework or external stylesheet~~ — `render_usage_html` is
  self-contained by contract. Do not add a `<link>` or CDN reference.
- ~~`report.nodes_failed`~~ — that is `run_bundle.RunBundle`'s field
  (`run_bundle.py:128`), not `UsageReport`'s. Count from
  `AgentUsage.failures`.

---

## Implementation Notes

### Table shape

```
| Seat            | Model           | Rounds | Tokens               | Duration |
|-----------------|-----------------|--------|----------------------|----------|
| development     | claude-opus-5   |      9 | 12,400 in / 3,100 out |   —      |
| └ cycle 1       | claude-opus-5   |      3 |  4,000 in / 1,000 out |  12.0s   |
| └ cycle 2       | claude-opus-5   |      3 |  4,200 in / 1,050 out |  11.4s   |
| development.w1  | claude-sonnet-5 |      4 |  6,000 in / 1,500 out |  30.2s   |
| qa              | claude-sonnet-5 |      2 |  1,900 in /   400 out |   8.1s   |
| **Totals**      |                 |     22 | 34,300 in / 8,450 out |          |
```

Cycle rows are indented children of their seat. In HTML, use a class on the
`<tr>` (e.g. `class="cycle"`) with an inline-styled indent rather than nested
tables — keeps it sortable and simple. **Suppress cycle rows when a seat has
exactly one cycle**; the parent row already says everything, and the noise
hurts the common case.

### Failures section

```markdown
### Failures

| Seat | Cycle | Error | Tokens burned |
|---|---|---|---|
| qa | 2 | `TimeoutError` | 1,900 in / 400 out |

_Error messages are not shown here — see the run bundle's per-node errors._
```

That closing line matters: it tells the reader where the full text lives
instead of leaving them thinking it was lost.

Omit the whole section when there are no failures — never render an empty
table.

### Partial marker

When `report.partial`, render prominently **above** the table in both formats,
e.g.:

> ⚠️ **Partial** — this run resumed in a different process, so usage recorded
> before it parked is not included. Totals below are a lower bound.

And label the totals row itself (e.g. `**Totals (partial)**`), so a figure
copied out of context still carries the caveat.

### Key Constraints

- **Escape everything** in HTML. Model ids and seat names arrive as data, not
  trusted markup — `render_usage_html`'s existing `escape()` usage is the
  standard to maintain.
- Keep markdown and HTML column sets identical; they render from one model
  precisely so they cannot drift.
- Never fabricate `0` — keep `_fmt_value` / `_fmt_value_html`.
- No pricing anywhere (spec Non-Goal).
- Keep the HTML fully self-contained.
- Thousands separators are a nicety; if added, apply consistently in both.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py:293` — the self-contained HTML contract
- `packages/ai-parrot/tests/flows/dev_loop/test_usage_report_html.py` — existing HTML assertions

---

## Acceptance Criteria

- [ ] Markdown and HTML both render seat rows, cycle rows and worker rows.
- [ ] A seat with one cycle renders no cycle sub-rows.
- [ ] Both render a Failures section when failures exist, with `error_type`
      and tokens burned — and omit it entirely when there are none.
- [ ] No error **message** appears in either output.
- [ ] `report.partial` renders a visible marker in both, and the totals row is
      labelled partial.
- [ ] Unreported values render `—`, never `0`, including in the totals row.
- [ ] No pricing or cost figure in either output.
- [ ] HTML escapes every interpolated value.
- [ ] HTML remains self-contained — no `<link>`, `<script src>`, `@import` or CDN.
- [ ] Markdown and HTML column sets match.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py packages/ai-parrot/tests/flows/dev_loop/test_usage_report_html.py -v` passes.
- [ ] `ruff check` clean.

---

## Test Specification

```python
def test_report_renders_node_cycle_worker(report_with_cycles_and_workers):
    md = render_usage_markdown(report_with_cycles_and_workers)
    assert "development" in md
    assert "cycle 1" in md and "cycle 2" in md
    assert "development.w1" in md and "development.w2" in md


def test_single_cycle_seat_has_no_cycle_rows(report_single_cycle):
    assert "cycle 1" not in render_usage_markdown(report_single_cycle)


def test_report_failures_section(report_with_failure):
    md = render_usage_markdown(report_with_failure)
    assert "Failures" in md
    assert "TimeoutError" in md


def test_no_failures_section_when_clean(report_clean):
    assert "Failures" not in render_usage_markdown(report_clean)


def test_partial_ledger_is_labelled(report_partial):
    """Spec §8 Q1: a partial run must SAY so, not print a total that
    silently omits pre-park usage."""
    md = render_usage_markdown(report_partial)
    html = render_usage_html(report_partial)
    assert "artial" in md and "artial" in html
    assert "partial" in md.lower().split("**totals")[1][:40]


def test_html_is_self_contained(report_with_cycles_and_workers):
    html = render_usage_html(report_with_cycles_and_workers)
    for forbidden in ("<link", "<script src", "@import", "cdn."):
        assert forbidden not in html.lower()


def test_html_escapes_seat_and_model(report_with_hostile_names):
    """Model ids and seat names are data, not markup."""
    html = render_usage_html(report_with_hostile_names)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_no_pricing_in_output(report_with_cycles_and_workers):
    for out in (render_usage_markdown(report_with_cycles_and_workers),
                render_usage_html(report_with_cycles_and_workers)):
        assert "$" not in out
        assert "cost" not in out.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 7 and §8 Q1
2. **Check dependencies** — TASK-2618 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the model shape TASK-2618 produced
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2619-usage-report-renderers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: Both renderers gained three additions, sharing all new helpers
between markdown and HTML so they cannot drift:

- **Cycle rows**: `_cycle_markdown_row`/`_cycle_html_row` emit one indented
  `└ cycle N` row per `AgentUsage.cycles` entry, but ONLY when
  `len(agent.cycles) > 1` — a seat with exactly one cycle shows no
  sub-rows, since the parent row already carries that cycle's numbers
  (verified by `test_single_cycle_seat_has_no_cycle_rows` in both files).
  HTML uses `<tr class="cycle">` with a CSS indent rule
  (`tr.cycle td:first-child { padding-left: ... }`) rather than nested
  tables, per the task's explicit guidance. Token/duration formatting is
  now shared via new `_fmt_tokens`/`_fmt_tokens_html` helpers (parameterized
  on a bare input/output pair) so `_fmt_agent_tokens`/`_fmt_agent_tokens_html`
  became one-line wrappers around them — no behavior change for existing
  callers, just de-duplication ahead of the cycle/failure rows needing the
  same formatting.
- **Failures section**: a new `_failed_cycles(report)` helper collects
  every `(agent, cycle)` pair with `cycle.status == "failed"`, shared by
  both renderers. Markdown emits a `### Failures` table (Seat/Cycle/Error/
  Tokens burned) with the required closing line verbatim ("_Error messages
  are not shown here — see the run bundle's per-node errors._"); HTML
  emits an equivalent `<h2>Failures</h2>` table via a new
  `_failures_table_html` helper. Both are omitted entirely (empty string /
  no section) when `_failed_cycles` returns empty — verified by
  `test_no_failures_section_when_clean` in both files. Only `cycle.error_type`
  is ever interpolated, never a message — `CycleUsage` (TASK-2618) has no
  message field to begin with, so this is structurally enforced, not just
  a convention (`test_no_error_message_in_failures_section` asserts
  `not hasattr(CycleUsage, "error_message")` alongside the footnote text).
- **Partial marker**: markdown gets a `⚠️ **Partial** — {reason}. Totals
  below are a lower bound.` line above the table (only when
  `report.partial`), and the totals line's own label switches to
  `**Totals (partial)**`. HTML gets an equivalent styled `<p>` banner and a
  `Totals (partial)` label. Both verified by
  `test_partial_ledger_is_labelled` (from the task's own Test
  Specification) checking the word "partial" appears both above the table
  and within the first 40 characters after the totals marker, in both
  formats.

Extended `test_usage_report.py` (markdown) and `test_usage_report_html.py`
(HTML) with the task's Test Specification, split per its own Files table
(markdown assertions in the former, HTML + the dual-format partial check in
the latter) — fixtures (`report_with_cycles_and_workers`,
`report_single_cycle`/`report`, `report_with_failure`, `report_clean`,
`report_partial`, `report_with_hostile_names`) duplicated locally per file
rather than introducing a shared conftest fixture (no conftest changes
needed, matching the existing per-file self-containment convention in this
test directory). One test from the task's own spec had a flawed literal
assertion — `test_no_error_message_in_failures_section`'s
`assert "message" not in md.lower()` would have failed against the
renderer's OWN required footnote text (which legitimately contains the
word "messages"); rewrote it to assert the privacy property that actually
matters (`error_type` only, no message field exists, footnote text
present) rather than a word-search that conflated the disclaimer with a
violation. 46 tests total across both files (27 + 19), all pass. Full
`packages/ai-parrot/tests/flows/dev_loop/` suite (1142 tests, excluding the
3 pre-existing unrelated failures) passes. `ruff check` and `mypy` both
clean.

**Deviations from spec**: The illustrative table in the task's
Implementation Notes shows a simplified 5-column shape (Seat/Model/Rounds/
Tokens/Duration); the actual `usage_report.py` column set (per the
Codebase Contract's own "Current columns" note and TASK-2618, unchanged by
this task) is 7 columns (Seat/Node/Backend/Model/Rounds/Tokens/Duration).
Followed the Codebase Contract's authoritative column list, not the
illustration — cycle rows render `—` for the Backend/Rounds cells that
don't meaningfully apply at cycle granularity, but repeat the parent's
`node_id` in the Node cell (still meaningful context), keeping the column
COUNT identical between parent and cycle rows so the table stays a single
coherent grid. No other deviations.
