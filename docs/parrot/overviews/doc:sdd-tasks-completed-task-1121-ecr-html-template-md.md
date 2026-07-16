---
type: Wiki Overview
title: 'TASK-1121: Port `generate_ecr_report.js` to Jinja2 template'
id: doc:sdd-tasks-completed-task-1121-ecr-html-template-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** of the spec (`sdd/specs/cloudsploit-ecr.spec.md`
  §3).
---

# TASK-1121: Port `generate_ecr_report.js` to Jinja2 template

**Feature**: FEAT-165 — CloudSploit ECR Image-Scan Collector & Interactive Report
**Spec**: `sdd/specs/cloudsploit-ecr.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (`sdd/specs/cloudsploit-ecr.spec.md` §3).

The user's `generate_ecr_report.js` produces a self-contained HTML
vulnerability report with severity badges, expand/collapse cards, per-package
CVE grouping, search input, and severity filters. This task ports that
output to a Jinja2 template; the rendering Python code lives in TASK-1122.

All CSS and JS are inlined so the file works offline with no external
requests. Browser-targeted — not safe to pass through `xhtml2pdf`.

The full JS source is in the proposal at
`sdd/state/FEAT-165/source.md` (under `## Script 2`).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/templates/ecr_scan_report.html`.
- The template renders an `EcrCollectionResult` model dump exposed as a
  Jinja2 context variable. Variables provided by the renderer (TASK-1122):
  - `generated_at`: ISO datetime string
  - `region`: str
  - `total_counts`: dict[str, int] (CRITICAL/HIGH/MEDIUM/LOW totals)
  - `repos_sorted`: list of repo dicts (already sorted by the renderer —
    template does NOT re-sort)
  - Each repo dict: `{repo, tag, scan_time_formatted, counts,
    total_findings, pkg_groups: [{pkg, ver, worst_severity, cves: [...]}]}`
- Match the JS output's features:
  - Hero header: title, region, generated_at, repo count.
  - Summary cards: Repos / Critical / High / Medium / Low totals.
  - Controls bar: search input + severity filter buttons + expand/collapse-all.
  - Per-repo cards:
    - Left border colour by worst severity (CRITICAL=red, HIGH=orange, MEDIUM=yellow, LOW=grey).
    - Header: repo name, tag, severity badges + counts, scan date, chevron.
    - Body: per-package filter bar, package blocks each with a CVE table
      (Severity | CVE | Description (≤180 chars) | Fix | CVSS).
    - Auto-expand when `counts.CRITICAL + counts.HIGH > 0`.
- Inline CSS exactly matching the JS aesthetic (gradients, monospace for
  package names, badge styles).
- Inline JS for `toggleRepo`, `togglePkg`, `filterPkgs`, `filterRepos`,
  `applyFilters`, `toggleAll` — copy verbatim from the JS, just emit it
  inside a `<script>` block.
- Use Jinja2 `{{ ... }}` and `{% for %}` to drive the data.
- Use the existing `autoescape=True` env (reports.py:31) — special chars
  in CVE descriptions get HTML-escaped automatically.

**NOT in scope**: the Python renderer that prepares the context
(TASK-1122), the data model (TASK-1118).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/templates/ecr_scan_report.html` | CREATE | Jinja2 template |
| `packages/ai-parrot-tools/tests/cloudsploit/fixtures/ecr_scan_report.expected.html` | CREATE (optional) | Small golden output for smoke test in TASK-1122 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
This task touches only an HTML file. No Python imports.

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py
# The Jinja2 Environment that will load this template:
self.env = Environment(
    loader=FileSystemLoader(str(template_dir)),
    autoescape=True,
)
# Verified at: cloudsploit/reports.py:28-32
# template_dir = Path(__file__).parent / "templates"
# Adjacent existing templates: scan_report.html, comparison_report.html
```

### Does NOT Exist
- ~~`{% include 'macros/badge.html' %}`~~ — the templates directory has no
  macros subdirectory. Inline any macros at the top of this file.
- ~~Tailwind / Bootstrap classes~~ — keep CSS inline and self-contained.
- ~~External `<script src="...">` or `<link rel="stylesheet">`~~ — must be
  fully offline.

---

## Implementation Notes

### Pattern to Follow

Reference adjacent template: `cloudsploit/templates/scan_report.html`
(`head -20` shows the structure — inline `<style>` blocks, `{{ summary.* }}`
context, plain Helvetica fonts). Your template uses richer CSS but the
overall shape is the same.

### Jinja2 differences from JS template literals

The JS uses string-template interpolation (\`${var}\`). In Jinja2:
- `${var}` → `{{ var }}`
- `${var || 'fallback'}` → `{{ var or 'fallback' }}`
- `array.map(x => ...).join('')` → `{% for x in array %}...{% endfor %}`
- `array.filter(...).map(...).join('')` → `{% for x in array if condition %}...{% endfor %}`
- Ternary `cond ? a : b` → `{% if cond %}a{% else %}b{% endif %}` or `{{ a if cond else b }}`

The renderer in TASK-1122 will pre-compute anything that's awkward in
Jinja2 (sorting, slicing descriptions to 180 chars, picking worst-severity
per package). The template should NOT contain business logic — just
iteration and conditionals.

### Pre-computed fields the renderer passes

The Python renderer (TASK-1122) will pass these conveniences so the
template stays simple:

- `description_short`: pre-truncated to 180 chars with ellipsis.
- `scan_time_formatted`: locale-formatted string (or `"N/A"`).
- `repo.has_critical / has_high / has_medium / has_low`: booleans for the
  `data-has-*` attrs on `.repo-card`.
- `repo.repo_open`: bool, true when CRITICAL+HIGH > 0.
- `pkg.worst_severity`: pre-computed enum value.
- `pkg.pkg_open`: bool, true when worst is CRITICAL or HIGH.
- `cve.severity_color_bg / severity_color_text`: pre-resolved hex colours.

### Key Constraints

- `autoescape=True` is already on — do NOT hand-escape `{{ description }}`.
- Output must be valid HTML5 and open in modern browsers.
- File size budget: target < 80 KB for the template itself (rendered
  output will be larger; that's fine).
- Use double-quoted attribute values throughout.
- Indent with 2 spaces inside `<style>` and `<script>` blocks for
  readability.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/templates/scan_report.html`
  — adjacent template, same style of inline CSS.
- `sdd/state/FEAT-165/source.md` — the full JS source under "## Script 2"
  with the exact HTML/CSS/JS to port.

---

## Acceptance Criteria

- [ ] Template file exists at the expected path.
- [ ] Rendering with the renderer in TASK-1122 produces an HTML file that
      opens in Chrome and Firefox with no console errors.
- [ ] No external `<link>` or `<script src=...>` references in the rendered
      output (run `grep -E 'src=|rel="stylesheet"' rendered.html` → 0 hits).
- [ ] Search input filters repo cards client-side (manual smoke test).
- [ ] Severity filter buttons (CRITICAL/HIGH/MEDIUM) hide/show repo cards
      based on `data-has-*` attrs.
- [ ] Per-repo "expand/collapse all" toggle works.
- [ ] Per-package blocks list every CVE in their CVE table.
- [ ] Repos and packages with CRITICAL or HIGH start auto-expanded.
- [ ] `description` text is HTML-escaped (an injected `<script>` in the
      fixture appears literally, NOT executed).
- [ ] No Python imports added by this task.

---

## Test Specification

This task ships an HTML template; the unit test lives in TASK-1122 (which
exercises the renderer using this template). For this task, the smoke test
is manual:

```bash
# After TASK-1122 lands, run:
pytest packages/ai-parrot-tools/tests/cloudsploit/test_ecr_reports.py::test_html_report_renders_with_real_fixtures -v
# Open the generated file in a browser and confirm:
#   - search bar filters live
#   - severity filter buttons work
#   - expand/collapse-all toggles all cards
```

A golden HTML fixture (small, deterministic) MAY be committed at
`tests/cloudsploit/fixtures/ecr_scan_report.expected.html` to anchor a
byte-for-byte snapshot test if TASK-1122's author prefers — optional.

---

## Agent Instructions

1. Read the spec at `sdd/specs/cloudsploit-ecr.spec.md` (§2 Overview, §3 Module 4).
2. Open `sdd/state/FEAT-165/source.md` and locate "## Script 2" — that is the source HTML/CSS/JS to port.
3. Read `cloudsploit/templates/scan_report.html` to learn the existing template style.
4. Create `cloudsploit/templates/ecr_scan_report.html` with the structure described in Implementation Notes.
5. Verify the rendered HTML opens cleanly (you can hand-construct a minimal Python script that loads the env and renders against a dummy context to smoke-test).
6. Move this file to `sdd/tasks/completed/`.
7. Update `sdd/tasks/index/cloudsploit-ecr.json` task status to `done`.
8. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
