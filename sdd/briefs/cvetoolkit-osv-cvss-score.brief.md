---
kind: brief
slug: cvetoolkit-osv-cvss-score
key: c216e0c0eb2b
base_branch: dev
source:
  type: ledger
  ref: issue:c216e0c0eb2b
  url: null
jira_issue_key: null
ledger_issue: issue:c216e0c0eb2b
created: '2026-11-01'
---

# Brief: Score OSV CVSS vectors so severity is not UNKNOWN without NVD

## Problem

Ledger `issue:c216e0c0eb2b` (bug, minor, discovered from spec:FEAT-778 code review):

> CVEToolkit._parse_osv creates CVSS(score=0.0) from the OSV vector string; _lookup then derives
> severity from positive scores only, so with enrich_nvd=False or an NVD failure the record has a
> vector but severity UNKNOWN. Suggested fix: compute the base score from the vector or carry
> score=None and derive severity from it. Found in code review of FEAT-778; derived from reading,
> not reproduced.

Effect: `lookup_cve` / `search_cves` / `download_cve` report `severity: unknown` and `cvss: 3.1 0.0 …`
for every OSV-only record (NVD disabled, rate-limited (429), timed out, or with no metrics), even though
OSV gave a full CVSS vector.

## Root cause

`CVEToolkit._parse_osv` keeps the OSV vector but never scores it. It hard-codes `score=0.0`
(`packages/ai-parrot-tools/src/parrot_tools/security/cve/toolkit.py:289`). `_lookup` keeps only scores
`> 0` (`toolkit.py:258`) before calling `severity_from_score`
(`toolkit.py:259`), so a placeholder 0.0 becomes `None`, which maps to `SeverityLevel.UNKNOWN`
(`packages/ai-parrot-tools/src/parrot_tools/security/cve/models.py:120-121`). NVD enrichment hides the
problem only when it succeeds: `_merge_nvd` replaces the OSV entry with the NVD one carrying `baseScore`
(`toolkit.py:333-341`). `CVSS.score` is typed as a plain `float` (`models.py:40`), so it cannot say
"not computed".

## Research findings

- Blast radius of `_parse_osv`: `_lookup` → `lookup_cve`, `download_cve`. `search_cves` calls `_parse_osv`
  directly (`toolkit.py:141`). All are in one file. Tests are in
  `packages/ai-parrot-tools/tests/security/cve/test_cve_toolkit.py`.
- Only one other place reads `CVSS.score`: the markdown render, `toolkit.py:230`
  (`meta_value(c.score)`, i.e. `str(...)`). A `None` score would print `None`.
- No CVSS library is installed in the venv or declared in any `pyproject.toml`. Search: `uv pip list | grep -i cvss`
  gave no result, and `grep cvss **/pyproject.toml` gave no result.
- Test oracle: the OSV fixture `tests/security/cve/fixtures/osv_CVE-2026-98432.json` has
  `CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:H/I:N/A:N`. Its CVSS 3.1 base score is **5.3 (MEDIUM)**, the
  same value as the NVD fixture's `baseScore` that `test_lookup_cve_merges_osv_and_nvd` asserts.
- Related open ledger issue on the same file: `issue:b26901f15d12` (malformed NVD/OSV bodies raise,
  no response size cap). It is a separate issue and not in scope here.

## Assumptions

(`/sdd-brief` ran without an interview round. These decisions came from research and conventions.)

1. **Compute CVSS 3.0/3.1 base scores in-house.** Do not add a dependency. The 3.x base formula is
   short and fully specified by FIRST. The only PyPI implementation (`cvss`) is LGPL-3.0, and pulling it in
   for a minor fix is not justified.
2. **CVSS 4.0 vectors from OSV get `score=None`.** 4.0 scoring needs the macro-vector lookup table from the
   spec, which is out of proportion for this fix. A 4.0-only OSV record therefore stays UNKNOWN, but
   by an explicit decision rather than by accident. Write this down in the docstring.
3. Change `CVSS.score` to `float | None`. A malformed 3.x vector (a missing or invalid base metric) also gives
   `None`. It never raises and never returns 0.0.
4. The rendered advisory prints `n/a` for a `None` score instead of `None`.
5. Leave the existing `> 0` filter in `_lookup` as it is. Changing how a genuine 0.0 score is handled (INFO vs
   UNKNOWN) is out of scope.

## Fix plan

- **HOTFIX-c216e0c0eb2b-1**: add `cvss3_base_score(vector) -> float | None` to `cve/models.py`.
  Widen `CVSS.score` to `float | None`. In `_parse_osv`, use the computed score for 3.x and `None` for
  4.0. Render `n/a` for a `None` score. Add tests.

## Validation commands

- `pytest packages/ai-parrot-tools/tests/security/cve/test_cve_toolkit.py -q`
