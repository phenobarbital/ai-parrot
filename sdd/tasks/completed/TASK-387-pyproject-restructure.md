# TASK-387: pyproject.toml Dependency Restructuring

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-386
**Assigned-to**: unassigned

---

## Context

This is the central packaging task for FEAT-056. It restructures `pyproject.toml` to move ~30 heavy dependencies from `[project.dependencies]` to new/existing `[project.optional-dependencies]` extras groups. This must be done carefully since it changes what gets installed by default.

Implements: Spec Module 2 — pyproject.toml Restructuring.

---

## Scope

- Audit all 57 current hard dependencies and classify each as "core" or "optional + which extra group".
- Move optional dependencies to extras groups per the table below.
- Keep core dependencies minimal: navconfig, pandas, navigator-api, asyncdb[default], pydantic, aiohttp, click, typing-extensions, PyYAML, python-datamodel, backoff, tiktoken, markdown2, tabulate, brotli, urllib3, xmltodict, prance, openapi-schema-validator, openapi-spec-validator, python-statemachine, aiohttp-swagger3, aiohttp-cors, aiohttp-sse-client, cel-python, questionary, psutil, async-notify, ddgs, pywa, Cython.
- Create/update these extras groups:
  - `db` — querysource, psycopg-binary, asyncdb[bigquery,mongodb,arangodb,influxdb,boto3]
  - `bigquery` — google-cloud-bigquery
  - `pdf` — weasyprint, fpdf, markitdown, python-docx
  - `ocr` — pytesseract
  - `audio` — pydub
  - `finance` — ta-lib, pandas-datareader
  - `visualization` — matplotlib, seaborn, numexpr
  - `flowtask` — flowtask
  - `scheduler` — apscheduler
  - `arango` — python-arango-async
  - `reddit` — praw
  - `all` — meta extra pulling all of the above + existing groups (agents, loaders, embeddings, ml-heavy, charts)
- Update `asyncdb` from `asyncdb[bigquery,mongodb,arangodb,influxdb,boto3]` in hard deps to `asyncdb[default]`.
- Remove `flowtask` from hard dependencies.
- Remove `apscheduler` from hard dependencies.
- Verify that `pip install ai-parrot` in a fresh venv has no system library requirements.

**NOT in scope**: Changing any Python source files (that's TASK-388+). Only `pyproject.toml` changes here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Restructure dependencies and optional-dependencies sections |

---

## Implementation Notes

### Decisions from Open Questions (resolved by author)

- `asyncdb[default]` stays in core (not full asyncdb[bigquery,mongodb,...])
- `querysource` moves to `[db]` extra
- `pandas` stays in core
- `flowtask` moves to `[flowtask]` extra
- `apscheduler` moves to `[scheduler]` extra

### Dependencies to MOVE from core to extras

| Dependency | Target Extra |
|---|---|
| `faiss-cpu` | `embeddings` |
| `sentencepiece` | `embeddings` |
| `psycopg-binary` | `db` |
| `google-cloud-bigquery` | `bigquery` |
| `numexpr` | `visualization` |
| `fpdf` | `pdf` |
| `python-docx` | `pdf` |
| `matplotlib` | `visualization` |
| `seaborn` | `visualization` |
| `pydub` | `audio` |
| `markitdown` | `pdf` |
| `pytesseract` | `ocr` |
| `python-arango-async` | `arango` |
| `weasyprint` | `pdf` |
| `querysource` | `db` |
| `praw` | `reddit` |
| `pandas-datareader` | `finance` |
| `ta-lib` | `finance` |
| `flowtask` | `flowtask` |
| `apscheduler` | `scheduler` |
| `rank_bm25` | `embeddings` |
| `jq` | `db` |
| `aioquic` | keep or move to `http3` |
| `pylsqpack` | keep or move to `http3` |

### Dependencies to KEEP in core

`Cython`, `pandas`, `tabulate`, `markdown2`, `python-datamodel`, `backoff`, `typing-extensions`, `navconfig[default]`, `navigator-auth`, `navigator-session`, `navigator-api[uvloop,locale]`, `click`, `async-notify[all]`, `ddgs`, `xmltodict`, `python-statemachine`, `aiohttp-swagger3`, `PyYAML`, `asyncdb[default]`, `brotli`, `urllib3`, `aiohttp-sse-client`, `prance`, `openapi-schema-validator`, `openapi-spec-validator`, `aiohttp-cors`, `pywa`, `cel-python`, `questionary`, `tiktoken`, `psutil`, `pydantic`.

### Key Constraints
- The `all` extra must include every other extra so `pip install ai-parrot[all]` restores full functionality
- Existing extras (`agents`, `agents-lite`, `loaders`, `embeddings`, `ml-heavy`, `charts`, `mcp`) must not break
- Version pins must be preserved exactly

---

## Acceptance Criteria

- [ ] `pip install ai-parrot` no longer installs flowtask, weasyprint, pytesseract, ta-lib, pydub, matplotlib, seaborn, faiss-cpu, psycopg-binary, google-cloud-bigquery, python-arango-async, querysource, praw, pandas-datareader, apscheduler
- [ ] `pip install ai-parrot[all]` installs all the above
- [ ] `pip install ai-parrot[db]` installs querysource, psycopg-binary, asyncdb extras
- [ ] `pip install ai-parrot[pdf]` installs weasyprint, fpdf, markitdown, python-docx
- [ ] Existing extras groups (agents, loaders, etc.) still work
- [ ] No duplicate dependencies across groups (or documented if intentional)
- [ ] Version pins preserved from current pyproject.toml

---

## Test Specification

```bash
# Manual verification (no pytest needed for this task)
# In a fresh venv:
pip install -e .
pip list | grep -i "flowtask\|weasyprint\|pytesseract\|ta-lib"
# Should return empty

pip install -e ".[all]"
pip list | grep -i "flowtask\|weasyprint\|pytesseract"
# Should show all packages
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 is completed
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-387-pyproject-restructure.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-03-22
**Notes**: Moved 15 heavy packages from core to extras. Added 11 new extras groups (db, bigquery, pdf, ocr, audio, finance, visualization, flowtask, scheduler, arango, reddit). Updated 'all' meta-extra to include all groups. asyncdb changed from [bigquery,mongodb,...] to [default] in core.

**Deviations from spec**: pandas pinned without version (spec says "pandas stays in core" but no version was specified for it in the original toml either)
