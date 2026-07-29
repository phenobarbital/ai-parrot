# TASK-1943: Add pytest coverage for para.style is None scenario

**Feature**: fix-mswordloader-none-name
**Feature ID**: FEAT-382
**Spec**: sdd/specs/fix-mswordloader-none-name.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Depends-on**: TASK-1942
**Assigned-to**: unassigned

## Context

After TASK-1942 lands the one-line fix, this task ensures the fix is covered
by an automated test so it cannot regress silently. The test mocks
`docx.Document` to return a paragraph whose `.style` is `None`.

## Scope

Create `tests/loaders/test_mswordloader_none_style.py` with at least two tests:
1. A paragraph with `style=None` does not raise and its text is included in the
   output.
2. A mix of styled and un-styled paragraphs in the same document is handled
   correctly.

## Files to Create/Modify

- `tests/loaders/test_mswordloader_none_style.py` — new file

## Implementation Notes

Use `unittest.mock.MagicMock` or `pytest-mock`'s `mocker` to patch
`docx.Document` so it returns a controlled list of fake paragraphs.

Minimal test scaffold:

```python
from unittest.mock import MagicMock, patch
from parrot_loaders.docx import MSWordLoader


def _make_para(text: str, style_name: str | None):
    para = MagicMock()
    para.text = text
    if style_name is None:
        para.style = None
    else:
        para.style = MagicMock()
        para.style.name = style_name
    return para


@patch("parrot_loaders.docx.docx.Document")
def test_none_style_does_not_raise(mock_doc):
    doc = MagicMock()
    doc.paragraphs = [_make_para("Hello world", None)]
    doc.tables = []
    mock_doc.return_value = doc

    loader = MSWordLoader()
    result = loader.docx_to_markdown("/fake/path.docx")
    assert "Hello world" in result


@patch("parrot_loaders.docx.docx.Document")
def test_mixed_styles_handled(mock_doc):
    doc = MagicMock()
    doc.paragraphs = [
        _make_para("Normal text", None),
        _make_para("A Heading", "Heading 1"),
        _make_para("List item", "List Bullet"),
    ]
    doc.tables = []
    mock_doc.return_value = doc

    loader = MSWordLoader()
    result = loader.docx_to_markdown("/fake/path.docx")
    assert "Normal text" in result
    assert "# A Heading" in result
    assert "- List item" in result
```

## Acceptance Criteria

- [ ] `tests/loaders/test_mswordloader_none_style.py` exists with at least two
      passing test functions.
- [ ] `pytest tests/loaders/test_mswordloader_none_style.py -v` exits 0.
- [ ] `pytest -q` (full suite) exits 0.
- [ ] `ruff check tests/loaders/test_mswordloader_none_style.py` exits 0.

## Output

When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/index/fix-mswordloader-none-name.json` status to "done"
3. Add a brief completion note below.

### Completion Note

(Agent fills this in when done)
