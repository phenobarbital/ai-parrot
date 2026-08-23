# TASK-2386: session_actions file upload & download actions

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2384
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** (Goal G1), third slice: `upload_file` and
`wait_for_download`.

These carry the document half of a bookkeeping workflow — attaching a receipt
to an expense, pulling an issued invoice back out as a PDF. Both are currently
stubbed on the modern path (`executor.py:298-311`).

Implements spec **Module 1 (part 3 of 3)**.

---

## Scope

- Implement `exec_upload_file(driver, action) -> bool` by lifting
  `WebScrapingTool._upload_file` (tool.py:2336), supporting both the single
  `file_path` and the `multiple_files` / `file_paths` forms, plus the
  `wait_after_upload` selector and `wait_timeout`.
- Implement `exec_wait_for_download(driver, action) -> bool` by lifting
  `WebScrapingTool._wait_for_download` (tool.py:2202), honouring
  `filename_pattern`, `download_path`, `timeout`, `move_to` and `delete_after`.
- Validate that `file_path` exists before touching the browser, and reject
  paths that escape a configured download/upload root.
- Write unit tests using `tmp_path`.

**NOT in scope**: wiring into the dispatcher (TASK-2387); the bank-statement
Excel ingestion that will *use* upload (TASK-2392).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py` | MODIFY | Add the two file actions |
| `packages/ai-parrot-tools/tests/scraping/test_session_actions_files.py` | CREATE | Unit tests with tmp_path |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver   # verified: drivers/abstract.py:37
from parrot_tools.scraping.models import (                        # verified: scraping/models.py
    UploadFile,         # line 633
    WaitForDownload,    # line 612
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
class WaitForDownload(BrowserAction):               # line 612
    filename_pattern: Optional[str] = None          # e.g. "*.pdf", "report*.xlsx"; None = any
    download_path: Optional[str] = None             # None = browser default dir
    timeout: int = 60
    move_to: Optional[str] = None
    delete_after: bool = False

class UploadFile(BrowserAction):                    # line 633
    selector: str                                   # REQUIRED
    file_path: str                                  # REQUIRED
    wait_after_upload: Optional[str] = None
    wait_timeout: int = 10
    multiple_files: bool = False
    file_paths: Optional[List[str]] = None

# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py — SOURCE to lift from
async def _wait_for_download(self, action: WaitForDownload) -> bool:  # line 2202
async def _upload_file(self, action: UploadFile) -> bool:             # line 2336

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):                          # line 37
    async def navigate(self, url: str, timeout: int = 30) -> None: ...   # line 47
    async def click(self, selector: str, timeout: int = 10) -> None: ... # line 70
    async def fill(...) -> None: ...                                     # line 79
    async def select_option(...) -> None: ...                            # line 91
    async def hover(self, selector: str, timeout: int = 10) -> None: ... # line 111
    async def press_key(self, key: str) -> None: ...                     # line 120
    async def get_page_source(self) -> str: ...                          # line 130
    async def get_text(self, selector: str, timeout: int = 10) -> str: ...# line 134
    async def wait_for_selector(...) -> None: ...                        # line 185
    async def wait_for_navigation(self, timeout: int = 30) -> None: ...  # line 198
    async def execute_script(self, script: str, *args) -> Any: ...       # line 220
    async def evaluate(self, expression: str) -> Any: ...                # line 232
    def current_url(self) -> str: ...                                    # line 246
    async def save_pdf(self, path: str) -> bytes: ...                    # line 284
```

### Does NOT Exist

- ~~`AbstractDriver.upload_file()`~~ / ~~`AbstractDriver.set_input_files()`~~ — NOT on the driver ABC (drivers/abstract.py:37-337). Follow whatever mechanism `tool.py:2336` already uses.
- ~~`AbstractDriver.download()`~~ / ~~`AbstractDriver.wait_for_download()`~~ — not on the ABC either. Download detection is filesystem polling, as in `tool.py:2202`.
- ~~`UploadFile.files`~~ — the plural field is `file_paths` (line 640), and it is gated by `multiple_files`.

---

## Implementation Notes

### Key Constraints
- Validate `file_path` / `file_paths` exist **before** interacting with the
  browser, so a typo fails fast with a clear message.
- Reject path traversal outside the configured root. These actions will later
  be driven by JSON authored outside the repo (the private plans directory), so
  treat their paths as untrusted input.
- `wait_for_download` polls the filesystem; keep the poll interval modest and
  always honour `timeout`. Return `False` on timeout — never `True`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] Single-file and `multiple_files` upload paths both work
- [ ] `wait_after_upload` selector is awaited with `wait_timeout` when set
- [ ] `filename_pattern` matching, `move_to` and `delete_after` all behave per the model's field docs
- [ ] A non-existent `file_path` fails before any driver call, with the path in the message
- [ ] A path escaping the configured root is rejected
- [ ] Download timeout returns `False`
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_session_actions_files.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.scraping.session_actions import exec_upload_file, exec_wait_for_download
from parrot_tools.scraping.models import UploadFile, WaitForDownload


class TestUpload:
    async def test_single_file(self, mock_driver, tmp_path):
        f = tmp_path / "receipt.pdf"; f.write_bytes(b"%PDF-")
        assert await exec_upload_file(mock_driver, UploadFile(selector="#f", file_path=str(f))) is True

    async def test_missing_file_fails_before_driver(self, mock_driver):
        action = UploadFile(selector="#f", file_path="/nope/missing.pdf")
        assert await exec_upload_file(mock_driver, action) is False
        mock_driver.click.assert_not_awaited()


class TestDownload:
    async def test_pattern_and_move_to(self, mock_driver, tmp_path):
        dl = tmp_path / "dl"; dl.mkdir(); dest = tmp_path / "kept"; dest.mkdir()
        (dl / "factura-001.pdf").write_bytes(b"%PDF-")
        action = WaitForDownload(filename_pattern="*.pdf", download_path=str(dl),
                                 move_to=str(dest), timeout=2)
        assert await exec_wait_for_download(mock_driver, action) is True
        assert (dest / "factura-001.pdf").exists()

    async def test_timeout_returns_false(self, mock_driver, tmp_path):
        action = WaitForDownload(download_path=str(tmp_path), timeout=1)
        assert await exec_wait_for_download(mock_driver, action) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2386-session-actions-file-transfer.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
