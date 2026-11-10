# TASK-5470: Isolated PyMuPDF Layout extraction adapter

**Feature**: FEAT-875 — Optional PyMuPDF Layout for Bookstore PDF Ingestion
**Spec**: `sdd/specs/bookstore-pymupdf-layout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5469
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Creates `pdf_layout_backend.py`, an internal PageIndex adapter that runs
PyMuPDF Layout extraction in a **fresh child process** (`python -m parrot.knowledge.pageindex.pdf_layout_backend`)
so the server process never toggles PyMuPDF's global Layout state. Parent and child exchange one
Pydantic request and one Pydantic result as UTF-8 JSON over stdin/stdout.

The vendor-specific parts depend on TASK-5469's report (`sdd/state/FEAT-875/layout-compatibility.md`):
the activation call, the OCR- and image-write-disable keywords, and the page-identity field.
**Read that report first.** Do not guess these APIs.

## Scope

- `LayoutExtractionRequest` / `LayoutExtractionResult` Pydantic v2 models (spec §2 Data Models).
- `extract_layout_pages()`: async parent API that spawns the child with
  `asyncio.create_subprocess_exec(sys.executable, "-m", ...)`, with no shell, absolute paths, and both
  pipes drained concurrently. It enforces a positive timeout (default 300 s), terminates and reaps on
  timeout or cancellation (cancellation still propagates), and maps every failure to `PDFStructureError`
  with a **bounded** diagnostic (stderr truncated).
- `extract_layout_document()`: child-only native extraction. OCR and image writes are disabled, and
  page IDs are validated (dense 1..N, no duplicate, reorder, or out-of-range pages; blank pages are `""`).
- `main()`: redirects vendor stdout to stderr **before** importing Layout, reads one JSON request,
  writes one JSON result, and returns 0.
- Unit tests covering lifecycle, protocol purity, and validation, plus native tests that skip only when
  Layout is not installed.

**NOT in scope**: routing from `build_page_index` (TASK-5471), image extraction, retrying through the
legacy backend, or process pooling.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_layout_backend.py` | CREATE | Models, parent API, child entry point |
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_layout_backend.py` | CREATE | Unit + native tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.pageindex.layout import PDFStructureError
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py:51
from pydantic import BaseModel  # project standard (Pydantic v2)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py:51
class PDFStructureError(...): ...   # existing Bookstore-friendly error; library.py:1511 converts it to BookstoreError
```

The vendor API (activation, OCR off, image writes off, page id field) comes **only** from
`sdd/state/FEAT-875/layout-compatibility.md` §"Activation API", §"OCR and image-write disabling",
and §"Page identity".

### Does NOT Exist

- No `pdf_layout_backend.py` exists yet, and nothing imports `extract_layout_pages`.
- No `pageindex/config.py`.
- Do not assume an import named `pymupdf_layout`, an `ocr=` keyword, or a `page_number` chunk key. Use the report.
- `LayoutHeaders` must **not** be passed to this backend (spec: native headings are selected explicitly).

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_layout_backend.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_layout_backend.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#PDFStructureError"
  ]
}
```

## Implementation Notes

### Key Constraints

- Async-first: CPU and native work stay in the child. Do not add threads (spec §7).
- The child must initialize under the package's real import graph (`parrot.knowledge.pageindex.__init__`
  runs first under `-m`). TASK-5469 verified whether activation survives that ordering. Follow its finding.
- No source-PDF path is interpolated into executable code; it travels only inside the JSON request.
- Logging is `logging.getLogger(__name__)`. Never use `print`. Child diagnostics go to stderr.

## Implementation Blueprint

### Steps (in order)

1. Write the models and their validators first. Both parent and child validate shapes, so the same validator is reused on each side.
2. Write `extract_layout_document`, using the report's vendor calls in place of `FILL IN`s.
3. Write `main()`. Redirect stdout before any vendor import, because vendor banners would corrupt the JSON protocol.
4. Write `extract_layout_pages`. It must reap the child on every exit path, because a leaked native process outlives the request.
5. Write tests. Unit tests fake the child with a tiny script via `monkeypatch` of the command vector. Native tests use `pytest.importorskip` on the verified module.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_layout_backend.py` (CREATE)

```python
"""Isolated PyMuPDF Layout extraction backend (FEAT-875).

Runs native Layout analysis in a fresh child process so the server process never toggles
PyMuPDF's global Layout state. Child entry point:
``python -m parrot.knowledge.pageindex.pdf_layout_backend``.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from pathlib import Path

from pydantic import BaseModel, model_validator

from parrot.knowledge.pageindex.layout import PDFStructureError

logger = logging.getLogger(__name__)

_MODULE = "parrot.knowledge.pageindex.pdf_layout_backend"
_MAX_DIAGNOSTIC = 2000  # bytes of child stderr surfaced in errors
INSTALL_HINT = "install the optional extra: uv pip install 'ai-parrot[bookstore-layout]'"


class LayoutExtractionRequest(BaseModel):
    """Absolute local PDF path for an isolated, OCR-disabled extraction."""

    pdf_path: str

    @model_validator(mode="after")
    def _absolute(self) -> "LayoutExtractionRequest":
        # FILL IN: reject non-absolute paths — bounded by spec §2 "absolute PDF/output paths"
        return self


class LayoutExtractionResult(BaseModel):
    """Validated physical-page Markdown and installed extraction package versions."""

    pages: list[tuple[int, str]]
    page_count: int
    versions: dict[str, str]

    @model_validator(mode="after")
    def _dense_pages(self) -> "LayoutExtractionResult":
        # FILL IN: page_count >= 1; len(pages) == page_count; ids exactly 1..N in order
        #          — bounded by spec §2 Data Models (missing/duplicate/reordered/out-of-range fail closed)
        return self


def extract_layout_document(request: LayoutExtractionRequest) -> LayoutExtractionResult:
    """Child-only native extraction, with OCR and image writes disabled and page IDs validated."""
    # FILL IN: activate Layout + extract page chunks — bounded by report §Activation API, §OCR, §Page identity
    # FILL IN: map vendor page identity -> (page_no, markdown); blank pages -> "" — never renumber by enumeration
    raise NotImplementedError  # replace with the verified extraction


def main() -> int:
    """Consume one JSON request, emit one result, and return zero; diagnostics use stderr."""
    protocol_out = sys.stdout
    sys.stdout = sys.stderr  # vendor banners must never reach the JSON channel
    request = LayoutExtractionRequest.model_validate_json(sys.stdin.read())
    result = extract_layout_document(request)
    protocol_out.write(result.model_dump_json())
    protocol_out.flush()
    return 0


async def extract_layout_pages(pdf_path: str | Path, *, timeout_s: float = 300.0) -> list[tuple[int, str]]:
    """Extract dense physical pages in an isolated child; raise PDFStructureError on failure.

    Require a positive timeout. Terminate and reap on timeout/cancellation; cancellation propagates.
    """
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    request = LayoutExtractionRequest(pdf_path=str(Path(pdf_path).resolve()))
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", _MODULE,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(request.model_dump_json().encode("utf-8")), timeout=timeout_s
        )
    except asyncio.TimeoutError as exc:
        await _reap(proc)
        raise PDFStructureError(f"PyMuPDF Layout extraction timed out after {timeout_s}s") from exc
    except asyncio.CancelledError:
        await _reap(proc)
        raise
    # FILL IN: nonzero exit -> PDFStructureError with bounded stderr; missing package -> include INSTALL_HINT
    # FILL IN: parse stdout via LayoutExtractionResult.model_validate_json; ValidationError -> PDFStructureError
    # FILL IN: logger.info backend + result.versions — bounded by spec §2 "versions are logged"
    raise NotImplementedError


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Terminate (then kill) the child and wait so no worker outlives the request."""
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
```

**Why:** `communicate()` drains both pipes concurrently, so a chatty child cannot deadlock the parent.
`_reap` on both timeout and cancellation satisfies "no worker left alive". Do **not** leave
`raise NotImplementedError` in the final code. Every one is a `FILL IN`.

### `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_layout_backend.py` (CREATE)

```python
"""Tests for the isolated PyMuPDF Layout backend (FEAT-875)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.knowledge.pageindex.layout import PDFStructureError
from parrot.knowledge.pageindex.pdf_layout_backend import (
    LayoutExtractionRequest,
    LayoutExtractionResult,
    extract_layout_pages,
)


@pytest.mark.parametrize("pages", [[(1, "a"), (1, "b")], [(2, "a"), (1, "b")], [(1, "a"), (3, "c")]])
def test_result_rejects_non_dense_pages(pages: list[tuple[int, str]]) -> None:
    with pytest.raises(ValidationError):
        LayoutExtractionResult(pages=pages, page_count=len(pages), versions={})


def test_request_rejects_relative_path() -> None:
    with pytest.raises(ValidationError):
        LayoutExtractionRequest(pdf_path="relative.pdf")


async def test_timeout_reaps_child(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # FILL IN: point the child command at a sleeping script; assert PDFStructureError and process reaped
    ...


# FILL IN: test_cancellation_reaps_and_propagates, test_nonzero_exit_bounded_diagnostic,
#          test_invalid_json_is_structure_error, test_vendor_stdout_noise_does_not_corrupt_protocol,
#          test_missing_package_install_hint, test_non_positive_timeout_rejected
# FILL IN: native tests behind pytest.importorskip(<verified Layout module from the report>):
#          two-column sentinel order, blank middle page kept as "", image-only PDF yields no text
```

**Why:** the parametrized cases are exactly spec §2's fail-closed list. Native tests may skip only when
Layout is absent, because the Layout-enabled job must run them with zero skips (spec §4).

### FILL IN checklist

- [ ] Request absolute-path validator
- [ ] Result dense-page validator
- [ ] Vendor activation, OCR off, image writes off, page-id mapping (from the report)
- [ ] Exit-code, missing-package, and malformed-output error mapping with bounded diagnostics
- [ ] Version logging
- [ ] Remaining lifecycle and native tests
- [ ] No `NotImplementedError` left in the final module

## Acceptance Criteria

- [ ] Timeout and cancellation leave no child process alive, and cancellation propagates.
- [ ] Vendor stdout noise cannot corrupt the JSON result.
- [ ] Missing, duplicate, reordered, or out-of-range page IDs raise `PDFStructureError`. Blank pages are kept as `""`.
- [ ] A missing Layout package gives an actionable error naming `ai-parrot[bookstore-layout]`, with no fallback.
- [ ] No LLM or network calls in any test.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_layout_backend.py -q`

## Test Specification

See the blueprint test file. Unit tests replace the child with a stub script and need no Layout package.
Native tests use `pytest.importorskip` on the module name verified in TASK-5469.

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**: `parrot sdd worktree ensure --slug bookstore-pymupdf-layout --feature-id FEAT-875`
2. **Read the spec** and `sdd/state/FEAT-875/layout-compatibility.md`.
3. **Check dependencies**: TASK-5469 must be `"done"` in `sdd/tasks/index/bookstore-pymupdf-layout.json`, with verdict `compatible`.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** to `"in-progress"` (set `started_at`) and commit only the index file.
6. **Implement** from the blueprint, completing every `FILL IN`.
7. **Verify**: run the Validation Commands.
8. **Commit** only the files this task lists.
9. **Close** with `parrot sdd task close TASK-5470 bookstore-pymupdf-layout verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
