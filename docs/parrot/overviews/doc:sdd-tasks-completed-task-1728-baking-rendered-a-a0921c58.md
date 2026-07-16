---
type: Wiki Overview
title: 'TASK-1728: Baking pass + RenderedArtifact model'
id: doc:sdd-tasks-completed-task-1728-baking-rendered-artifact-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 6** of the spec (§3): the baking pass and the `RenderedArtifact`'
relates_to:
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.outputs.a2ui.artifacts
  rel: mentions
- concept: mod:parrot.outputs.a2ui.baking
  rel: mentions
- concept: mod:parrot.outputs.a2ui.models
  rel: mentions
- concept: mod:parrot.outputs.a2ui.renderers
  rel: mentions
- concept: mod:parrot.storage.artifacts
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1728: Baking pass + RenderedArtifact model

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1720, TASK-1723
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec (§3): the baking pass and the `RenderedArtifact`
model. Static surfaces (email, PDF, Teams card, baked HTML) cannot hold live
JSON Pointer data-model bindings — the bake pass resolves **every** binding
against the envelope's data model at render time, producing a self-contained
`RenderedArtifact` (spec §2 Data Models, G5). Research confirmed **nothing
reusable exists** — this task CREATES the model (the input doc's CR-2 assumption
that a rendered-file model already existed was wrong).

This is a CORE-side task (`parrot.outputs.a2ui.artifacts` + bake helper), but with
one hard packaging constraint (resolved OQ, spec §8): **`jsonpointer` is a dep of
`ai-parrot-visualizations[a2ui]`, NOT of core**. Core validates binding *syntax*
only (light regex, Module 1); full pointer *resolution* must live behind a lazy
import so `import parrot.outputs.a2ui` works with zero new core deps (G8).

---

## Scope

- Implement `RenderedArtifact` and `DeepLink` Pydantic v2 models in
  `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py`, exactly as sketched
  in spec §2 Data Models (copied into the Codebase Contract below), including the
  `content` XOR `path` invariant (validated — exactly one of inline bytes or temp
  file path).
- Implement the bake helper in
  `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py`:
  - Walks a `CreateSurface` envelope, finds all data-model bindings, resolves each
    JSON Pointer against the envelope data model, and returns a fully-resolved
    (zero live bindings) component tree for renderers to materialize.
  - **Structure the pointer-resolution entry point so core stays dep-free**: the
    module must NOT import `jsonpointer` at module level. Resolution lazily imports
    it inside the function; `ImportError` is re-raised with an actionable message
    naming `ai-parrot-visualizations[a2ui]` (same pattern as
    `_markdown_to_pdf`'s weasyprint guard and the embeddings registry). Core-only
    installs can still *syntax-validate* bindings (delegate to Module 1's light
    regex validation) — full resolution runs only where `jsonpointer` is available
    (i.e., in satellite renderers). Record this constraint in the module docstring.
  - Unresolvable pointer (path not present in the data model) → structured
    validation error (never silently dropped, never partial output).
- Implement `ArtifactStore` persistence glue: persist the source envelope via
  `ArtifactStore.save_artifact` and store the resulting id / S3 URI in
  `RenderedArtifact.source_envelope_ref`. The >200 KB S3 overflow is handled
  transparently by `ArtifactStore` (`definition_ref` convention) — reuse it, do
  not reimplement thresholds.
- Add `jsonpointer>=2.4` to the new `a2ui` extra in
  `packages/ai-parrot-visualizations/pyproject.toml` (create the extra if the
  renderer tasks have not created it yet).
- Write core unit tests (models, XOR invariant, actionable ImportError, store
  persistence with a mocked store) and satellite-side bake-resolution tests
  (`test_bake_resolves_all_pointers`, unresolvable pointer → validation error).

**NOT in scope**:
- Any concrete renderer (TASK-1729/1730/1731/1732 — Module 5).
- Delivery bridge / `send_notification` wiring, Teams Graph upload (Module 7).
- `DeepLinkService` mint/consume and resume routes (Module 8) — this task ships
  the `DeepLink` **model only**.
- Envelope models / binding-syntax regex themselves (Module 1, TASK-1720).
- Renderer registry / capabilities (Module 4, TASK-1723).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` | CREATE | `RenderedArtifact` + `DeepLink` Pydantic models |
| `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py` | CREATE | Bake helper: binding walk + lazy-jsonpointer resolution + envelope persistence glue |
| `packages/ai-parrot-visualizations/pyproject.toml` | MODIFY | Add/extend `a2ui` extra with `jsonpointer>=2.4` |
| `packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py` | CREATE | Model + persistence + missing-dep unit tests (core side) |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_baking.py` | CREATE | Full pointer-resolution tests (jsonpointer available) — note: viz package has NO `tests/` tree yet, create it |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified references from the actual codebase (re-checked 2026-07-10).
> Do NOT invent imports/attributes not listed here — `grep`/`read` first.

### Verified Imports
```python
from parrot.storage.artifacts import ArtifactStore  # storage/artifacts.py:27
from parrot.storage.models import Artifact, ArtifactType  # storage/models.py:275 / :244
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/storage/artifacts.py:27
class ArtifactStore:
    async def save_artifact(...)   # :46 — handles the >200 KB S3 overflow internally
    async def get_artifact(...)    # :77 — resolves definition_ref via self._overflow (:90)
    async def get_public_url(...)  # :177

# packages/ai-parrot/src/parrot/storage/models.py:275 — chat Artifact (definitions, NOT files)
class Artifact(BaseModel):
    definition: Optional[Dict[str, Any]] = None
    definition_ref: Optional[str] = None  # :293 — S3 URI if serialized >200 KB (docstring :283)

# Lazy-import + actionable-error precedent:
# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py:101 _markdown_to_pdf
#   :103 `from weasyprint import HTML` inside the function; :106 ImportError names the extra
# packages/ai-parrot/src/parrot/embeddings/registry.py
#   anchor: `raise ImportError(f"Cannot import embedding module '{module_path}': {exc}")`
```

### Target shape (spec §2 Data Models — sketch, NOT implementation code)
```python
# parrot/outputs/a2ui/artifacts.py — NEW (research: nothing reusable exists)
class RenderedArtifact(BaseModel):
    artifact_id: str
    mime_type: str
    content: Optional[bytes]                           # inline, XOR path
    path: Optional[Path]                               # temp file for attachments
    filename: str
    title: str
    surface: str                                       # renderer name
    source_envelope_ref: Optional[str]                 # ArtifactStore id / S3 URI
    deep_links: List[DeepLink] = []
    metadata: Dict[str, Any] = {}

class DeepLink(BaseModel):
    action_label: str
    url: str                                           # channel resume URL embedding the token
    token_id: str                                      # for audit/consume tracking
    expires_at: datetime
```

### Created by dependency tasks (verify against merged code before use)
- `parrot.outputs.a2ui.models` — `CreateSurface` + v1.0 message set, binding-syntax
  validation (TASK-1720, Module 1).
- `parrot.outputs.a2ui.renderers` — `AbstractA2UIRenderer`, `RendererCapabilities`
  (TASK-1723, Module 4) — baking is invoked by static renderers through this seam.

### Does NOT Exist
- ~~`RenderedArtifact` / `RenderedOutput` / `OutputArtifact`~~ — **no rendered-file
  model exists ANYWHERE in the monorepo today** (verified by repo-wide grep,
  2026-07-10). This task CREATES it. Do not go looking for one to reuse.
- ~~`jsonpointer` in any `pyproject.toml` or import~~ — not present anywhere in the
  repo yet; this task adds it to the viz `a2ui` extra ONLY (never to core).
- ~~`parrot/outputs/a2ui/` directory~~ — does not exist on `dev` yet; created by
  TASK-1720. If it is still absent when you start, your dependencies are not done.
- ~~`ArtifactStore.save()` / `.persist()`~~ — the method is `save_artifact` (:46).

---

## Implementation Notes

### Key Constraints
- **No `exec`/`eval` anywhere** in the A2UI subtree (G1) — baking is pure data
  transformation.
- **Zero live bindings post-bake** (spec §7 two-phase bake): a baked tree must
  contain no unresolved pointer expressions; assert this as a post-condition.
- **Core dep hygiene (G8)**: `import parrot.outputs.a2ui.baking` must succeed with
  core-only install; only *calling* full resolution may raise the actionable
  ImportError. This keeps `test_core_importable_without_satellite` (spec §4) green.
- Async-first where I/O is involved (store persistence); Pydantic v2; Google-style
  docstrings; `self.logger` / module logger, no prints.
- Oversized envelopes: rely on `ArtifactStore`'s existing overflow — persist the
  envelope, record the returned reference in `source_envelope_ref`.

### References in Codebase
- `packages/ai-parrot/src/parrot/storage/artifacts.py` — persistence + overflow.
- `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py:101` —
  lazy heavy-dep import with actionable error.
- Spec §2 "New Public Interfaces" — `AbstractA2UIRenderer.render(..., bake=True)`
  is the consumer of this helper.

---

## Acceptance Criteria

- [ ] `RenderedArtifact` + `DeepLink` implemented per the spec §2 sketch; `content`
      XOR `path` enforced by a model validator
- [ ] Bake helper resolves all JSON Pointer bindings; unresolvable pointer raises a
      structured validation error; baked output contains zero live bindings
- [ ] `jsonpointer` imported lazily only; core-only install can import the module;
      missing dep raises ImportError naming `ai-parrot-visualizations[a2ui]`
- [ ] Envelope persisted via `ArtifactStore.save_artifact`; ref recorded in
      `source_envelope_ref`; >200 KB overflow covered by the store's convention
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_baking.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui`
- [ ] No exec/eval: `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers` returns nothing
- [ ] Imports work: `from parrot.outputs.a2ui.artifacts import RenderedArtifact, DeepLink`

---

## Test Specification

> Minimal scaffold — names and intent only; the agent fills in bodies.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py
class TestRenderedArtifact:
    def test_model_fields_match_spec(self):
        """RenderedArtifact exposes the exact spec §2 field set with defaults."""
        ...

    def test_content_xor_path_enforced(self):
        """Providing both (or neither) of content/path raises a validation error."""
        ...

    async def test_source_envelope_persisted_via_artifact_store(self):
        """Envelope is saved through ArtifactStore.save_artifact (mocked) and the
        returned reference lands in source_envelope_ref."""
        ...

    def test_bake_missing_jsonpointer_raises_actionable_error(self):
        """With jsonpointer unavailable, resolution raises ImportError naming
        ai-parrot-visualizations[a2ui]; module import itself still succeeds."""
        ...


# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_baking.py
class TestBakingPass:
    def test_bake_resolves_all_pointers(self):
        """Baked output contains zero live bindings — every JSON Pointer binding in
        the golden envelope is replaced by its data-model value (spec §4)."""
        ...

    def test_bake_unresolvable_pointer_raises(self):
        """A binding pointing at a nonexistent data-model path raises a structured
        validation error (no partial/silent output)."""
        ...

    def test_bake_is_deterministic(self):
        """Same envelope + data model bakes to an identical tree on repeat runs."""
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
4. **Update status** in the per-spec index (`sdd/tasks/index/`) → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1728-baking-rendered-artifact.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Created `artifacts.py` (`RenderedArtifact` + `DeepLink` per spec §2, with a
`content` XOR `path` model validator) and `baking.py` (bake pass). Bindings resolve
via `jsonpointer.resolve_pointer` behind a lazy `_load_jsonpointer()` (indirected
through `_import_jsonpointer()` so tests can force failure) — `import
parrot.outputs.a2ui.baking` works core-only; calling resolution without the extra
raises `ImportError` naming `ai-parrot-visualizations[a2ui]`. `bake_envelope` resolves
all bindings against the nested `data_model`, guards a zero-live-binding
post-condition, and raises `BakeError` on unresolvable pointers. `persist_envelope`
saves the source envelope via `ArtifactStore.save_artifact` (which returns None; the
generated `artifact_id` is the returned ref) and relies on the store's >200 KB
overflow. Added `a2ui` (`jsonpointer>=2.4` + map/jinja2/echarts) and `a2ui-pdf`
(+weasyprint) extras to the viz pyproject; wired `a2ui` into `all`. Core: 70 tests
pass; viz baking: 3 pass; ruff clean; no exec/eval.

**Deviations from spec**: none. Two notes: (1) `save_artifact` returns None (verified),
so `source_envelope_ref` is the artifact_id we assign rather than a store-returned id.
(2) The viz `tests/` tree collides with the core `tests/` package name under a shared
pytest run, so viz tests must be run with `--import-mode=importlib` (or from the viz
package rootdir) — documented for the QA/renderer tasks that follow.
