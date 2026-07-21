# TASK-1759: Declare playwright + rapidfuzz (and verify ddgs) in satellite pyproject

**Feature**: FEAT-305 — CompanyResearch — extend CompanyInfoToolkit
**Spec**: `sdd/specs/companyresearch-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements the dependency portion of spec §7 (External Dependencies) and the
> `ddgs`-pin open question (§8). Every downstream task imports `rapidfuzz`
> (fuzzy name validation), `ddgs` (DDG-first search) and needs `playwright`
> installed at runtime for the fetch layer. These deps must land FIRST so the
> other tasks' code can import and their tests can run in the worktree venv.

---

## Scope

- Add `playwright>=1.52` to the satellite package's `scraping` optional-deps
  extra in `packages/ai-parrot-tools/pyproject.toml` (it is currently only in
  core `ai-parrot`; `PlaywrightDriver` needs it at runtime here).
- Add `rapidfuzz>=3.0` as a dependency of the satellite package (used by the
  search layer's fuzzy company-name validation). Choose the extra/section that
  matches how the satellite declares its other runtime deps (e.g. alongside
  `beautifulsoup4`).
- Verify `ddgs` is declared explicitly in the satellite `pyproject.toml`. If it
  only arrives transitively, add an explicit pin (`ddgo.py` imports it directly).
- After editing, install into the active venv so subsequent tasks work:
  `source .venv/bin/activate && uv pip install -e packages/ai-parrot-tools` (and
  `playwright install chromium` if the Playwright browser is not present).

**NOT in scope**: any code changes in `company_info/tool.py`; test files
(TASK-1764); the fuzzy/search/fetch logic itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | Add `playwright>=1.52`, `rapidfuzz>=3.0`; ensure `ddgs` pin |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13 on `dev`.

### Verified facts
```
# ddgs is imported directly by the satellite today:
#   packages/ai-parrot-tools/src/parrot_tools/ddgo.py:11  ->  from ddgs import DDGS
#   packages/ai-parrot-tools/src/parrot_tools/ddgo.py:12  ->  from ddgs.exceptions import DDGSException, RatelimitException
# backoff is a CORE dep already: packages/ai-parrot/pyproject.toml:45 ("backoff==2.2.1")
# beautifulsoup4 is a satellite dep: packages/ai-parrot-tools/pyproject.toml:47 ("beautifulsoup4>=4.12")
# playwright currently lives only in core ai-parrot[agents] (pyproject ~:224 area)
```

### Does NOT Exist
- ~~`fuzzywuzzy`~~ / ~~`rapidfuzz`~~ — NOT installed in either package today
  (grep of both pyprojects). Use `rapidfuzz` (maintained, MIT, no GPL
  levenshtein dep) — do NOT reintroduce flowtask's `fuzzywuzzy`.
- ~~`from duckduckgo_search import DDGS`~~ — the satellite uses the **`ddgs`**
  package, not `duckduckgo_search`.

---

## Implementation Notes

### Key Constraints
- Use `uv` exclusively; ALWAYS `source .venv/bin/activate` first (repo rule).
- Match the version-pin style already used in the satellite pyproject
  (`>=` ranges, not `==`, per the existing `beautifulsoup4>=4.12`).
- Do not touch the core `packages/ai-parrot/pyproject.toml`.

---

## Acceptance Criteria

- [ ] `playwright>=1.52` and `rapidfuzz>=3.0` declared in
      `packages/ai-parrot-tools/pyproject.toml`.
- [ ] `ddgs` is explicitly declared in the satellite pyproject.
- [ ] `source .venv/bin/activate && python -c "import rapidfuzz, ddgs, playwright; print('ok')"` succeeds.
- [ ] `uv pip install -e packages/ai-parrot-tools` completes without error.

---

## Test Specification

> No unit test file for this task. Verification is the import smoke check above.

```bash
source .venv/bin/activate
python -c "import rapidfuzz; from ddgs import DDGS; import playwright; print('deps ok')"
```

---

## Agent Instructions

1. Read the spec §7 for dependency rationale.
2. Verify the current satellite pyproject deps before editing.
3. Implement per scope; install into venv.
4. Verify acceptance criteria.
5. Move this file to `sdd/tasks/completed/`, update the per-spec index to `done`.
6. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-07-14
**Notes**: Added `ddgs>=9.5.2` to the base `dependencies` list (it was already
imported unconditionally in `ddgo.py` and now also in `company_info/tool.py`'s
search layer, but only arrived transitively via `ai-parrot`'s own
`ddgs>=9.5.2` pin — now pinned explicitly in the satellite too). Added
`playwright>=1.52` and `rapidfuzz>=3.0` to the `scraping` extra (alongside
`selenium`/`undetected-chromedriver`/`webdriver-manager`, since that's the
extra tied to `CompanyInfoToolkit`'s browser deps). Verified via
`uv pip install -e packages/ai-parrot-tools[scraping]` and
`python -c "import rapidfuzz; from ddgs import DDGS; import playwright"` —
both succeeded. Chromium browser binary was already present in the venv
(`playwright.sync_api` launch smoke test passed).
**Deviations from spec**: none
