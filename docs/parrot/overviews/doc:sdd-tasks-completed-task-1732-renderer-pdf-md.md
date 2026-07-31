---
type: Wiki Overview
title: 'TASK-1732: PDF renderer (SPK-1 backend)'
id: doc:sdd-tasks-completed-task-1732-renderer-pdf-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the **pdf renderer** of **Module 5** (spec §3), closing the G5
  static
relates_to:
- concept: mod:parrot.outputs.a2ui
  rel: mentions
---

# TASK-1732: PDF renderer (SPK-1 backend)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1722, TASK-1729
**Assigned-to**: unassigned

---

## Context

Implements the **pdf renderer** of **Module 5** (spec §3), closing the G5 static
delivery chain: envelope → baked SSR-HTML (TASK-1729) → rasterized PDF →
`send_notification` email attachment. The backend choice is gated by **SPK-1**
(Module 0a, TASK-1722): **weasyprint is the spec default** (§7 — chosen for
determinism; playwright is nondeterministic in containers) **unless SPK-1
evidence says otherwise**.

**MANDATORY FIRST STEP**: read TASK-1722's completion note in
`sdd/tasks/completed/` and the SPK-1 evidence under
`artifacts/spikes/spk1-rasterization/`. If SPK-1 recorded a different backend or
a per-artifact-class split (e.g. playwright for chart-heavy infographics), follow
the recorded decision and note the deviation in this task's completion note.

---

## Scope

- Implement the PDF renderer in
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py`:
  - Subclass core `AbstractA2UIRenderer` (TASK-1723, transitively required by
    TASK-1729); **never** legacy `BaseRenderer` (exec sink).
  - Register as `pdf`; capabilities: `interactive=False`,
    `supports_actions=False`, `supports_updates=False`,
    `output="application/pdf"`.
  - Pipeline: render the envelope through the **SSR-HTML renderer (TASK-1729)**
    to a baked, self-contained HTML document, then rasterize with the SPK-1
    backend — **weasyprint by default** (lazy import, actionable ImportError
    naming `ai-parrot-visualizations[a2ui-pdf]`).
  - **Charts under weasyprint**: weasyprint executes no JavaScript, so Chart
    components must be **pre-rendered to static SVG** before rasterization
    (spec §7: "ECharts→static-SVG pre-render is the required companion if
    weasyprint wins"). Build the SVG deterministically from the baked chart data
    (or per the concrete mechanism SPK-1's evidence recorded) — never by
    executing JS or LLM code.
  - **Playwright fallback**: only if SPK-1 decided a per-artifact-class split,
    implement backend selection keyed on artifact class, playwright behind the
    same lazy-import/actionable-error discipline. If SPK-1 confirmed weasyprint
    outright, do NOT ship playwright code paths.
  - Output: `RenderedArtifact` with `mime_type="application/pdf"`, PDF bytes in
    `content` or a temp-file `path` (attachment-friendly, XOR rule from
    TASK-1728), `surface="pdf"`.
  - `requires_actions` components: inherited from the SSR-HTML stage — deep-link
    URLs render as visible printed links; strip-with-notice otherwise.
- Add the `a2ui-pdf` extra to `packages/ai-parrot-visualizations/pyproject.toml`
  (weasyprint pinned consistently with the host `pdf` extra's `weasyprint==68.0`;
  include playwright ONLY if SPK-1 decided the split).
- Write unit tests + the integration test `test_e2e_envelope_to_pdf_email`
  (spec §4): infographic envelope → bake → PDF `RenderedArtifact` → email
  attachment path with the email/SMTP side mocked (drive
  `send_notification(report=…)` with a mocked provider — do not send anything).

**NOT in scope**:
- SSR-HTML rendering itself (TASK-1729 — consumed here).
- Delivery bridge changes in `parrot/notifications/` (Module 7) — the e2e test
  exercises the existing `send_notification` seam with mocks only.
- Teams Graph upload, Slack public-URL (Module 7).
- Re-running or amending SPK-1 (TASK-1722); this task *consumes* its decision.
- Folium/ECharts/AC renderers (TASK-1730/1731).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py` | CREATE | PDF renderer: SSR-HTML → SPK-1 backend rasterization |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/__init__.py` | MODIFY | Created by TASK-1729 (regular package init) |
| `packages/ai-parrot-visualizations/pyproject.toml` | MODIFY | New `a2ui-pdf` extra (weasyprint; playwright only per SPK-1) |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py` | CREATE | Unit tests (backend selection, SVG pre-render, actionable errors) |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_e2e_pdf_email.py` | CREATE | `test_e2e_envelope_to_pdf_email` (email path mocked) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified references from the actual codebase (re-checked 2026-07-10).
> Do NOT invent imports/attributes not listed here — `grep`/`read` first.

### Verified weasyprint precedent in this monorepo
```python
# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py:101
def _markdown_to_pdf(self, markdown: str, schedule_id: str) -> Path:
    try:
        from weasyprint import HTML          # :103 — lazy import inside the function
    except ImportError as exc:
        raise ImportError(
            "PDF generation requires weasyprint. "   # :106 — actionable, names the extra
            "Install with: uv pip install 'ai-parrot[pdf]'"
        ) from exc
    ...
    HTML(string=html_body).write_pdf(filename)       # md→HTML string→PDF file
# Copy this lazy-import + HTML(string=...).write_pdf(...) shape; your error names
# 'ai-parrot-visualizations[a2ui-pdf]'.
```

### Verified dependency pins
```toml
# packages/ai-parrot/pyproject.toml
#   :133-134  pdf = ["weasyprint==68.0", ...]   # host pin to stay consistent with
#   :225      "playwright==1.52.0"              # inside the agents dependency group
# packages/ai-parrot-visualizations/pyproject.toml — has NO weasyprint/playwright today
```

### Verified delivery seam (for the mocked e2e test)
```python
# packages/ai-parrot/src/parrot/notifications/__init__.py:131 — NotificationMixin
async def send_notification(self, message, recipients,
    provider=..., subject=None, report=None, template=None,
    with_attachments: bool = True, provider_options=None, **kwargs) -> Dict[str, Any]
# Attachment sources: report.files → report.documents → content blocks (type=="file")
# Surface exists on BasicAgent (bots/agent.py:29 — Chatbot + NotificationMixin), NOT AbstractBot.
```

### Forbidden legacy anchor
```python
# packages/ai-parrot/src/parrot/outputs/formats/base.py
class BaseRenderer(ABC):   # :54 — execute_code (:125) → exec(code, ...) (:163). Never used by A2UI.
```

### Interfaces created by dependency tasks (verify against merged code)
```python
# TASK-1729 (satellite): parrot/outputs/a2ui_renderers/ssr_html.py — the baked
#   self-contained HTML producer this renderer consumes (compose via the registry
#   or direct class use — follow whatever seam TASK-1729 shipped).
# TASK-1723 (core): register_a2ui_renderer / AbstractA2UIRenderer /
#   RendererCapabilities (spec §2 sketch; see TASK-1729's contract).
# TASK-1728 (core): RenderedArtifact (content XOR path) / DeepLink.
# TASK-1722 (SPK-1): completion note in sdd/tasks/completed/ + evidence in
#   artifacts/spikes/spk1-rasterization/ — THE backend decision record.
```

### Does NOT Exist
- ~~`parrot/outputs/a2ui_renderers/pdf.py`~~ — created by THIS task.
- ~~`a2ui-pdf` extra~~ — does not exist in any pyproject yet; this task adds it.
- ~~weasyprint or playwright in ai-parrot-visualizations deps~~ — verified absent
  today; add via the new extra only.
- ~~A generic HTML→PDF utility in `parrot/outputs/`~~ — the only in-repo
  precedent is the scheduler's `_markdown_to_pdf` cited above (server package);
  do not import it, copy its shape.
- ~~JS execution under weasyprint~~ — weasyprint renders no JavaScript; anything
  that needs a script tag will silently not draw. Hence the SVG pre-render rule.

---

## Implementation Notes

### Key Constraints
- **Read SPK-1 first** (TASK-1722 completion note + `artifacts/spikes/spk1-rasterization/`).
  The spec default is weasyprint (§7, determinism); only deviate on recorded evidence.
- **G1**: zero `exec`/`eval`; chart SVG pre-render is deterministic data→SVG.
- **Determinism**: same envelope → byte-comparable PDF as far as weasyprint
  allows (fix metadata/dates if weasyprint stamps them — check `write_pdf`
  options); this was the whole point of the weasyprint default.
- weasyprint's blocking `write_pdf` must not block the event loop — run it in an
  executor (`asyncio.to_thread` / loop executor) inside async `render`.
- Temp-file handling: if emitting `path`, create under `tempfile` with a
  meaningful suffix/prefix (see `_write_temp_file` in the scheduler functions
  module) and set `filename` for attachment naming.
- The e2e test mocks the email provider — no network, no SMTP; assert the PDF
  artifact reaches the attachment-extraction seam (`report.files` precedence).
- Async-first; Pydantic v2; Google-style docstrings; module logger, no prints.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py:75-115` —
  the full md→PDF→email-attachment flow this renderer generalizes.
- `packages/ai-parrot/src/parrot/notifications/__init__.py:131` — delivery seam.
- Spec §4 `test_e2e_envelope_to_pdf_email`; spec §7 weasyprint/playwright risk notes.

---

## Acceptance Criteria

- [ ] SPK-1 (TASK-1722) completion note read; backend decision followed and cited
      in this task's completion note
- [ ] Renderer registered as `pdf`; capabilities `interactive=False`,
      `supports_actions=False`, `supports_updates=False`, `output="application/pdf"`
- [ ] Renders via TASK-1729's baked SSR-HTML; charts pre-rendered to static SVG
      when the backend is weasyprint (no JS-dependent content in the PDF path)
- [ ] Returns `RenderedArtifact` with `mime_type="application/pdf"` honoring the
      content XOR path rule
- [ ] Missing backend dep → ImportError naming `ai-parrot-visualizations[a2ui-pdf]`
- [ ] `a2ui-pdf` extra added (weasyprint pinned consistently with host
      `weasyprint==68.0`; playwright only if SPK-1 decided the split)
- [ ] All tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_e2e_pdf_email.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers`
- [ ] No exec/eval: `grep -rn "exec(\|eval(" packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers` returns nothing
- [ ] `BaseRenderer` never imported; `write_pdf` runs off the event loop

---

## Test Specification

> Minimal scaffold — names and intent only; the agent fills in bodies.

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py
class TestPDFRenderer:
    def test_capabilities_declared(self):
        """interactive=False, supports_actions=False, output='application/pdf'."""
        ...

    async def test_renders_baked_ssr_html_to_pdf(self):
        """Golden envelope → SSR-HTML → PDF bytes with %PDF magic; artifact has
        mime_type='application/pdf' and honors content XOR path."""
        ...

    async def test_charts_prerendered_to_svg_under_weasyprint(self):
        """Chart components appear as static SVG in the intermediate HTML handed
        to weasyprint (no <script>-dependent chart content survives)."""
        ...

    def test_missing_backend_actionable_error(self):
        """Without the backend installed, render raises ImportError naming
        ai-parrot-visualizations[a2ui-pdf]."""
        ...

    async def test_render_does_not_block_event_loop(self):
        """write_pdf executes in an executor/thread, not directly on the loop."""
        ...


# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_e2e_pdf_email.py
async def test_e2e_envelope_to_pdf_email():
    """Spec §4: infographic envelope → bake → PDF RenderedArtifact →
    send_notification(report=...) attachment path with the email provider mocked;
    the PDF surfaces through the report.files extraction seam."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
   (TASK-1722's completion note is a REQUIRED input, not just a gate)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index (`sdd/tasks/index/`) → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1732-renderer-pdf.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Read SPK-1 (TASK-1722): **weasyprint confirmed, no per-class split** — so
this renderer ships weasyprint only (no playwright path). `PDFRenderer` (registered
`pdf`, output `application/pdf`) composes the baked SSR-HTML (TASK-1729), pre-renders
each Chart component to a deterministic static SVG (weasyprint runs no JS), injects the
SVGs before `</body>`, then rasterizes via `weasyprint.HTML(string=...).write_pdf()`.
The blocking `write_pdf` runs off the event loop via `asyncio.to_thread` (test asserts
it executes on a non-main thread). weasyprint imported lazily with an actionable
ImportError naming `ai-parrot-visualizations[a2ui-pdf]`. Returns a `RenderedArtifact`
with inline PDF `content` (%PDF- magic verified). `a2ui-pdf` extra pin aligned to
`weasyprint>=68.0`. 7 tests pass (incl. e2e envelope→PDF→email-attachment seam with a
mocked provider); ruff clean; no exec/eval; `BaseRenderer` never imported.

**Deviations from spec**: `render()` accepts an optional `deep_links` kwarg (as in the
sibling renderers). The e2e test mocks the provider and validates the `report.files`
attachment-precedence seam directly rather than instantiating a full `BasicAgent`
(the full `send_notification` wiring is TASK-1733's scope); documented inline.
