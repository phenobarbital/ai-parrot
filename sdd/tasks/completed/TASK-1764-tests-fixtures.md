# TASK-1764: Tests + recorded-HTML fixtures for company_info

**Feature**: FEAT-305 — CompanyResearch — extend CompanyInfoToolkit
**Spec**: `sdd/specs/companyresearch-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1760, TASK-1761, TASK-1762, TASK-1763
**Assigned-to**: unassigned

---

## Context

> Implements the test portion of spec Module 5 (§3) and the full Test
> Specification (§4). No test directory exists for `company_info` yet — this
> task creates it. Tests run against recorded HTML fixtures only: no live
> scraping in CI (goal G6). A single opt-in live smoke test is gated behind
> `-m live`.

---

## Scope

Create `packages/ai-parrot-tools/tests/company_info/`:

- **`conftest.py`** with fixtures:
  - `leadiq_html`, `rocketreach_html`, `explorium_html`, `siccode_html`,
    `visualvisitor_html`, `zoominfo_html` — recorded page HTML per source
    (stored as files under a `fixtures/` subdir, loaded by the fixture).
  - `mock_driver(monkeypatch)` — patches `driver_context`/`_fetch_page` to yield
    fixture HTML without launching a browser.
  - `mock_search(monkeypatch)` — patches DDG/`_google_site_search` to return
    canned hits.
- **Unit tests** covering every row of spec §4:
  - `test_source_configs_complete`, `test_validate_hit_exact/fuzzy/reject`,
    `test_search_ddg_first_google_fallback`, `test_url_suffix_cleanup` (Module 1)
  - `test_fetch_uses_playwright_config` (Module 2)
  - `test_scrape_visualvisitor_fixture` (Module 3)
  - `test_each_source_fixture` — existing 5 extractors still parse fixture HTML
  - `test_research_company_first_success`, `test_research_company_sources_param`,
    `test_research_company_all_fail` (Module 4)
  - `test_toolkit_tools_exposed` (integration)
- **Live smoke test** `test_live_smoke`, marked `@pytest.mark.live`, skipped by
  default in CI (one real `research_company("PetSmart")` for manual selector
  validation). Register the `live` marker in the satellite pytest config if not
  already present.

**NOT in scope**: implementation code (TASK-1760..1763); dependency declarations
(TASK-1759).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/company_info/conftest.py` | CREATE | Fixtures + monkeypatch mocks |
| `packages/ai-parrot-tools/tests/company_info/fixtures/*.html` | CREATE | Recorded HTML per source |
| `packages/ai-parrot-tools/tests/company_info/test_company_info.py` | CREATE | Unit + integration tests |
| `packages/ai-parrot-tools/pyproject.toml` (or `pytest.ini`) | MODIFY | Register `live` marker if absent |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13 on `dev`.

### Verified Imports
```python
from parrot_tools.company_info import CompanyInfoToolkit, CompanyInfo  # __init__.py:1
import pytest
# pytest-asyncio is the async test runner used repo-wide (repo testing rules)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py
class CompanyInfoToolkit(AbstractToolkit):           # line 163
    async def research_company(...)                  # TASK-1763
    async def scrape_visualvisitor(...)              # TASK-1762
    async def scrape_zoominfo/explorium/leadiq/rocketreach/siccode(...)  # existing
    def _validate_search_hit(...)                    # TASK-1760
    def _search_company_url(...)                     # TASK-1760
    async def _fetch_page(...)                       # TASK-1761
# tool exposure: AbstractToolkit.get_tools()  ->  parrot/tools/toolkit.py:207
```

### Does NOT Exist
- No tests exist under `packages/ai-parrot-tools/tests/` for company_info
  (verified via find 2026-07-13) — this task creates the directory.
- ~~`from duckduckgo_search import DDGS`~~ — mock the `ddgs` path instead.

---

## Implementation Notes

### Key Constraints
- Fixtures only — NO network calls in the default test run.
- `test_research_company_first_success` MUST assert the third source's scrape
  method was NOT called after the second succeeds (use a spy/mock call count).
- `test_fetch_uses_playwright_config` asserts the `DriverConfig` handed to
  `driver_context` has `driver_type == "playwright"` (patch `driver_context`).
- Use `pytest-asyncio` for the async tests; `self.logger`-style assertions not
  required.
- Keep recorded HTML minimal — just enough markup to exercise each parser's
  selectors.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — DDG usage to mock.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:750` —
  `driver_context` usage shape to patch.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-tools/tests/company_info/ -v` passes with
      fixtures only (no network).
- [ ] Every §4 unit test row is implemented and passing.
- [ ] `test_research_company_first_success` proves later sources are not called
      after a success.
- [ ] `test_toolkit_tools_exposed` confirms `research_company` +
      `scrape_visualvisitor` are in `get_tools()`.
- [ ] Live test is opt-in only: `-m live` runs it, default run skips it.
- [ ] `ruff check packages/ai-parrot-tools/tests/company_info/` clean.

---

## Test Specification

> This task IS the test suite — implement the full §4 table. Skeleton:

```python
import pytest
from parrot_tools.company_info import CompanyInfoToolkit, CompanyInfo


class TestSearchLayer:
    def test_source_configs_complete(self): ...
    def test_validate_hit_exact(self): ...
    def test_validate_hit_fuzzy(self): ...
    def test_validate_hit_reject(self): ...
    async def test_search_ddg_first_google_fallback(self, monkeypatch): ...
    def test_url_suffix_cleanup(self): ...


class TestResearchCompany:
    async def test_research_company_first_success(self, mock_driver, mock_search): ...
    async def test_research_company_sources_param(self): ...
    async def test_research_company_all_fail(self, mock_driver, mock_search): ...


class TestToolkitExposure:
    def test_toolkit_tools_exposed(self): ...

    @pytest.mark.live
    async def test_live_smoke(self):
        result = await CompanyInfoToolkit().research_company("PetSmart")
        assert result.scrape_status == "success"
```

---

## Agent Instructions

1. Read spec §4 (full Test Specification) and §6 (Codebase Contract).
2. Verify TASK-1760..1763 are in `sdd/tasks/completed/`.
3. Verify the Codebase Contract against the now-implemented methods.
4. Implement per scope; record minimal HTML fixtures.
5. Run `pytest packages/ai-parrot-tools/tests/company_info/ -v` — must pass.
6. Move this file to `sdd/tasks/completed/`; update the per-spec index to `done`.
7. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
