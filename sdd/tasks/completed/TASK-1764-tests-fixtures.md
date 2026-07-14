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
class CompanyInfoToolkit(AbstractToolkit):           # as landed by TASK-1759..1763 in this worktree
    async def research_company(company_name, sources=None, return_json=False)  # TASK-1763, @tool_schema(ResearchCompanyInput)
    async def scrape_visualvisitor(company_name, return_json=False)      # TASK-1762
    async def scrape_zoominfo/explorium/leadiq/rocketreach/siccode(...)  # existing, now call _search_company_url
    def _validate_search_hit(self, title, url, company_name, keywords) -> bool           # TASK-1760 (sync)
    async def _search_company_url(self, company_name, site_config) -> Optional[str]      # TASK-1760 — ASYNC (contract corrected), must be awaited
    async def _fetch_page(self, url, custom_user_agent=None) -> Optional[BeautifulSoup]  # TASK-1761
COMPANY_SOURCES: Dict[str, SourceConfig]             # module-level registry (NOT self._sources)
DEFAULT_SOURCE_PRIORITY: List[str]                   # module-level default priority order (TASK-1763)
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

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-07-14
**Notes**: Corrected the Codebase Contract (module-level `COMPANY_SOURCES`/
`DEFAULT_SOURCE_PRIORITY`, `_search_company_url` is async) before writing
tests. Created `packages/ai-parrot-tools/tests/company_info/` with
`__init__.py`, `conftest.py` (6 HTML fixtures loaders — leadiq/rocketreach/
explorium/siccode/visualvisitor/zoominfo — plus a `toolkit` factory fixture
and `mock_driver`/`mock_search` monkeypatch helpers that replace
`_fetch_page`/`_fetch_page_with_selenium` and `_search_company_url`
respectively, so no test ever launches a browser or hits the network),
`fixtures/*.html` (6 minimal hand-built HTML fixtures, each verified
directly against the real BeautifulSoup selectors in `tool.py` before
being wired into a test), and `test_company_info.py` implementing every
§4 row plus a few extra edge-case tests (keyword-mismatch rejection, DDG
success without fallback, fetch-failure returns `None`,
`research_company` never raises on an unexpected `scrape_*` exception,
`scrape_visualvisitor` no-hit path, ctor back-compat). Did NOT modify
`pyproject.toml`/`pytest.ini` to register the `live` marker — it was
already registered in the repo-root `pytest.ini` (verified: `markers =
... live: ...`), so no satellite-level change was needed. Added a
`pytest_collection_modifyitems` hook in `conftest.py` that skips
`live`-marked tests unless `-m live` is explicitly passed (mirrors the
`real_llm` skip-by-default pattern already used in
`packages/ai-parrot/tests/conftest.py`) — this was necessary because,
without it, `test_live_smoke` was observed to actually run and pass
against the real internet in this sandboxed environment on a plain
`pytest packages/ai-parrot-tools/tests/company_info/ -v`, which would
violate goal G6 ("no live scraping in CI") wherever network access isn't
available or isn't desired. Verified all acceptance criteria: `pytest
packages/ai-parrot-tools/tests/company_info/ -v` → 23 passed, 1 skipped
(the live test); `pytest ... -m live` → 1 passed, 23 deselected (real
`research_company("PetSmart")` call succeeded in this environment,
confirming current selectors are still valid against the live site as of
this run); `ruff check packages/ai-parrot-tools/tests/company_info/` →
clean.
**Deviations from spec**: none — the pyproject/pytest.ini marker
registration bullet in "Files to Create/Modify" turned out to be a no-op
given the marker was already globally registered; the
`pytest_collection_modifyitems` skip-by-default hook was added to
`conftest.py` (not listed in the original Files table) to actually
satisfy the "default run skips it" acceptance criterion, since a bare
`@pytest.mark.live` alone does not skip by default in pytest — only
selects/deselects when `-m` is passed.
