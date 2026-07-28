# TASK-1945: Add pytest coverage for para.style is None scenario

**Feature**: fix-msword-loader-none-name
**Feature ID**: FEAT-383
**Spec**: sdd/specs/fix-msword-loader-none-name.spec.md
**Status**: [ ] pending
**Priority**: high
**Depends-on**: TASK-1944
**Assigned-to**: unassigned

## Context

TASK-1944 applies the None-guard fix.  This task adds a pytest test that
exercises the `para.style is None` code path to prevent regressions and
satisfy the acceptance criterion in the spec.

Jira: NAV-9269

## Scope

Create `tests/loaders/test_mswordloader_none_style.py` with a test that
mocks a `docx.Document` containing one paragraph with `style = None` and
verifies that `MSWordLoader.docx_to_markdown()` returns a string without
raising.

## Files to Create/Modify

- `tests/loaders/test_mswordloader_none_style.py` — new file

## Implementation Notes

Use `unittest.mock.MagicMock` / `unittest.mock.patch` to mock
`docx.Document` so no real `.docx` file is needed:

```python
from unittest.mock import MagicMock, patch
from parrot_loaders.docx import MSWordLoader

def test_docx_to_markdown_none_style():
    mock_para = MagicMock()
    mock_para.style = None
    mock_para.text = "Paragraph with missing style"

    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para]
    mock_doc.tables = []

    with patch("parrot_loaders.docx.docx.Document", return_value=mock_doc):
        loader = MSWordLoader()
        result = loader.docx_to_markdown("/fake/path.docx")

    assert "Paragraph with missing style" in result
```

## Reference Code

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — implementation
  under test
- `tests/loaders/test_docx_loader_fix.py` — existing loader test patterns

## Acceptance Criteria

- [ ] `tests/loaders/test_mswordloader_none_style.py` exists and contains at
      least one test.
- [ ] The test passes with `pytest tests/loaders/test_mswordloader_none_style.py -v`.
- [ ] `pytest -q` exits 0 (full suite passes).

## Output

When complete, move this file to `sdd/tasks/completed/` and update
`sdd/tasks/index/fix-msword-loader-none-name.json` status to "done".

### Completion Note

(Agent fills this in when done)
