# Thales User Guide

**Thales** (named after Thales of Miletus — the codename's working slug,
`agentcrew-tales-research`, survives only in ledger/file continuity) is a
research flow that turns a thesis statement into a sourced research
package: research decks with cited findings, per-deck slide HTML, an
executive summary, a final print-CSS document (+ optional PDF), and a
summary infographic.

Every factual claim in a Thales deck carries source metadata (URL, title,
authors, publisher, dates) and a verification channel — this is the
project's answer to "a wall of unattributed LLM prose."

For the full design rationale see
`sdd/specs/agentcrew-tales-research.spec.md`.

---

## Quick Start — Python API

```python
import asyncio
from parrot.flows.thales import ThalesRunner

async def main():
    runner = ThalesRunner(
        thesis="remote work increases regional inequality",
        output_dir="./thales_output",   # mirrors every artifact + manifest.json
    )
    result = await runner.run()

    print(f"{len(result.decks)} decks, {len(result.bibliography.entries)} sources")
    print(result.executive_summary)
    print(result.final_document.url or result.final_document.path)

asyncio.run(main())
```

`ThalesRunner.run()` is two-phase (per the spec's design):

1. **Phase 1 — planning**: a planner LLM call turns the thesis into
   `num_decks` (default 10) `ResearchAngle`s.
2. **Phase 2 — research + synthesis**: an `AgentsFlow` graph is assembled
   for exactly those angles (research nodes → deck builders → slide specs
   → slide rendering → bibliography/exec-summary → final document +
   infographic) and executed with `checkpoint=True` (FEAT-399).

### The `num_decks` floor — and its cost

```python
ThalesConfig(num_decks=9)   # raises: minimum is 10
ThalesConfig(num_decks=500) # fine — no upper cap
```

`num_decks` **defaults to 10 and has no upper cap**. This is deliberate
(resolved in brainstorm) but has a real cost implication: each angle
researches across every enabled source (`M` sources), so a run makes
`num_decks × M` research calls. With the default 3 sources (web, deep
research, arxiv) and the 10-deck floor, that's **≥30 research calls per
run** — and Deep Research calls in particular are minutes-scale background
interactions. `ThalesRunner` logs the projected call count before phase 2
starts:

```
Thales run <id>: 10 angles x 3 sources = 30 projected research calls
```

Plan capacity/cost accordingly before raising `num_decks` for a production
run.

### Sources

```python
ThalesRunner(thesis="...", sources=["web", "deep_research", "arxiv"])  # default
ThalesRunner(thesis="...", sources=["web", "arxiv"])                    # deep research disabled
```

v1 ships three sources:

| Source | What it does |
|---|---|
| `web` | `WebSearchAgent` with Gemini's built-in Google Search (`use_builtin_search=True`), contrastive search, groundedness scoring |
| `deep_research` | The configured client's `ask(prompt, deep_research=True)` — a cross-provider flag; Google runs it as a real background Deep Research agent, other providers apply an enhanced research mode |
| `arxiv` | An agent carrying `ArxivTool`; paper metadata (title/authors/published/pdf_url) maps 1:1 onto source claims |

Disabling a source (e.g. `sources=["web", "arxiv"]`) degrades cleanly —
decks simply cite the remaining sources; no error.

### The `research-tools-for-agents` extension contract

Thales's research-node contract is deliberately narrow so new sources can
be added without touching the flow itself: a research node normalizes its
raw tool/agent output into `Finding` objects, each carrying one or more
`SourceClaim`s (`url`, `title`, `authors`, `publisher`, `published_date`,
`accessed_date`, `source_tool`, `verification`). The separate
`research-tools-for-agents` spec (World Bank, EU Open Data, Oxford
Academic, Gallup) implements new sources purely by producing `Finding`/
`SourceClaim` objects against this same contract — adding a source there
is adding a research node here, no flow changes required.

---

## Quick Start — HTTP API

Thales exposes a POST + polling surface (deliberately not SSE/WebSocket):

```bash
# Launch a run
curl -X POST http://localhost:8000/api/v1/thales \
  -H 'Content-Type: application/json' \
  -d '{"thesis": "open-source flight stacks bridge LATAM engineering talent"}'
# → {"run_id": "..."}

# Poll status (pending -> running -> completed|failed)
curl http://localhost:8000/api/v1/thales/<run_id>
# → {"run_id": ..., "status": "running", "node_events": [...]}
# → on completion, also carries "result": <full ThalesResult>

# List artifacts with public URLs
curl http://localhost:8000/api/v1/thales/<run_id>/artifacts
# → {"run_id": ..., "artifacts": [{"kind": "final_html", "url": "..."}, ...]}
```

`num_decks` below the floor of 10 is rejected with **HTTP 400** naming the
minimum. An unknown `run_id` on either GET route returns **HTTP 404**. A
failed run reports `"status": "failed"` with an `"error"` summary on the
status GET (HTTP 200 — the poll itself succeeded; the *run* failed).

---

## Artifacts & manifest layout

Every artifact persists through two independent surfaces — each fails
without aborting the other:

1. **`ArtifactStore`** (when `artifact_store=` is configured) — public URLs
   via `get_public_url()`.
2. **`output_dir` mirroring** (when `output_dir=` is configured) — plain
   files on disk:

```
<output_dir>/
├── deck-<angle_id>.json      # one per angle — the ResearchDeck JSON
├── slide-<angle_id>.html     # one per angle — the rendered slide HTML
└── manifest.json             # the full ThalesResult, JSON-serialized
```

`ThalesResult` (the manifest) aggregates: `decks` (all `ResearchDeck`
objects), `slides` (per-deck `ArtifactRef`s), `bibliography`,
`executive_summary`, `final_document` / `final_pdf` (`ArtifactRef`s),
`infographic` (the toolkit's render result, or `None`), and `warnings`
(non-fatal issues — e.g. a dropped deck, or a missing `weasyprint`).

A single angle's deck can be **dropped** (all its research sources
failed) without aborting the run — it's recorded as a warning. The run
only *raises* when **every** angle's deck was dropped.

---

## PDF behavior

The final document is always emitted as print-CSS HTML (`@page` rules,
one page-break per slide, bibliography as the final section). A real
`.pdf` is additionally emitted **only when `weasyprint` is importable**
(the `pdf` extra):

- `weasyprint` installed → `result.final_pdf` is populated, `url`/`path` set.
- `weasyprint` absent → `result.final_pdf` is `None`, and
  `result.warnings` includes a message naming the missing extra. The run
  still succeeds.

Charts follow the same "must survive a JS-less renderer" constraint: every
chart on a slide is emitted **both** as ECharts option-JSON (the
interactive browser path) and as a static SVG (the print/PDF path,
selected via `@media print` CSS) — weasyprint executes no JavaScript.

---

## Verification channels

Every `SourceClaim.verification` is one of:

| Value | Meaning |
|---|---|
| `"groundedness"` | Scored by the deterministic `GroundednessGuardrail` (FEAT-398) — the source came from a tool call whose `ToolCall.result` could be checked as evidence (e.g. arxiv). |
| `"provider_grounding"` | The source came from a provider-native grounding path (Gemini built-in search, Deep Research) that yields no `ToolCall.result` evidence for the deterministic scorer to check — accepted as-is in v1 (resolved in brainstorm). |
| `"unverified"` | No groundedness report was available for this claim. |

Missing publication dates are **never invented** — the bibliography
formatter renders them as `"n.d."` (APA-ish convention).

---

## Known limitation: `AgentsFlow.resume()`

Thales runs with `checkpoint=True` (FEAT-399) so a `FlowCheckpointer`
persists progress as nodes complete — this is real and verified (see
`tests/flows/thales/test_integration.py::TestCheckpointResume`). However,
a full `AgentsFlow.resume(flow_id, checkpoint_id, ...)` round-trip is
**not currently supported** for Thales's node shapes: `resume()`
reconstructs nodes via `from_definition()` with no `node_factories`
parameter, so custom fields Thales's nodes require (`angle`, `config`,
`client`, `agent`, `store`, `toolkit`, ...) cannot be supplied on
reconstruction. Adding `node_factories` support to `AgentsFlow.resume()`
itself would be an engine change, which is out of scope for this feature
(spec: "No changes to `flow.py`"). Tracked as a follow-up, not silently
worked around.

---

## Architecture reference

```
ThalesRunner.run()
  │ phase 1: planner LLM ──▶ list[ResearchAngle]  (len >= num_decks, no cap)
  │ phase 2: assemble AgentsFlow programmatically ──▶ run_flow(checkpoint=True)
  ▼
start ─▶ per angle i (parallel):
           research[i][web]   ─┐
           research[i][deep]   ├─▶ deck_builder[i] ─▶ slide_spec[i] ─▶ slide_render[i] ─┐
           research[i][arxiv] ─┘   (OR-join)          (structured)     (deterministic)  │
         bibliography  ◀── all decks' SourceClaims (deterministic, APA-ish) ◀───────────┤
         exec_summary  ◀── all decks (SynthesisNode-style)                              │
         final_document ◀── slides + bibliography (print-CSS HTML [+ .pdf])             │
         infographic   ◀── exec_summary + decks (InfographicToolkit) ─▶ end ◀───────────┘
  ▼
ArtifactStore + output_dir/manifest.json ──▶ ThalesResult
```

Every Thales node type is registered in the engine's `NODE_REGISTRY`,
idempotently (`parrot.flows.thales.nodes.registry.register_thales_node`),
mirroring `parrot.flows.dev_loop`'s own registration pattern — required
because `checkpoint=True` calls `AgentsFlow.to_definition()` as a
fail-fast export check regardless of assembly mode. See
`parrot/flows/thales/definition.py`'s module docstring for the full
verification trail.

Source code: `packages/ai-parrot/src/parrot/flows/thales/`.
HTTP handler: `packages/ai-parrot-server/src/parrot/handlers/thales.py`.
