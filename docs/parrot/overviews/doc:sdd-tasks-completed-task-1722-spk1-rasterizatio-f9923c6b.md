---
type: Wiki Overview
title: 'TASK-1722: SPK-1: rasterization backend spike (weasyprint vs playwright)'
id: doc:sdd-tasks-completed-task-1722-spk1-rasterization-spike-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 0a** of the spec (§3, "SPK-1 rasterization spike").
  Spike gates were waived and embedded as early feature tasks (spec §8): before the
  pdf renderer (Module 5) hardens, we need evidence-based confirmation that **weasyprint**
  is the right default PDF backend vers'
relates_to:
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.outputs.a2ui.models
  rel: mentions
---

# TASK-1722: SPK-1: rasterization backend spike (weasyprint vs playwright)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1720
**Assigned-to**: unassigned

---

## Context

Implements **Module 0a** of the spec (§3, "SPK-1 rasterization spike"). Spike gates were waived and embedded as early feature tasks (spec §8): before the pdf renderer (Module 5) hardens, we need evidence-based confirmation that **weasyprint** is the right default PDF backend versus **playwright** for baked A2UI surfaces. Weasyprint is the presumed default precisely because it is deterministic and runs no JS — which means ECharts content must pre-render to static SVG as a companion constraint (spec §7 risks). This task produces evidence and a recorded decision, NOT shipped code.

---

## Scope

- Build ONE realistic infographic-like `CreateSurface` envelope fixture (hand-authored JSON using the TASK-1720 models; exercising chart-like + KPI-like + text content with resolved/inlined data — no catalog needed since Module 2/3 may not exist yet).
- Write throwaway spike scripts that take the fixture through a manual HTML materialization and rasterize it to **PDF and email-safe HTML** through BOTH backends:
  - `weasyprint` (already a dependency: `packages/ai-parrot/pyproject.toml:134`, `weasyprint==68.0`)
  - `playwright` (already a dependency: `packages/ai-parrot/pyproject.toml:225`, `playwright==1.52.0`)
- Measure per backend: **output size**, **wall-clock latency**, and **determinism** — 3 runs each, byte-compare the outputs (`sha256sum`); record whether repeated runs are byte-identical.
- For the weasyprint path, demonstrate the ECharts-to-static-SVG pre-render constraint: chart content in the fixture must be a static SVG (weasyprint executes no JS); note in the evidence what this implies for the Module 5 echarts renderer.
- Write all evidence to `artifacts/spikes/spk1-rasterization/`: the fixture, generated PDFs/HTML, a `results.md` with the measurement table and the backend decision + rationale.
- Record the decision: fill the spike outcome into the **Completion Note** of this task AND check off the spec §8 open-question checkbox "SPK-1 outcome — confirm weasyprint default or split per artifact class" (edit `sdd/specs/a2ui-implementation.spec.md`, mark resolved with a one-line outcome).

**NOT in scope**:
- Shipping ANY spike code into `packages/*/src/` — spike code is throwaway and lives only under `artifacts/spikes/spk1-rasterization/`.
- The real pdf renderer (Module 5 task) — it consumes this decision.
- The baking pass / JSON Pointer resolution (Module 6) — the fixture uses inlined data.
- Adding or upgrading any dependency.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/spikes/spk1-rasterization/fixture_infographic_envelope.json` | CREATE | Realistic infographic-like CreateSurface envelope (inlined data) |
| `artifacts/spikes/spk1-rasterization/spike_weasyprint.py` | CREATE | Throwaway: envelope → HTML → PDF/email-HTML via weasyprint, timed, 3 runs |
| `artifacts/spikes/spk1-rasterization/spike_playwright.py` | CREATE | Throwaway: envelope → HTML → PDF via playwright (chromium), timed, 3 runs |
| `artifacts/spikes/spk1-rasterization/results.md` | CREATE | Measurement table (size/latency/determinism) + backend decision |
| `artifacts/spikes/spk1-rasterization/outputs/` | CREATE | Generated PDFs/HTML + checksums per run |
| `sdd/specs/a2ui-implementation.spec.md` | MODIFY | Check the §8 SPK-1 checkbox with a one-line outcome |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.models import CreateSurface  # created by TASK-1720 — verify exact export names before use
# weasyprint==68.0  — verified in packages/ai-parrot/pyproject.toml:134 (pdf-related extra)
# playwright==1.52.0 — verified in packages/ai-parrot/pyproject.toml:225 (agents extra)
```

### Existing Signatures to Use
```python
# None — spike code is standalone throwaway. It may load the envelope with the
# TASK-1720 serialization layer to keep the fixture honest, but must not touch
# any other parrot subsystem.
```

### Does NOT Exist
- ~~A pdf A2UI renderer~~ — `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/` does not exist yet (Module 5 creates it; this spike informs it).
- ~~The baking pass / `RenderedArtifact`~~ — Module 6; fixture data must be inlined.
- ~~The v1 catalog components~~ — Module 3; do NOT block on them, the fixture is envelope-shaped JSON only.

### Environment Notes
- Run everything with the venv active: `source .venv/bin/activate`. Verify both backends import before measuring (`python -c "import weasyprint"`, `python -c "from playwright.sync_api import sync_playwright"`); if playwright browsers are missing, `playwright install chromium` (note the install in results.md).
- Spec §7 risk to verify empirically: **playwright nondeterminism in containers** — this is exactly what the byte-compare measures.

---

## Implementation Notes

### Pattern to Follow
No production pattern applies — this is a spike. Keep each script self-contained: load fixture → build one HTML document (inline CSS, static SVG for chart content) → rasterize 3× → print a small metrics table (size bytes, latency ms, sha256 per run).

### Key Constraints
- **Throwaway code**: no imports of spike code from anywhere; no tests required; ruff/pytest acceptance applies only to NOT having broken anything else.
- Same input HTML must be fed to both backends so size/latency/determinism are comparable.
- Determinism check is byte-level: 3 runs per backend per output format, compare sha256. If a backend embeds timestamps (PDF creation date), record it and note whether it is neutralizable via backend options — that nuance IS the spike's value.
- Email-safe HTML output: single self-contained document (inline styles, no external fetches, no `<script>`).
- The decision recorded must answer spec §8: "confirm weasyprint default or split per artifact class" — i.e. either "weasyprint for all static artifact classes" or an explicit split (e.g. weasyprint for infographic/report, playwright for X because Y).

### References in Codebase
- `sdd/specs/a2ui-implementation.spec.md` §7 "Known Risks / Gotchas" — playwright nondeterminism + ECharts→static-SVG companion requirement.
- `packages/ai-parrot/pyproject.toml:134` / `:225` — pinned backend versions to report in results.md.

---

## Acceptance Criteria

- [ ] Evidence directory `artifacts/spikes/spk1-rasterization/` contains fixture, both spike scripts, generated outputs with checksums, and `results.md`.
- [ ] `results.md` has a measurement table: backend × output-format × {size, latency, byte-identical across 3 runs yes/no}.
- [ ] ECharts/static-SVG constraint for weasyprint explicitly documented in `results.md`.
- [ ] Backend decision recorded in `results.md` AND in this task's Completion Note.
- [ ] Spec §8 SPK-1 checkbox updated to resolved with a one-line outcome.
- [ ] No spike code under `packages/*/src/`; no dependency changes.
- [ ] Existing test suite untouched and green: `pytest packages/ai-parrot/tests/outputs/ -v`
- [ ] No linting errors introduced in package code: `ruff check packages/ai-parrot/src/parrot/outputs/` (spike scripts under `artifacts/` are exempt)

---

## Test Specification

> Spike task — no shipped tests. The scripts themselves are the experiment.
> The scaffold below is the self-check the spike scripts must perform and report.

```python
# artifacts/spikes/spk1-rasterization/spike_weasyprint.py (self-check outline, throwaway)

def check_fixture_parses_with_a2ui_models():
    """Fixture loads through the TASK-1720 serialization layer (keeps the envelope honest)."""
    ...

def check_three_run_determinism():
    """3 PDF runs produced; sha256 comparison result recorded (byte-identical or not)."""
    ...

def check_email_html_is_self_contained():
    """Email-safe HTML output has no <script> tags and no external resource references."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1722-spk1-rasterization-spike.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — for this spike the note MUST state the backend decision

---

## Completion Note

*(Agent fills this in when done — MUST include the rasterization backend decision and the headline numbers)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Backend decision**: **weasyprint confirmed as the default for ALL static artifact
classes.** playwright is NOT adopted as a per-artifact-class split in v1 (kept as a
documented fallback for any future JS-only artifact class).

**Headline numbers** (3 runs each, same materialized HTML, static-SVG chart):
- weasyprint 69.0 → PDF **8,447 bytes**, ~100–140 ms, **byte-identical across 3 runs**.
- playwright 1.52.0 (chromium headless-shell 136) → PDF **30,299 bytes**, ~7–8 ms per
  `page.pdf()` (excludes one-time browser launch), **byte-identical across 3 runs in
  this environment**.
- Decision drivers: weasyprint is intrinsically deterministic (no JS/browser/font
  variance), ~3.6× smaller output, and needs no ~100 MB browser in the deploy image.

**ECharts pre-render implication**: weasyprint runs no JS, so chart content must
pre-render to **static SVG** for the PDF path (fixture used a hand-authored SVG bar
chart and rasterized cleanly). Carried into TASK-1732: rasterize the SSR-HTML output
with charts as static SVG.

Evidence: `artifacts/spikes/spk1-rasterization/` (fixture, both spike scripts, 6 PDFs +
email HTML, `outputs/checksums.sha256`, `results.md`). Spec §8 SPK-1 checkbox marked
resolved. Both backends actually executed (chromium installed via `playwright install
chromium`). Existing a2ui suite green (70 passed).

**Deviations from spec**: spike evidence lives under `artifacts/` which is globally
gitignored, so it was committed with `git add -f` (a stray `__pycache__/*.pyc` that
slipped in was subsequently untracked). No package `src/` code or dependencies changed.
