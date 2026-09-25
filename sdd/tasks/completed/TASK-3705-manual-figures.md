# TASK-3705: Figure extraction, caption pairing, vision captioning, upload, presign (M6)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3699, TASK-3704
**Assigned-to**: unassigned

> Parallelism: calls extract_page_images/PageImage from TASK-3704 (pageindex/pdf_to_markdown.py); builds MediaRef/MediaLink from TASK-3699 (manuals/models.py).

---

## Context

Spec §3 **Module 6 (Figures)**. Figures are first-class graph nodes (G4): extracted with bboxes, paired to
steps deterministically by caption label, captioned once at ingest by a capability-resolved vision client,
uploaded through `FileManagerInterface`, and referenced only by `storage_key` (never a URL — **AC13**).
Presigned URLs are minted per answer (`presign`) by the service (TASK-3723). A cited-but-missing figure writes
**no** link and lands in the verification queue — never a nearest-page guess as `primary`. The callout pass
(Q8) is added to this same file by TASK-3706.

---

## Scope

- Create `manuals/figures.py` with: `CAPTION_RE`, `FigureCandidate`, `extract_figures`, `pair_figures`,
  `VisionCaptioner` protocol, `resolve_captioner`, `caption_figures`, `upload_figures`, `presign`, and the errors
  `CaptioningUnavailable`, `MediaUnavailable`.
- `pair_figures` operates on any sequence of objects exposing `.figure_refs: list[str]` (StepDraft from TASK-3707
  is imported only under `TYPE_CHECKING` — no runtime dependency on carding).
- Tests: `test_pair_figures_primary_by_label_secondary_by_distance`, `test_resolve_captioner_capability`,
  `test_presign_rejects_non_http`, plus an extract/upload test.

**NOT in scope**: callouts / `CalloutMapper` (TASK-3706); `assemble_card` wiring (TASK-3708); library
orchestration and the verification-queue write (TASK-3713 — this task only *returns* the unpaired labels);
channel delivery (TASK-3716..3719).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/figures.py` | CREATE | extraction, pairing, captioning, upload, presign |
| `packages/ai-parrot/tests/knowledge/manuals/test_figures.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.pdf_to_markdown import PageImage, extract_page_images   # created by TASK-3704 (pdf_to_markdown.py)
from parrot.knowledge.manuals.models import MediaRef, MediaLink                          # created by TASK-3699 (manuals/models.py)
# TYPE_CHECKING only:
from parrot.knowledge.manuals.carding import StepDraft                                   # created by TASK-3707 — NEVER at runtime
from pydantic import BaseModel, Field
import asyncio, hashlib, re, logging
from typing import Any, Mapping, Protocol, Sequence, TYPE_CHECKING
```

### Existing Signatures to Use
```python
# Vision entry points (per provider — NOT on AbstractClient):
AnthropicClient.ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image], reference_images=None, model=None,
    max_tokens=None, temperature=None, structured_output=None, count_objects=False, history=None, system_prompt=None,
    context_1m=False, no_memory=False) -> AIMessage
    # verified: packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:1329-1343
GoogleGenAIClient.ask_to_image(...)   # verified: packages/ai-parrot-client-google/src/parrot/clients/google/client.py:5160
OpenAIClient.ask_to_image(...)        # verified: packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py:1468
ClaudeAgentClient.ask_to_image(self, *args, **kwargs)  # verified: .../anthropic/claude_agent.py:1036-1040 — raises NotImplementedError

# FileManagerInterface (navigator-api 4.0.0; .venv/.../navigator/utils/file/abstract.py)
async def get_file_url(self, path: str, expiry: int = 3600) -> str                             # :67
async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata    # :79-81
# LocalFileManager.get_file_url returns file:// (spec §6, local.py:160-172)

# TASK-3699 model contract (spec §3 M2):
class MediaRef(BaseModel): media_id; kind: MediaKind; storage_key; uri; page; bbox; sha256; caption; label; t_start; t_end; origin="manual"; callouts=[]; unresolved_callouts=[]
    # validator: figure/photo ⇒ storage_key; never an http(s) URL in storage_key
class MediaLink(BaseModel): media_id: str; role: MediaRole; confidence: float; origin: Literal["manual","llm"]
```

### Does NOT Exist
- ~~`ask_to_image` on `AbstractClient`; URL input to any `ask_to_image`~~ — per provider, Path/bytes only (F023).
- ~~`get_file_url(path, expiry_seconds)`~~ — the parameter is `expiry` (F024).
- ~~A URL field persisted on `MediaRef`~~ — storage keys only (G4).
- ~~`parrot.knowledge.manuals.figures`~~ — created here.
- ~~A runtime import of `manuals.carding` from figures~~ — would create a cycle with TASK-3708 (`assemble_card` calls `pair_figures`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/figures.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_figures.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient.ask_to_image",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py#ClaudeAgentClient.ask_to_image"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- `extract_page_images` is sync — call it from async code via `asyncio.to_thread`; `extract_figures` itself is sync.
- Pairing is deterministic: label cited in `figure_refs` ⇒ `role="primary"`, `confidence=1.0`; otherwise the
  closest same-page step by vertical distance ⇒ `role="secondary"`, confidence scaled into (0, 0.9]; a label
  cited but not found ⇒ **no link** (returned as an unpaired reference for the queue).
- Captions are descriptive metadata only; they never select or order steps (G1).
- Use `FakeFileManager` from `tests/knowledge/_support/files.py` (TASK-3698) and the `manual_pdf` fixture.
- No new third-party dependency; Google docstrings, strict type hints, Pydantic v2, `logger` not `print`.
- Ontology imports (AC17) not relevant here.

### References in Codebase
- `packages/ai-parrot/src/parrot/storage/overflow.py:119-144` — `generate_presigned_url` calls `get_file_url(key, expiry=…)`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module header, errors and `CAPTION_RE` — *why*: the regex is fixed by the spec and shared by pairing and TASK-3706.
2. Implement `extract_figures` over `extract_page_images` + `page_texts` — *why*: caption = text block right below the bbox matching `CAPTION_RE`.
3. Implement `pair_figures` — *why*: deterministic pairing is the G1 guarantee; the LLM never chooses media.
4. Implement `resolve_captioner` / `caption_figures` — *why*: Q3 capability resolution; ClaudeAgentClient counts as absent.
5. Implement `upload_figures` / `presign` — *why*: G4/AC13 — keys stored, URLs minted per answer and rejected unless http(s).

### `packages/ai-parrot/src/parrot/knowledge/manuals/figures.py` (CREATE)
```python
"""Figure extraction, deterministic pairing, vision captioning and storage (FEAT-601 M6)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

from pydantic import BaseModel

from parrot.knowledge.manuals.models import MediaLink, MediaRef
from parrot.knowledge.pageindex.pdf_to_markdown import PageImage, extract_page_images

if TYPE_CHECKING:  # pragma: no cover
    from parrot.knowledge.manuals.carding import StepDraft

logger = logging.getLogger(__name__)

CAPTION_RE = re.compile(r"^\s*(?:Fig\.?|Figure|Figura)\s*([\dA-Z][\dA-Z\-\.]*)\s*[:.\-–]?\s*(.*)$", re.I | re.M)
CAPTION_PROMPT = "Describe this technical figure in one or two factual sentences. Context: {context}"


class CaptioningUnavailable(RuntimeError):
    """No vision-capable client is configured."""


class MediaUnavailable(RuntimeError):
    """A storage backend cannot produce an http(s) URL for a media key."""


class FigureCandidate(BaseModel):
    """One extracted image plus its (optional) printed caption."""

    image: PageImage
    label: str | None = None
    caption_text: str | None = None
    caption_distance: float | None = None
    vision_caption: str | None = None


def extract_figures(pdf_path: Path, work_dir: Path, *, page_texts: Mapping[int, str]) -> list[FigureCandidate]:
    """Extract page images and pair each with the caption printed directly below it."""
    images = extract_page_images(pdf_path, work_dir)
    # FILL IN: per image, find the first CAPTION_RE match below image.bbox on the same page (use pymupdf text blocks
    #   or page_texts order); fill label (normalized "3-4"), caption_text, caption_distance — bounded by: deterministic,
    #   no LLM, label None when no caption.
    return [FigureCandidate(image=img) for img in images]


def pair_figures(
    steps: Sequence["StepDraft"],
    figures: Sequence[FigureCandidate],
    *,
    page_of_step: Mapping[int, int],
) -> list[tuple[int, MediaLink]]:
    """Pair steps with figures: label ⇒ primary/1.0; uncaptioned same-page closest ⇒ secondary (scaled)."""
    # FILL IN: (1) for each step index, each ref in step.figure_refs → normalized label → figure with that label ⇒
    #   (i, MediaLink(role="primary", confidence=1.0, origin="manual")); (2) uncaptioned figures → closest step on the
    #   same page ⇒ role="secondary", confidence in (0, 0.9] scaled by distance; (3) cited label with no figure ⇒
    #   no link — bounded by G1 and spec M6 ("never a nearest-page guess as primary"). media_id = figure sha256[:16].
    return []


def unpaired_references(steps: Sequence["StepDraft"], figures: Sequence[FigureCandidate]) -> list[str]:
    """Figure labels cited by steps that no extracted figure carries (verification-queue items)."""
    # FILL IN: set difference of normalized cited labels vs figure labels, sorted — bounded by M6 queue rule.
    return []


class VisionCaptioner(Protocol):
    """Anything that can caption one image file."""

    async def caption(self, image: Path, *, context: str) -> str: ...


class _AskToImageCaptioner:
    """Adapter over a provider client's ``ask_to_image`` (Path input only)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def caption(self, image: Path, *, context: str) -> str:
        try:
            msg = await self._client.ask_to_image(CAPTION_PROMPT.format(context=context), image)
        except NotImplementedError as exc:
            raise CaptioningUnavailable(str(exc)) from exc
        # FILL IN: extract text from AIMessage (output/content) → str, strip — bounded by: never raise on empty text.
        return str(getattr(msg, "output", "") or "").strip()


def resolve_captioner(client: Any) -> VisionCaptioner:
    """Resolve a captioner by capability (Q3); raise CaptioningUnavailable when absent."""
    # FILL IN: None or no ask_to_image ⇒ raise; type(client).__name__ == "ClaudeAgentClient" ⇒ raise (it raises
    #   NotImplementedError, claude_agent.py:1036-1040) — bounded by AC13.
    return _AskToImageCaptioner(client)


async def caption_figures(
    figures: Sequence[FigureCandidate], captioner: VisionCaptioner, *, concurrency: int = 4
) -> list[FigureCandidate]:
    """Caption every figure once, bounded by a semaphore; failures leave vision_caption None."""
    sem = asyncio.Semaphore(concurrency)
    # FILL IN: gather with sem; context = caption_text or label or ""; log + continue on per-figure errors,
    #   re-raise CaptioningUnavailable — bounded by: input is image.path (Path), never a URL (AC13).
    return list(figures)


async def upload_figures(figures: Sequence[FigureCandidate], fm: Any, *, prefix: str) -> list[MediaRef]:
    """Upload each figure through FileManagerInterface.upload_file and return MediaRefs keyed by storage key."""
    # FILL IN: destination f"{prefix}/{fig.image.sha256}.png"; await fm.upload_file(fig.image.path, destination);
    #   MediaRef(kind="figure", storage_key=destination, page, bbox, sha256, caption=vision_caption or caption_text,
    #   label) — bounded by AC13 (no URL stored).
    return []


async def presign(fm: Any, storage_key: str, *, expiry: int = 900) -> str:
    """Mint a short-lived URL; raise MediaUnavailable unless it is http(s)."""
    url = await fm.get_file_url(storage_key, expiry=expiry)
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise MediaUnavailable(f"storage backend returned a non-http URL for {storage_key!r}")
    return url
```
**Why this shape**: pairing, captioning and storage are separate pure/async steps so TASK-3713 can order them
(pair before caption; upload last) and TASK-3708 can call `pair_figures` without importing I/O code.
`presign` is finished code because its contract (`expiry=`, http(s) only) is fully decided (AC13).

### `packages/ai-parrot/tests/knowledge/manuals/test_figures.py` (CREATE)
```python
"""FEAT-601 M6 — figures (AC13)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.knowledge.manuals import figures as fg


def test_pair_figures_primary_by_label_secondary_by_distance(tmp_path) -> None:
    # FILL IN: build FigureCandidate objects directly (PageImage with fake paths); steps as SimpleNamespace(figure_refs=[...]);
    #   assert label match ⇒ primary/1.0; uncaptioned same-page ⇒ secondary with 0<conf<=0.9; missing label ⇒ no link and
    #   listed by unpaired_references.
    ...


async def test_resolve_captioner_capability(tmp_path) -> None:
    class Vision:
        async def ask_to_image(self, prompt, image, **kw):
            return SimpleNamespace(output="a bracket")

    class ClaudeAgentClient:
        async def ask_to_image(self, *a, **k):
            raise NotImplementedError

    assert await fg.resolve_captioner(Vision()).caption(tmp_path / "f.png", context="") == "a bracket"
    with pytest.raises(fg.CaptioningUnavailable):
        fg.resolve_captioner(ClaudeAgentClient())
    with pytest.raises(fg.CaptioningUnavailable):
        fg.resolve_captioner(object())


async def test_presign_rejects_non_http() -> None:
    # FILL IN: fake fm whose get_file_url(path, expiry=…) records expiry and returns "file:///x" ⇒ MediaUnavailable;
    #   https ⇒ returned; assert expiry kwarg name used.
    ...


async def test_extract_and_upload_figures(manual_pdf, fake_file_manager, tmp_path) -> None:
    # FILL IN: extract_figures on manual_pdf (TASK-3698 fixture: "Fig. 1"/"Fig. 2") ⇒ labels "1","2";
    #   upload_figures ⇒ MediaRef.storage_key not http(s), keys recorded by fake_file_manager.
    ...
```

### FILL IN checklist
- [ ] `extract_figures` caption lookup below bbox — deterministic.
- [ ] `pair_figures` primary/secondary/no-link rules — G1, M6.
- [ ] `unpaired_references` — queue items.
- [ ] `resolve_captioner` capability rules; `_AskToImageCaptioner` text extraction — AC13.
- [ ] `caption_figures` bounded concurrency + error policy.
- [ ] `upload_figures` key scheme — AC13.
- [ ] Test bodies (remove `...`).

---

## Acceptance Criteria

- [ ] Label ⇒ primary/1.0; uncaptioned ⇒ secondary scaled; missing label ⇒ no link + unpaired reference (M6).
- [ ] Captioner resolved by capability; `ClaudeAgentClient`/no-method ⇒ `CaptioningUnavailable`; only Path input (AC13).
- [ ] `presign` uses `expiry=` and rejects non-http(s); no URL is persisted in any `MediaRef` (AC13, G4).
- [ ] `ruff check` + `black --check -l 120` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_figures.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_pair_figures_primary_by_label_secondary_by_distance` | label ⇒ primary/1.0; uncaptioned same-page ⇒ secondary scaled; missing label ⇒ no link + queue entry |
| `test_resolve_captioner_capability` | `ask_to_image` client ⇒ adapter; `ClaudeAgentClient`-like ⇒ `CaptioningUnavailable` |
| `test_presign_rejects_non_http` | `file://` ⇒ `MediaUnavailable`; `expiry=` kwarg used |
| `test_extract_and_upload_figures` | synthetic manual ⇒ labelled figures; upload stores keys only |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/training-agent.spec.md` (module section named in Context).
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/` (or merged in your feature branch).
3. **Verify the Codebase Contract** — before writing ANY code confirm every import, signature and line anchor
   above still holds (`grep -n` / `read`). Symbols marked "created by TASK-<X>" must exist now that the
   dependency landed; if a name differs, follow the landed code and record the deviation.
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes.
6. **Verify** — run every command in *Validation Commands* (with the worktree `PYTHONPATH`), plus `ruff check`
   and `black --check -l 120` on the touched files.
7. **Move this file** to `sdd/tasks/completed/`, set the index entry to `"done"`, fill in the Completion Note.

---

## Completion Note


- Task: TASK-3705
- Feature: training-agent
- Implementation SHA: fb81905650957992e0b2d3069e21575f98d47470
- Closed at (UTC): 2026-09-25T07:51:27+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
| supplementary_test_evidence | 97 passed, 0 failed (scoped direct pytest over manuals+catalog+figures+contracts/test_ontology_domain, after review-fix commit) |
