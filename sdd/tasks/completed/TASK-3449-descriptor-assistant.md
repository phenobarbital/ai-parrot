# TASK-3449: LLM-assisted descriptor proposal CLI (POG PDF only)

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3419, TASK-3435, TASK-3436
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 20**, goal G16. A slots definition is only useful when its
positions carry descriptors (`display_name / family / xl / colors / pack /
identifiers / aliases`); the reference ink-wall definition describes 2 of 102
positions. This utility proposes descriptors per position from the **POG PDF
only**, with page evidence, for **human review**. The user discarded any
catalog / SKU / price lookup: there is no data to back it, so the tool **never
proposes `price`** — even if the model returns one.

The script lives under `examples/planogram/`, which is git-ignored except for
explicit negations; TASK-3419 adds the negation that makes
`examples/planogram/descriptor_assistant.py` trackable.

---

## Scope

- `DescriptorProposal` / `PageProposals` Pydantic models (no `price` field).
- `render_pdf_pages(pdf, *, dpi) -> List[bytes]` — PNG bytes per page, PyMuPDF
  imported lazily with a clear error when missing.
- `async propose_descriptors(pdf, definition, adapter) -> Dict[str, DescriptorProposal]`
  — one `VisionAdapter.ask` call per PDF page (page image + the list of
  undescribed positions), responses merged by `facing_id`; unknown facing ids
  are dropped with a logged warning; any `price` key is stripped.
- `write_proposal(proposals, definition_path) -> Path` — writes
  `<definition stem>.descriptors.proposal.json` **next to** the definition;
  never writes to the definition file itself.
- CLI (`argparse`): `--pdf`, `--definition`, `--backend provider:model`,
  `--dpi`, `--cache-dir`.
- Offline test with a fake adapter; the script is loaded through
  `importlib.util.spec_from_file_location` (it is not an importable package).

**NOT in scope**: catalog / SKU / price lookup; editing or merging into the
definition file; OCR of the PDF; any change to package code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/descriptor_assistant.py` | CREATE | CLI + `propose_descriptors` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_assistant.py` | CREATE | offline tests (fake adapter) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, Field
from parrot.clients.factory import LLMFactory      # verified: packages/ai-parrot/src/parrot/clients/factory.py:163
import fitz                                        # PyMuPDF 1.27 — LAZY import only. Declared by core extra
                                                   #   `bookstore` (packages/ai-parrot/pyproject.toml:341-345), NOT by ai-parrot-pipelines
# created by dependency tasks
from parrot_pipelines.planogram.comparison.definition import SlotsDefinition, load_slots_definition   # TASK-3435
from parrot_pipelines.planogram.identification.vision import VisionAdapter, VisionError               # TASK-3436
from parrot_pipelines.planogram.backend import UNSET, resolve_backend                                 # TASK-3426 (via TASK-3436)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                                                  # :163
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient     # :257; unknown provider ⇒ ImportError :296-299

# PyMuPDF API (verified in the repo venv, PyMuPDF 1.27.1):
#   doc = fitz.open(str(path)); doc.page_count; page = doc.load_page(i)
#   pix = page.get_pixmap(dpi=150); png_bytes = pix.tobytes("png")

# .gitignore FEAT-565 block (verified :413-425): `examples/planogram/*` is ignored; tracked files need a `!` negation.
```

```python
# Created by TASK-3436 (dependency) — planogram/identification/vision.py, spec §3 Module 10
class VisionAdapter:
    def __init__(self, client: Any, backend: ResolvedBackend, *, semaphore: asyncio.Semaphore,
                 cache_dir: Optional[Path] = None, max_tokens: int = 8192,
                 timeout: float = 120.0, repair_retries: int = 1) -> None
    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *, stage: str,
                  prompt_version: str, system_prompt: Optional[str] = None) -> T     # raises VisionError
# Created by TASK-3426 (dependency) — planogram/backend.py
def resolve_backend(llm, llm_provider, llm_model, config_backend) -> ResolvedBackend
# Created by TASK-3435 (dependency) — planogram/comparison/definition.py
def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition
class FacingDefinition(BaseModel): facing_id, shelf_id, slot, product, brand, facings, descriptors: Descriptors
class Descriptors(BaseModel):      display_name, family, xl, colors, pack, identifiers, aliases, price  (all optional)
def definition_coverage(definition: SlotsDefinition) -> Tuple[float, List[str]]      # (fraction, undescribed facing_ids)
# Created by TASK-3419 (dependency): the `!examples/planogram/descriptor_assistant.py` negation in .gitignore
```

### Does NOT Exist
- ~~a catalog file, `load_catalog()`, SKU or price source~~ — removed/discarded; never look one up.
- ~~`price` in `DescriptorProposal`~~ — deliberately absent; strip it from model output.
- ~~`pdf2image`~~ — not installed; use PyMuPDF.
- ~~`pymupdf` as a dependency of `ai-parrot-pipelines`~~ — not declared there; lazy import + actionable error.
- ~~`examples.planogram` as an importable package~~ — tests load the script by file path.
- ~~`VisionAdapter.ask_pdf` or any PDF support in the adapter~~ — it takes image bytes only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/descriptor_assistant.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_assistant.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.create"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Blocking work off the loop: `await asyncio.to_thread(render_pdf_pages, pdf, dpi=dpi)`
  and `await asyncio.to_thread(load_slots_definition, path)`.
- No `print`: `logging` for progress, `sys.stdout.write` for the final output path.
- The "never price" rule is enforced **twice**: the schema has no `price`
  field, and `_strip_price` removes the key from any nested dict before
  validation (Pydantic's default `extra="ignore"` would drop it silently; the
  explicit strip makes the rule testable and logged).

### Key Constraints
- Output is a *proposal* file; refuse to run when the computed output path
  equals the definition path.
- One failed page is isolated: log it, continue with the other pages.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- `examples/planogram/plancheck/reference.py:96-106` — the descriptor field list (reference only; do not import `plancheck`)
- `packages/ai-parrot-pipelines/tests/conftest.py` — `fake_vision_client` (TASK-3420, reached through TASK-3436)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create the script with models + `_strip_price` — *why*: the "never price" rule is the task's hard constraint; build it first and test it first.
2. Add `render_pdf_pages` with the lazy PyMuPDF import — *why*: keeps the script importable (and the tests runnable) without PyMuPDF.
3. Add `propose_descriptors`, `write_proposal`, then the CLI — *why*: the test drives `propose_descriptors` directly with a fake adapter.
4. Write the tests, run the Validation Command.
5. Confirm `git check-ignore examples/planogram/descriptor_assistant.py` prints nothing — *why*: proves TASK-3419's negation covers the file.

### `examples/planogram/descriptor_assistant.py` (CREATE)
```python
"""Propose per-position descriptors from a POG PDF, for human review (FEAT-574).

POG PDF only: no catalog, SKU or price lookup. ``price`` is never proposed.
Usage: python examples/planogram/descriptor_assistant.py --pdf POG.pdf --definition slots.json \
           --backend anthropic:claude-sonnet-5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from parrot_pipelines.planogram.comparison.definition import SlotsDefinition, load_slots_definition

logger = logging.getLogger("descriptor_assistant")
PROMPT_VERSION = "descriptors-v1"
STAGE = "descriptors"


class DescriptorProposal(BaseModel):
    """Proposed descriptors for one facing. There is deliberately NO price field."""

    facing_id: str
    display_name: Optional[str] = None
    family: Optional[str] = None
    xl: Optional[bool] = None
    colors: List[str] = Field(default_factory=list)
    pack: Optional[str] = None
    identifiers: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    page: int = 0
    evidence: str = ""


class PageProposals(BaseModel):
    """Structured output of one page call."""

    proposals: List[DescriptorProposal] = Field(default_factory=list)


def _strip_price(payload: Any) -> Any:
    """Recursively drop every ``price`` key from a model payload (logged once per call)."""
    # FILL IN: dict → drop "price" (case-insensitive) and recurse; list → recurse — bounded by:
    #   must not mutate the caller's object.
    raise NotImplementedError


def render_pdf_pages(pdf: Path, *, dpi: int = 150) -> List[bytes]:
    """Render every page of ``pdf`` to PNG bytes (blocking — call via asyncio.to_thread).

    Raises:
        RuntimeError: When PyMuPDF is not installed (message names `uv pip install pymupdf`).
        FileNotFoundError: When ``pdf`` does not exist.
    """
    # FILL IN: lazy `import fitz`; fitz.open(str(pdf)); page.get_pixmap(dpi=dpi).tobytes("png")
    raise NotImplementedError


async def propose_descriptors(pdf: Path, definition: SlotsDefinition, adapter: Any
                              ) -> Dict[str, DescriptorProposal]:
    """facing_id → proposal (descriptors without price, page number, evidence text)."""
    pages = await asyncio.to_thread(render_pdf_pages, pdf)
    known = {f.facing_id: f for shelf in definition.shelves for f in shelf.facings}
    proposals: Dict[str, DescriptorProposal] = {}
    for number, png in enumerate(pages, start=1):
        try:
            answer = await adapter.ask(_build_prompt(definition, number), [png], PageProposals,
                                       stage=STAGE, prompt_version=PROMPT_VERSION)
        except Exception as exc:  # one failed page never aborts the run
            logger.warning("page %d failed: %s", number, exc)
            continue
        # FILL IN: for each proposal — skip + warn when facing_id not in `known`; force page=number;
        #   first proposal for a facing wins unless the later one has MORE non-empty fields.
    return proposals
```
**Why this shape**: `propose_descriptors`' signature is fixed by spec Module 20.
`adapter` is typed `Any` so the test can pass a fake exposing only `ask`.

### same file — part 2
```python
def _build_prompt(definition: SlotsDefinition, page: int) -> str:
    """Prompt listing facing_id + product + brand of the positions to describe."""
    # FILL IN: instruct — use ONLY what is printed on this page; quote the evidence text; leave a field
    #   null when the page does not show it; NEVER output a price — bounded by: list only facings whose
    #   descriptors are insufficient (definition_coverage's undescribed ids) to keep the prompt small.
    raise NotImplementedError


def write_proposal(proposals: Dict[str, DescriptorProposal], definition_path: Path) -> Path:
    """Write ``<stem>.descriptors.proposal.json`` next to the definition. Never the definition itself."""
    out = definition_path.with_name(f"{definition_path.stem}.descriptors.proposal.json")
    if out.resolve() == definition_path.resolve():
        raise ValueError("refusing to overwrite the slots definition")
    payload = {fid: _strip_price(p.model_dump()) for fid, p in sorted(proposals.items())}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


async def _run(args: argparse.Namespace) -> int:
    # FILL IN: definition = await asyncio.to_thread(load_slots_definition, args.definition);
    #   build VisionAdapter — lazy imports of LLMFactory, VisionAdapter, resolve_backend/UNSET:
    #   backend = resolve_backend(args.backend, UNSET, UNSET, None); client = LLMFactory.create(args.backend);
    #   adapter = VisionAdapter(client, backend, semaphore=asyncio.Semaphore(2), cache_dir=args.cache_dir)
    #   — bounded by: `async with client:` around the calls if the client is a context manager.
    raise NotImplementedError


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--backend", required=True, help='"provider:model"')
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--cache-dir", type=Path, default=None)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
```
**Why**: provider imports are lazy inside `_run` so the test can load the
script without any provider SDK; `write_proposal` strips `price` again as a
last line of defence.

### FILL IN checklist
- [ ] `_strip_price` — recursive, non-mutating, case-insensitive
- [ ] `render_pdf_pages` — lazy PyMuPDF, actionable error
- [ ] `propose_descriptors` — unknown ids dropped, page forced, merge rule
- [ ] `_build_prompt` — evidence quoting, null-when-absent, never price, only undescribed facings
- [ ] `_run` — adapter construction, client lifecycle
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `DescriptorProposal` has no `price` field and the written proposal JSON contains no `price` key at any depth, even when the fake model returns one.
- [ ] Input is the POG PDF only — no catalog/SKU/price lookup code exists in the script.
- [ ] Unknown `facing_id`s are dropped with a warning; a failed page does not abort the run.
- [ ] The proposal is written next to the definition as `<stem>.descriptors.proposal.json`; the definition file is byte-identical afterwards.
- [ ] Importing the script requires neither PyMuPDF nor a provider SDK.
- [ ] `git check-ignore examples/planogram/descriptor_assistant.py` prints nothing.
- [ ] No `print`; `ruff check examples/planogram/descriptor_assistant.py` passes.
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_assistant.py -q` passes offline.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_assistant.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_assistant.py
"""Offline tests for examples/planogram/descriptor_assistant.py (loaded by file path)."""
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "examples" / "planogram" / "descriptor_assistant.py"


@pytest.fixture(scope="module")
def assistant():
    spec = importlib.util.spec_from_file_location("descriptor_assistant", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAdapter:
    """Returns one canned PageProposals per ask() call; records calls."""
    def __init__(self, answers): self.answers, self.calls = list(answers), []
    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append({"prompt": prompt, "stage": stage})
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return schema.model_validate(item)


def test_strip_price_is_recursive_and_non_mutating(assistant): ...


def test_descriptor_proposal_has_no_price_field(assistant):
    assert "price" not in assistant.DescriptorProposal.model_fields


@pytest.mark.asyncio
async def test_never_proposes_price(assistant, monkeypatch, tmp_path):
    """Fake model returns {"facing_id": "shelf-1:1", "price": "19.99", …}; written JSON has no 'price'."""


@pytest.mark.asyncio
async def test_unknown_facing_ids_dropped_and_failed_page_isolated(assistant, monkeypatch): ...


def test_write_proposal_never_touches_definition(assistant, tmp_path): ...
```
(`monkeypatch.setattr(assistant, "render_pdf_pages", lambda pdf, dpi=150: [b"png1", b"png2"])` keeps
the tests free of PyMuPDF. Check `parents[4]` resolves to the repo root from
`packages/ai-parrot-pipelines/tests/planogram_cycle/` and adjust if not.)

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
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3449-descriptor-assistant.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD

**Completed by**: sdd-worker (sequential fallback — parrot-sdd-coder MCP server unresponsive)
**Date**: 2026-09-19
**Notes**: `examples/planogram/descriptor_assistant.py` per blueprint. "Never price" enforced three times:
schema has no `price`, `_strip_price` (recursive, case-insensitive, non-mutating) runs on every model answer,
and again in `write_proposal`. Prompt lists only undescribed facings (`definition_coverage`). Merge rule:
first proposal wins unless a later one fills more descriptor fields; page number forced from the render loop.
Deviation (minor): `render_pdf_pages(dpi=None)` defaults to a module `_RENDER_DPI` that the CLI sets from
`--dpi`, because `propose_descriptors` (fixed signature) calls the renderer with no dpi. Test fixture registers
the module in `sys.modules` before `exec_module` — Pydantic needs it to resolve `from __future__` annotations.
Validation: 7/7 tests pass offline; ruff + black clean; `git check-ignore` prints nothing; importing the
script loads neither `fitz` nor a provider SDK.
Seat: sdd-worker (sequential) · Backend: native · Model: claude-opus-5 · Attempts: 1
