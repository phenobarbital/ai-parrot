# TASK-2230: Fan-in nodes — bibliography (APA-ish), exec summary, final document, infographic

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2226, TASK-2228
**Assigned-to**: unassigned

---

## Context

Module 3 (fan-in half) of FEAT-425. Four node families that consume ALL
decks/slides: the deterministic APA-ish bibliography formatter, the
executive-summary synthesis (reusing the flow plane's `SynthesisNode` /
`synthesize_results` util), the final-document composer (calls TASK-2228's
renderer; print-CSS HTML + optional `.pdf`), and the infographic node
(InfographicToolkit, FEAT-308 pattern). Shares the `nodes/` package created
by TASK-2229 (extends its `__init__.py`).

---

## Scope

- Create in `packages/ai-parrot/src/parrot/flows/thales/nodes/`:
  - `bibliography.py` — `BibliographyNode` + pure function
    `format_apa(claims: list[SourceClaim]) -> Bibliography`:
    dedupe by normalized URL; APA-ish entry
    (`Author(s) (year). Title. Publisher. URL`); missing dates render
    **"n.d."** — NEVER invent a date; missing authors → publisher-led entry.
    Deterministic ordering (alphabetical by first author/publisher).
  - `summary.py` — `ExecSummaryNode` wrapping the existing
    `synthesize_results` util / `SynthesisNode` pattern over all deck texts.
  - `document.py` — `FinalDocumentNode`: slides + bibliography →
    `render_document(...)` (TASK-2228); when weasyprint present also
    `rasterize_pdf(...)`; persists BOTH via `ArtifactStore.save_artifact`
    and returns `ArtifactRef`s (pdf ref `None` + warning when unavailable).
  - `infographic.py` — `InfographicNode`: executive summary + decks →
    `InfographicToolkit.render_template(...)` (any-agent Jinja path) or the
    FEAT-308 `crew_report` route; graceful degrade — on toolkit failure log
    and return `None` (run continues; spec: infographic is Optional on
    `ThalesResult`).
- Extend `nodes/__init__.py` re-exports.
- Unit tests (formatter is pure — exhaustive table-driven tests; nodes with
  mocked store/toolkit).

**NOT in scope**: LLM nodes (TASK-2229); slide/document HTML internals
(TASK-2228 — this task calls them); flow wiring (TASK-2231).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/thales/nodes/bibliography.py` | CREATE | APA-ish formatter + node |
| `packages/ai-parrot/src/parrot/flows/thales/nodes/summary.py` | CREATE | ExecSummaryNode |
| `packages/ai-parrot/src/parrot/flows/thales/nodes/document.py` | CREATE | FinalDocumentNode (+ PDF, persistence) |
| `packages/ai-parrot/src/parrot/flows/thales/nodes/infographic.py` | CREATE | InfographicNode |
| `packages/ai-parrot/src/parrot/flows/thales/nodes/__init__.py` | MODIFY | Add re-exports (created by TASK-2229) |
| `packages/ai-parrot/tests/flows/thales/test_fanin_nodes.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from parrot.bots.flows.core.node import Node                 # core/node.py:68
from parrot.bots.flows.core.storage.synthesis import synthesize_results  # imported by flow.py
from parrot.tools.infographic_toolkit import InfographicToolkit  # infographic_toolkit.py:180
from parrot.storage.artifacts import ArtifactStore            # storage/artifacts.py:27
from parrot.flows.thales.models import Bibliography, SourceClaim, ArtifactRef  # TASK-2226
from parrot.flows.thales.rendering.document import render_document, rasterize_pdf  # TASK-2228
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1963
class SynthesisNode(Node):
    def model_post_init(self, __context): ...   # auto-create FSM
    async def execute(self, ctx, deps): ...     # LLM synthesis over dependency results
# synthesize_results util imported at flow.py top:
#   from ..core.storage.synthesis import synthesize_results

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                            # L27
    async def save_artifact(...): ...           # L46
    async def get_public_url(...): ...          # L177

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):      # L180
    async def render(self, template_name, theme, mode, data_variables,
                     blocks=None, blocks_variable=None, enhance_brief=None): ...  # L403
    async def render_template(self, template_name, data=None, theme=None,
                              title=None): ...  # L520 (works for ANY agent — no pandas REPL)
# FEAT-308 precedent for assembling crew/deck content into an infographic:
#   packages/ai-parrot/src/parrot/bots/flows/crew/result_infographic.py (tab assembly)
#   packages/ai-parrot/src/parrot/bots/flows/result_agent.py:107 (ResultAgent)
```

### Does NOT Exist
- ~~A bibliography/citation formatter anywhere in `parrot/`~~ — none exists;
  `format_apa` in this task is the first.
- ~~`SourceClaim.year`~~ — there is no year field; derive the year from
  `published_date` (ISO string) and render "n.d." when it is None.
- ~~`InfographicToolkit` requiring a PandasAgent~~ for this path —
  `render_template` (L520) explicitly works for any agent; do NOT wire a
  pandas REPL here.
- ~~A `thales` infographic template~~ in `infographic_registry` — pass a
  Jinja template via `templates={...}`/`add_template()` or reuse
  `crew_report`; do not assume a registered template name exists.
- ~~`ArtifactStore` global singleton~~ — the store instance is injected via
  the node factory closure (TASK-2231 provides it).

---

## Implementation Notes

### Pattern to Follow
```python
# format_apa is a PURE function — table-driven-testable without any node:
def format_apa(claims: list[SourceClaim]) -> Bibliography:
    # dedupe (normalized url) → sort → format:
    # "Lastname, F. (2024). Title. Publisher. https://..."
    # "Publisher. (n.d.). Title. https://..."   ← date-less form
```

### Key Constraints
- Bibliography determinism: same claims (any order) → identical entries list.
- Node failures in `infographic.py` must degrade (log + `None`), never
  break the run — mirrors FEAT-308's graceful-degrade contract.
- `FinalDocumentNode` warning path: weasyprint missing → pdf `ArtifactRef`
  is `None` and a warning string is appended for the manifest.
- Async throughout; store/toolkit injected, never constructed inside nodes.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/crew/result_infographic.py` —
  deterministic content→infographic assembly precedent (FEAT-308).

---

## Acceptance Criteria

- [ ] `format_apa` dedupes duplicate URLs, orders deterministically, renders "n.d." for missing dates, never fabricates a year
- [ ] `ExecSummaryNode` produces a synthesis string from ≥2 mocked decks
- [ ] `FinalDocumentNode` persists document HTML (and PDF when weasyprint present) via mocked `ArtifactStore`; missing weasyprint → `None` ref + warning
- [ ] `InfographicNode` failure degrades to `None` without raising
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/thales/test_fanin_nodes.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/thales/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/thales/test_fanin_nodes.py
from parrot.flows.thales.nodes.bibliography import format_apa
from parrot.flows.thales.models import SourceClaim

def _claim(**kw):
    base = dict(url="https://x/a", accessed_date="2026-08-17",
                source_tool="web_search", verification="provider_grounding")
    return SourceClaim(**{**base, **kw})

def test_bibliography_apa_dedupe():
    bib = format_apa([_claim(), _claim()])          # duplicate URL
    assert len(bib.entries) == 1

def test_bibliography_nd_for_missing_date():
    bib = format_apa([_claim(title="T", publisher="P", published_date=None)])
    assert "n.d." in bib.entries[0] and "20" not in bib.entries[0].split("n.d.")[0]

def test_bibliography_deterministic_order():
    a, b = _claim(url="https://x/a", title="A"), _claim(url="https://x/b", title="B")
    assert format_apa([a, b]).entries == format_apa([b, a]).entries
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2226, TASK-2228 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2230-thales-fanin-nodes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-17
**Notes**: Implemented `format_apa` (pure, deterministic dedupe-by-
normalized-URL + alphabetical ordering + "n.d." for missing dates, never
invents a year) + `BibliographyNode` fan-in; `ExecSummaryNode` (mirrors
`SynthesisNode`'s exact `_PartialResult`/`synthesize_results` pattern);
`FinalDocumentNode` (calls TASK-2228's `render_document`/`rasterize_pdf`,
persists HTML as `ArtifactType.INTERACTIVE` and PDF as `ArtifactType.EXPORT`
via injected `ArtifactStore`, `None` ref + warning when weasyprint absent);
`InfographicNode` (calls `InfographicToolkit.render_template`, degrades to
`None` + logged warning on any toolkit failure, never raises). Extended
`nodes/__init__.py` re-exports. 12 unit tests pass (mocked store/toolkit/
synthesis client); full `packages/ai-parrot/tests/flows/thales/` suite:
58 passed. `ruff check` on the new files shows only pre-existing style
categories (`UP006`/`UP017`/`UP035`/`UP045`/`PYI063`) — `UP017`
(`timezone.utc` vs `datetime.UTC`) matches the exact convention already
used in `storage/artifacts.py`, the module this code persists through.

Bug found and fixed (scoped to this task's own new files only): the
`SynthesisNode`/`DecisionNode` precedent's `model_post_init` docstring
says "call parent hook" but none of the real precedents actually call
`super().model_post_init()` — leaving `self.logger`/`self._logger` as
`None` on every custom `Node` subclass built that way (verified: the base
`Node.model_post_init` is what sets `self._logger`). `InfographicNode`
needs a working logger for its graceful-degrade log line, so all four of
this task's node classes explicitly call `super().model_post_init(
__context)` first. TASK-2229's three node classes (already committed) do
not call `self.logger` anywhere, so they were left untouched — fixing
them was out of THIS task's file scope.

Design notes (latitude taken within scope, TASK-2231 wiring still owns
the actual DAG assembly):
- `FinalDocumentNode` takes `store`/`user_id`/`agent_id`/`session_id` as
  constructor fields (all injected via `node_factories`, per the task's own
  "ArtifactStore... injected via the node factory closure" contract note,
  extended to the other run-scoped identifiers `ArtifactStore.save_artifact`
  requires) plus `slide_node_ids`/`bibliography_node_id` fields so it knows
  which `deps` entries are slides vs. the bibliography.
- `InfographicNode` similarly takes an injected `toolkit: InfographicToolkit`
  (already configured with its templates) and an `exec_summary_node_id`
  field to split `deps` into the summary string vs. deck payloads.

**Deviations from spec**: none
