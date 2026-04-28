# TASK-861: Build `contextual.py` helper module

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of the spec. Provides the pure-function helper that all stores will
call to assemble the text-to-embed plus a traceable header from a
`Document.metadata['document_meta']` payload.

This is the foundational task — every other task in FEAT-127 imports from
this module. It must land first.

Spec sections: §1 Goals (2), §2 Architectural Design, §3 Module 1, §6
Codebase Contract.

---

## Scope

- Create `parrot/stores/utils/contextual.py`.
- Implement `build_contextual_text(document, template, max_header_tokens) -> tuple[str, str]`.
- Export module-level constants `DEFAULT_TEMPLATE`, `DEFAULT_MAX_HEADER_TOKENS`,
  `KNOWN_PLACEHOLDERS`, and the `ContextualTemplate` type alias.
- Render the template against a sanitised view of `document_meta` only;
  never against arbitrary `metadata`.
- Drop `None` and empty-string fields; collapse the resulting separators so
  the rendered header never shows orphan pipes or `"None"`.
- Accept the template as either `str` (formatted via `str.format_map` on a
  defaulted dict) or `Callable[[dict], str]` (called with the
  `document_meta` dict).
- Cap the header at `max_header_tokens` using whitespace tokenisation
  (truncate the header BEFORE concatenating with the chunk content).
- When `document_meta` is missing/empty OR the rendered header is empty
  after collapsing, return `(document.page_content, "")` unchanged.
- Escape any `{` / `}` characters appearing in metadata field VALUES so
  malicious metadata cannot break formatting (per spec §7 risk #1).
- Write unit tests covering every row in spec §4 "Unit Tests" for Module 1
  (rows 1–9).

**NOT in scope**:

- Touching `AbstractStore` or any concrete store. Wiring is TASK-862 / TASK-863+.
- `_apply_contextual_augmentation` — that helper lives on `AbstractStore`
  and belongs to TASK-862.
- Replacing or modifying `LateChunkingProcessor._create_contextual_text`.
- Any embedding-client changes.
- Persisting `contextual_header` into `Document.metadata` — that is the
  responsibility of `_apply_contextual_augmentation` (TASK-862).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/utils/contextual.py` | CREATE | Helper, constants, type alias. |
| `packages/ai-parrot/tests/unit/stores/utils/test_contextual.py` | CREATE | Unit tests for the helper. |
| `packages/ai-parrot/src/parrot/stores/utils/__init__.py` | MODIFY (if needed) | Re-export `build_contextual_text`, `DEFAULT_TEMPLATE`, `DEFAULT_MAX_HEADER_TOKENS` for ergonomic imports. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual
> codebase as of 2026-04-27. Do NOT invent imports or signatures.

### Verified Imports

```python
from parrot.stores.models import Document   # verified: parrot/stores/models.py:21
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                                   # line 21
    page_content: str                                        # line 26
    metadata: Dict[str, Any] = Field(default_factory=dict)   # line 27
```

`document_meta` is a sub-dict that lives at `document.metadata["document_meta"]`
when the loader-side metadata standardisation feature has been merged.
The helper MUST tolerate the key being absent or the dict being empty.

### Existing Sibling Helper (reference only — DO NOT modify)

```python
# packages/ai-parrot/src/parrot/stores/utils/chunking.py:174
class LateChunkingProcessor:
    def _create_contextual_text(
        self, full_text: str, chunk_text: str,
        start_pos: int, end_pos: int,
    ) -> str: ...
```

Mentioned only so the implementer knows there is an unrelated, neighbour-text
augmentation helper next door. The two are orthogonal — see spec §7 risk #6.

### Does NOT Exist

- ~~`parrot.stores.utils.contextual`~~ — created by this task.
- ~~`Document.contextual_header`~~ — top-level Document field, never created.
  The header lives in `metadata['contextual_header']` (and that wiring is
  TASK-862, not here).
- ~~`Document.document_meta`~~ — top-level field. The canonical key is
  `document.metadata["document_meta"]`.
- ~~A `tiktoken` / `transformers` dependency~~ — explicitly NOT used.
  Header capping is whitespace-based per spec §7.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/stores/utils/contextual.py
from typing import Callable, Union
from parrot.stores.models import Document

DEFAULT_TEMPLATE: str = (
    "Title: {title} | Section: {section} | Category: {category}\n\n{content}"
)
DEFAULT_MAX_HEADER_TOKENS: int = 100
KNOWN_PLACEHOLDERS = frozenset({
    "title", "section", "category", "page", "language", "source", "content",
})
ContextualTemplate = Union[str, Callable[[dict], str]]


def build_contextual_text(
    document: Document,
    template: ContextualTemplate = DEFAULT_TEMPLATE,
    max_header_tokens: int = DEFAULT_MAX_HEADER_TOKENS,
) -> tuple[str, str]:
    """Return (text_to_embed, header_used). See spec §2 Data Models."""
    # 1. Pull document_meta safely; tolerate missing.
    # 2. Sanitise values: drop None / "" / non-stringable; escape "{" "}".
    # 3. Render template (str path: str.format_map with default-empty dict).
    # 4. Collapse orphan separators ("Title:  | Section: B" → "Section: B"),
    #    drop empty leading/trailing lines.
    # 5. Whitespace-tokenise the header; truncate to max_header_tokens.
    # 6. If header empty after collapse → return (page_content, "").
    # 7. Else return (header + "\n\n" + page_content, header).
```

### Sanitiser Sketch

```python
class _DefaultEmpty(dict):
    def __missing__(self, key: str) -> str:
        return ""

def _sanitise(meta: dict) -> dict:
    out = {}
    for k, v in meta.items():
        if v is None:
            continue
        sv = str(v).strip()
        if not sv:
            continue
        # Escape braces so nested {placeholders} in metadata cannot re-render.
        out[k] = sv.replace("{", "{{").replace("}", "}}")
    return out
```

### Separator Collapse

The default template is `"Title: {title} | Section: {section} | Category: {category}\n\n{content}"`.
After substitution with empty values you may get `"Title:  | Section: B |  \n\n..."`.
Implement a collapse step that:
- splits on `" | "`,
- drops fragments whose value (after `"label:"`) is empty,
- re-joins with `" | "`,
- strips trailing `" | "` or leading `" | "`.

A regex like `r"\s*\|\s*\|\s*"` won't catch all shapes — prefer the explicit
split/filter/join. Add tests for the partial-fields case (spec §4 row 2).

### Determinism

`build_contextual_text(doc, template)` MUST be a pure function. No timestamp,
no UUID, no logging side effects. Test by calling 100 times and asserting
identical output (spec §4 row 9).

### Header Cap

Whitespace-tokenise the header (`header.split()`) and truncate to
`max_header_tokens` words, then re-join with single spaces. Always preserve
`page_content` byte-for-byte; the cap applies only to the header.

### Callable Template Path

```python
if callable(template):
    rendered_header_or_full = template(meta_view)  # implementer chooses contract
```

The cleanest contract: the callable returns the FULL rendered text (header +
content) and the helper extracts the header by splitting on the first
double-newline. Document this in the helper's docstring. Tests must cover
both cases (spec §4 row 6).

### Logging

None. The helper is pure. Logging happens at the store boundary (TASK-862).

### References in Codebase

- `parrot/stores/utils/chunking.py` — sibling pre-embedding helper, same
  module, same import style.
- `parrot/stores/models.py` — `Document` definition.

---

## Acceptance Criteria

- [ ] `parrot/stores/utils/contextual.py` exists and exports
      `build_contextual_text`, `DEFAULT_TEMPLATE`, `DEFAULT_MAX_HEADER_TOKENS`,
      `KNOWN_PLACEHOLDERS`, `ContextualTemplate`.
- [ ] `from parrot.stores.utils.contextual import build_contextual_text` works.
- [ ] All Module 1 unit tests in spec §4 pass:
      `pytest packages/ai-parrot/tests/unit/stores/utils/test_contextual.py -v`
- [ ] `Document.page_content` is byte-equal before and after every helper call
      (asserted in tests).
- [ ] Helper raises NO exception on empty meta, missing meta key, malicious
      `{...}` in values, non-stringable values (e.g. integers — they get
      `str()`'d), or unknown placeholders in the template.
- [ ] No new dependency added to `pyproject.toml`. Stdlib + Pydantic only.
- [ ] `ruff check packages/ai-parrot/src/parrot/stores/utils/contextual.py`
      passes.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/stores/utils/test_contextual.py
import pytest
from parrot.stores.models import Document
from parrot.stores.utils.contextual import (
    build_contextual_text,
    DEFAULT_TEMPLATE,
    DEFAULT_MAX_HEADER_TOKENS,
)


@pytest.fixture
def doc_full():
    return Document(
        page_content="You will receive it on the 15th of every month.",
        metadata={"document_meta": {
            "title": "Employee Handbook",
            "section": "Compensation",
            "category": "HR Policy",
            "language": "en",
        }},
    )


@pytest.fixture
def doc_partial():
    return Document(
        page_content="Body.",
        metadata={"document_meta": {"title": "Only Title"}},
    )


@pytest.fixture
def doc_empty():
    return Document(page_content="Standalone passage.", metadata={})


class TestBuildContextualText:
    def test_all_fields_present(self, doc_full):
        text, header = build_contextual_text(doc_full)
        assert "Title: Employee Handbook" in header
        assert "Section: Compensation" in header
        assert "Category: HR Policy" in header
        assert text.endswith(doc_full.page_content)

    def test_partial_fields_no_orphan_pipes(self, doc_partial):
        text, header = build_contextual_text(doc_partial)
        assert header == "Title: Only Title"
        assert " |  " not in header
        assert "None" not in header
        assert text.endswith(doc_partial.page_content)

    def test_no_meta(self, doc_empty):
        text, header = build_contextual_text(doc_empty)
        assert text == doc_empty.page_content
        assert header == ""

    def test_skips_none_and_empty_string(self):
        doc = Document(page_content="x", metadata={"document_meta": {
            "title": None, "section": "", "category": "C",
        }})
        _, header = build_contextual_text(doc)
        assert header == "Category: C"

    def test_custom_string_template(self, doc_full):
        text, _ = build_contextual_text(doc_full, template="[{title}] {content}")
        assert text.startswith("[Employee Handbook] ")

    def test_custom_callable_template(self, doc_full):
        cb = lambda meta: f"<<{meta.get('title')}>>\n\nBODY"
        text, header = build_contextual_text(doc_full, template=cb)
        assert "<<Employee Handbook>>" in header
        assert text.endswith("BODY")

    def test_unknown_placeholder_renders_empty(self, doc_full):
        text, _ = build_contextual_text(doc_full, template="{nonexistent}|{content}")
        assert "nonexistent" not in text
        assert text.endswith(doc_full.page_content)

    def test_caps_header_tokens(self):
        long_title = " ".join(["Word"] * 500)
        doc = Document(page_content="body", metadata={"document_meta": {"title": long_title}})
        _, header = build_contextual_text(doc, max_header_tokens=10)
        assert len(header.split()) <= 12  # "Title:" + cap

    def test_is_deterministic(self, doc_full):
        results = {build_contextual_text(doc_full) for _ in range(100)}
        assert len(results) == 1

    def test_does_not_mutate_page_content(self, doc_full):
        before = doc_full.page_content
        build_contextual_text(doc_full)
        assert doc_full.page_content == before

    def test_metadata_brace_injection_is_neutralised(self):
        doc = Document(page_content="x", metadata={"document_meta": {
            "title": "{content}{content}{content}",
        }})
        text, header = build_contextual_text(doc)
        # The literal {content} must NOT have been re-substituted.
        assert "{content}" in header
        assert text.count("x") == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/contextual-embedding-headers.spec.md` for full context.
2. **No dependencies** — this is a foundational task.
3. **Verify the Codebase Contract** — confirm `parrot/stores/models.py` still
   exports `Document` with `page_content` and `metadata` fields.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID.
5. **Implement** the helper following the patterns above.
6. **Run tests** — all must pass.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker agent
**Date**: 2026-04-27
**Notes**: Created parrot/stores/utils/contextual.py with build_contextual_text(), DEFAULT_TEMPLATE, DEFAULT_MAX_HEADER_TOKENS, KNOWN_PLACEHOLDERS, ContextualTemplate. Updated utils/__init__.py to re-export. 14/14 unit tests pass.
**Deviations from spec**: none
