# TASK-1947: Add pytest coverage for para.style is None scenario

**Feature**: FEAT-384 — Fix MSWordLoader NoneType crash on para.style.name access (NAV-9269)
**Spec**: `sdd/specs/fix-msword-loader-none-style.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1946
**Assigned-to**: unassigned

---

## Context

After the one-line guard is applied in TASK-1946, this task adds regression
tests to `tests/loaders/test_mswordloader_none_style.py` ensuring the crash
scenario (NAV-9269) is covered and never regresses. Tests use
`unittest.mock.MagicMock` to simulate python-docx objects — no real `.docx`
files are required.

---

## Scope

- Create `tests/loaders/test_mswordloader_none_style.py` with at minimum four tests:
  1. Paragraph with `style=None` is emitted as plain body text (no crash).
  2. Heading style paragraphs still produce `# heading` markdown.
  3. List style paragraphs still produce `- item` markdown.
  4. A mixed document with None-style and valid-style paragraphs loads without raising.

**NOT in scope**: testing `_load()`, `extract_text()`, or any async path.
Only `docx_to_markdown()` is exercised here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/loaders/test_mswordloader_none_style.py` | CREATE | Pytest tests for None-style guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-loaders/src/parrot_loaders/docx.py:11
from parrot_loaders.docx import MSWordLoader  # or adjust to actual import path
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/docx.py:17
def docx_to_markdown(self, docx_path):
    doc = docx.Document(docx_path)
    ...
    for para in doc.paragraphs:
        style = para.style.name.lower() if para.style is not None else ""
        text = para.text.strip()
```

### Does NOT Exist
- ~~`MSWordLoader.parse()`~~ — method does not exist; use `docx_to_markdown()`
- ~~`MSWordLoader.load_sync()`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow

Patch `docx.Document` at the call site inside `docx_to_markdown`:

```python
from unittest.mock import MagicMock, patch

def make_para(text: str, style_name=None):
    """Helper: returns a mock docx Paragraph."""
    para = MagicMock()
    para.text = text
    if style_name is None:
        para.style = None
    else:
        para.style = MagicMock()
        para.style.name = style_name
    return para

@patch("parrot_loaders.docx.docx.Document")
def test_none_style_paragraph_treated_as_body(mock_doc_cls):
    mock_doc = MagicMock()
    mock_doc.paragraphs = [make_para("Hello world", style_name=None)]
    mock_doc.tables = []
    mock_doc_cls.return_value = mock_doc

    loader = MSWordLoader()
    result = loader.docx_to_markdown("fake.docx")
    assert "Hello world" in result
```

### Key Constraints
- Use `unittest.mock` — do NOT create real `.docx` fixture files.
- Patch `parrot_loaders.docx.docx.Document` (the `docx` module as imported inside `docx.py`).
- Test file must be standalone and not require env vars or external services.

---

## Acceptance Criteria

- [ ] `tests/loaders/test_mswordloader_none_style.py` exists with four or more tests.
- [ ] All four tests pass: `pytest tests/loaders/test_mswordloader_none_style.py -v`.
- [ ] `pytest tests/loaders/ -v` still passes (no regression in existing tests).

---

## Test Specification

```python
# tests/loaders/test_mswordloader_none_style.py
import pytest
from unittest.mock import MagicMock, patch


def make_para(text, style_name=None):
    para = MagicMock()
    para.text = text
    if style_name is None:
        para.style = None
    else:
        para.style = MagicMock()
        para.style.name = style_name
    return para


class TestMSWordLoaderNoneStyle:

    @patch("parrot_loaders.docx.docx.Document")
    def test_none_style_paragraph_treated_as_body(self, mock_doc_cls):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [make_para("Hello world")]
        mock_doc.tables = []
        mock_doc_cls.return_value = mock_doc
        from parrot_loaders.docx import MSWordLoader
        loader = MSWordLoader()
        result = loader.docx_to_markdown("fake.docx")
        assert "Hello world" in result

    @patch("parrot_loaders.docx.docx.Document")
    def test_heading_style_still_works(self, mock_doc_cls):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [make_para("My Heading", style_name="Heading 1")]
        mock_doc.tables = []
        mock_doc_cls.return_value = mock_doc
        from parrot_loaders.docx import MSWordLoader
        loader = MSWordLoader()
        result = loader.docx_to_markdown("fake.docx")
        assert "# My Heading" in result

    @patch("parrot_loaders.docx.docx.Document")
    def test_list_style_still_works(self, mock_doc_cls):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [make_para("List item", style_name="List Bullet")]
        mock_doc.tables = []
        mock_doc_cls.return_value = mock_doc
        from parrot_loaders.docx import MSWordLoader
        loader = MSWordLoader()
        result = loader.docx_to_markdown("fake.docx")
        assert "- List item" in result

    @patch("parrot_loaders.docx.docx.Document")
    def test_mixed_doc_with_none_style(self, mock_doc_cls):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            make_para("Title", style_name="Heading 1"),
            make_para("Orphan paragraph"),          # style=None
            make_para("Normal text", style_name="Normal"),
        ]
        mock_doc.tables = []
        mock_doc_cls.return_value = mock_doc
        from parrot_loaders.docx import MSWordLoader
        loader = MSWordLoader()
        # Must not raise
        result = loader.docx_to_markdown("fake.docx")
        assert "Title" in result
        assert "Orphan paragraph" in result
        assert "Normal text" in result
```

---

## Agent Instructions

1. **Verify** TASK-1946 is in `tasks/completed/` before starting.
2. **Create** `tests/loaders/test_mswordloader_none_style.py` from the scaffold above.
3. **Run** `pytest tests/loaders/test_mswordloader_none_style.py -v` and confirm all pass.
4. **Move** this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
