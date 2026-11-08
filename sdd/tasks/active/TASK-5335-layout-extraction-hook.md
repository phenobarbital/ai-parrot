# TASK-5335: Layout-aware extraction hook: hdr_info (M2)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 2. The builder (TASK-5340) extracts per-page markdown with the layout-aware header detector
(`LayoutHeaders`, TASK-5334) so that every printed heading becomes a `heading` segment. It does so through
the existing `extract_markdown_per_page`, which today forwards only `page_chunks` and the image options to
`pymupdf4llm.to_markdown`. This task adds one keyword, `hdr_info`, forwarded only when given, so that the
call without it stays byte-identical (AC-12: `test_pdf_page_images.py:36` passes unchanged).

Spec sections: §2 "Pipeline" step 3, §3 Module 2, §4 `test_pdf_page_images.py::test_hdr_info_forwarded`,
AC-12. Delegation-eligible per spec §3 ("`hdr_info: Any = None`; forwarded only when not `None`").

---

## Scope

- Add `from typing import Any` to `pdf_to_markdown.py`.
- Add the keyword-only parameter `hdr_info: Any = None` to `extract_markdown_per_page`, after
  `image_size_limit`, with an `Args:` docstring entry.
- Forward it as `kwargs["hdr_info"] = hdr_info` only when it is not `None`, right after
  `kwargs: dict[str, object] = {"page_chunks": True}` and before the `images_dir` block.
- Add `test_hdr_info_forwarded` to `test_pdf_page_images.py`, as a sibling right after
  `test_extract_markdown_per_page_unchanged_without_images_dir`.

**NOT in scope**: `LayoutHeaders` (TASK-5334); calling the hook from the builder (TASK-5340); any change to
`extract_page_images`, `build_node_markdown_map` or the existing tests' assertions (the existing
`tm.assert_called_once_with(str(pdf), page_chunks=True)` must stay untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` | MODIFY | `hdr_info` keyword, forwarded only when not `None` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py` | MODIFY | Add `test_hdr_info_forwarded` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from typing import Any                                               # stdlib; pdf_to_markdown.py has no typing import today (grep -c '^from typing' == 0)
from parrot.knowledge.pageindex import pdf_to_markdown as p2m        # verified: test_pdf_page_images.py:12
from unittest import mock                                            # verified: test_pdf_page_images.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py
from pathlib import Path                                             # :21 (the import anchor; occurrences 1)
def extract_markdown_per_page(                                       # :39
    pdf_path: str | Path,
    *,
    images_dir: str | Path | None = None,
    image_format: str = "png",
    dpi: int = 150,
    image_size_limit: float = 0.05,                                  # :45 (anchor; occurrences 1)
) -> list[tuple[int, str]]:
    # docstring Args: image_size_limit entry ends at :62
    #   "            ``pymupdf4llm`` when ``images_dir`` is set. Ignored otherwise."  (occurrences 1)
    # :94  kwargs: dict[str, object] = {"page_chunks": True}             (occurrences 1)
    # :95-103 images_dir block, then chunks = pymupdf4llm.to_markdown(path_str, **kwargs)
# pymupdf4llm 0.0.27: to_markdown(doc, *, pages=None, hdr_info=None, ..., page_chunks=False, ...)  (pymupdf_rag.py:303)

# packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py
def _two_image_pdf(path: Path) -> Path                               # :15
def test_extract_markdown_per_page_unchanged_without_images_dir(tmp_path: Path) -> None:   # :36
    # :41 tm.assert_called_once_with(str(pdf), page_chunks=True)      — must stay unchanged
    # :56 last line:  assert "pages" not in call_kwargs                (anchor; occurrences 1)
def test_extract_page_images_bbox(tmp_path: Path) -> None:           # :59
```

### Does NOT Exist
- ~~a `hdr_info` parameter on `extract_markdown_per_page`~~ — it forwards only `page_chunks` and the image options today
- ~~`from typing import ...` in `pdf_to_markdown.py`~~ — no typing import exists; add `from typing import Any`
- ~~`pages=` forwarding~~ — never pass `pages=` (comment at :92-93: it would decouple the index from `get_page_tokens`)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py#extract_markdown_per_page",
    "sym:packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py#_two_image_pdf"
  ]
}
```

---

## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-5335",
  "spec_path": "sdd/specs/pageindex-layout-structure.spec.md",
  "design_complete": true,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py",
      "action": "modify",
      "expected_sha256": "cb0850a104fa37ddabb3d68d15c1bf0e2255d01c56bd652b76375709c99fe4d5",
      "planned_changes": "Import Any; add keyword hdr_info: Any = None after image_size_limit with an Args docstring entry; forward kwargs['hdr_info'] only when not None, right after the kwargs line",
      "blocks": ["impl-p2m-hdr-info"]
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py",
      "action": "modify",
      "expected_sha256": "c57b157df0a56e33bf81e77aedc6148f27ab67192d659e73fdb728fde0af62d4",
      "planned_changes": "Add test_hdr_info_forwarded after test_extract_markdown_per_page_unchanged_without_images_dir",
      "blocks": ["impl-test-hdr-info"]
    }
  ],
  "references": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py",
      "sha256": "cb0850a104fa37ddabb3d68d15c1bf0e2255d01c56bd652b76375709c99fe4d5",
      "start_line": 16,
      "end_line": 126,
      "purpose": "imports and extract_markdown_per_page (signature :39-46, docstring :47-77, kwargs :94-103)"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py",
      "sha256": "c57b157df0a56e33bf81e77aedc6148f27ab67192d659e73fdb728fde0af62d4",
      "start_line": 1,
      "end_line": 59,
      "purpose": "imports, _two_image_pdf helper and the unchanged call-shape test the new test sits after"
    }
  ],
  "implementation_blocks": ["impl-p2m-hdr-info", "impl-test-hdr-info"],
  "acceptance_criteria": [
    "extract_markdown_per_page(path, hdr_info=obj) calls pymupdf4llm.to_markdown(str(path), page_chunks=True, hdr_info=obj)",
    "without hdr_info (or hdr_info=None) the call is to_markdown(str(path), page_chunks=True), exactly as before",
    "test_extract_markdown_per_page_unchanged_without_images_dir passes unchanged",
    "pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py passes",
    "pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py passes"
  ],
  "validation_commands": [
    ["pytest", "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py", "-q"],
    ["pytest", "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py", "-q"]
  ]
}
```

```python id=impl-p2m-hdr-info
# Apply to packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py — four insertions.

# 1. Insert directly below the line `from pathlib import Path` (line 21):
from typing import Any

# 2. Insert directly below the signature line `    image_size_limit: float = 0.05,` (line 45):
    hdr_info: Any = None,

# 3. Insert directly below the docstring line
#    `            ``pymupdf4llm`` when ``images_dir`` is set. Ignored otherwise.` (line 62):
        hdr_info: Header detector forwarded to ``pymupdf4llm.to_markdown`` as
            ``hdr_info`` (an object with ``get_header_id(span, page=None)``,
            e.g. ``LayoutHeaders``). Forwarded only when not ``None``; with
            ``None`` the call is byte-identical to the pre-existing behaviour.

# 4. Insert directly below the line `    kwargs: dict[str, object] = {"page_chunks": True}` (line 94),
#    before the `if images_dir is not None:` block:
    if hdr_info is not None:
        kwargs["hdr_info"] = hdr_info
```

```python id=impl-test-hdr-info
# Apply to packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py:
# insert below the line `    assert "pages" not in call_kwargs` (line 56), before `def test_extract_page_images_bbox`.


def test_hdr_info_forwarded(tmp_path: Path) -> None:
    """``hdr_info`` reaches ``to_markdown`` by keyword; ``None`` keeps the old call shape (AC-12)."""
    pdf = _two_image_pdf(tmp_path / "c.pdf")
    detector = object()
    with mock.patch.object(p2m.pymupdf4llm, "to_markdown", return_value=[{"text": "z"}]) as tm:
        assert p2m.extract_markdown_per_page(pdf, hdr_info=detector) == [(1, "z")]
    tm.assert_called_once_with(str(pdf), page_chunks=True, hdr_info=detector)

    with mock.patch.object(p2m.pymupdf4llm, "to_markdown", return_value=[{"text": "w"}]) as tm2:
        assert p2m.extract_markdown_per_page(pdf, hdr_info=None) == [(1, "w")]
    tm2.assert_called_once_with(str(pdf), page_chunks=True)

    images_dir = tmp_path / "img"
    with mock.patch.object(p2m.pymupdf4llm, "to_markdown", return_value=[{"text": "v"}]) as tm3:
        assert p2m.extract_markdown_per_page(pdf, images_dir=images_dir, hdr_info=detector) == [(1, "v")]
    _, call_kwargs = tm3.call_args
    assert call_kwargs["hdr_info"] is detector
    assert call_kwargs["write_images"] is True
    assert "pages" not in call_kwargs
```

## Implementation Notes

### Pattern to Follow
The existing optional-kwargs pattern in the same function: start from `{"page_chunks": True}` and add keys
only when the caller asked for them (`pdf_to_markdown.py:94-102`), so the default call never changes.

### Key Constraints
- Keyword-only (it sits after the existing `*`), default `None`, type `Any` (pymupdf4llm accepts any
  object with `get_header_id`, a callable, or `False`).
- Never pass `pages=`; never change the order or content of the existing kwargs.
- Hashes in the Delegation Contract were computed on `dev` @ `8dbdb08cbb`; if they are stale at execution
  time, refresh the packet in this file first, then re-run the writer.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:39-126`
- `.venv/lib/python3.12/site-packages/pymupdf4llm/helpers/pymupdf_rag.py:303,415-423` — `hdr_info` dispatch

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `from typing import Any` below `from pathlib import Path` — *why*: the new parameter is typed `Any` and the module has no typing import.
2. Add `hdr_info: Any = None,` below `image_size_limit: float = 0.05,` and its docstring entry — *why*: spec M2 fixes the name, type, default and position.
3. Add the two forwarding lines below the `kwargs` line — *why*: forwarding only when not `None` keeps the default call byte-identical (AC-12).
4. Add `test_hdr_info_forwarded` and run both Validation Commands — *why*: pins forwarding and the unchanged shape.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from pathlib import Path$' packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py)
# AFTER — insert below `from pathlib import Path` (verified: pdf_to_markdown.py:21)
from typing import Any

# occurrences: 1 (verified: grep -c '    image_size_limit: float = 0.05,' packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py)
# AFTER — insert below `    image_size_limit: float = 0.05,` (verified: pdf_to_markdown.py:45)
    hdr_info: Any = None,

# occurrences: 1 (verified: grep -c '            ``pymupdf4llm`` when ``images_dir`` is set. Ignored otherwise.' packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py)
# AFTER — insert below that docstring line (verified: pdf_to_markdown.py:62)
        hdr_info: Header detector forwarded to ``pymupdf4llm.to_markdown`` as
            ``hdr_info`` (an object with ``get_header_id(span, page=None)``,
            e.g. ``LayoutHeaders``). Forwarded only when not ``None``; with
            ``None`` the call is byte-identical to the pre-existing behaviour.

# occurrences: 1 (verified: grep -c '    kwargs: dict\[str, object\] = {"page_chunks": True}' packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py)
# AFTER — insert below `    kwargs: dict[str, object] = {"page_chunks": True}` (verified: pdf_to_markdown.py:94)
    if hdr_info is not None:
        kwargs["hdr_info"] = hdr_info
```
**Why**: four mechanical insertions; the design is complete (spec §3 M2 marks it delegation-eligible).

### `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    assert "pages" not in call_kwargs' packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py)
# AFTER — insert below `    assert "pages" not in call_kwargs` (verified: test_pdf_page_images.py:56), before `def test_extract_page_images_bbox`
# Content: exactly the `impl-test-hdr-info` block of the Delegation Contract above.
```
**Why**: a sibling of the existing call-shape test, reusing `_two_image_pdf` and the same mock pattern.

### FILL IN checklist
- [ ] none — the design is complete; copy the Delegation Contract blocks verbatim

---

## Acceptance Criteria

- [ ] AC-12: `extract_markdown_per_page` without `hdr_info` calls `to_markdown(path, page_chunks=True)` exactly as before; `test_pdf_page_images.py:36` passes unchanged
- [ ] With `hdr_info=obj` the call carries `hdr_info=obj` (also combined with `images_dir`)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py -q` and `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py` is clean (AC-18)

---

## Validation Commands

> Commands a registered test runner recognises — `pytest`, `vitest`, `cargo test`, `parrot e2e` or an
> `[extensions]` entry in `.parrot/test_runners.toml`. pytest: file-level only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_to_markdown.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed.

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py
# test_hdr_info_forwarded — the `impl-test-hdr-info` block above, verbatim:
#   hdr_info=obj  -> to_markdown(str(pdf), page_chunks=True, hdr_info=obj)
#   hdr_info=None -> to_markdown(str(pdf), page_chunks=True)
#   images_dir + hdr_info -> both forwarded, still no "pages"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (never `uv sync` in the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5335 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
