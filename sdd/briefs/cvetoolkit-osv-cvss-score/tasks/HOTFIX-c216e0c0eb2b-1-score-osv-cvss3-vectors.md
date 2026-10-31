# HOTFIX-c216e0c0eb2b-1: Compute CVSS 3.x base scores for OSV vectors

**Feature**: cvetoolkit-osv-cvss-score (BRIEF-c216e0c0eb2b)
**Spec**: sdd/briefs/cvetoolkit-osv-cvss-score.brief.md
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
OSV-only CVE records (NVD disabled or failed) get `CVSS(score=0.0)`, so `_lookup` gives severity
UNKNOWN even though there is a full vector. See the brief's Root cause section.

## Scope
- In `cve/models.py`, add a pure function `cvss3_base_score(vector: str) -> float | None`. It follows the
  FIRST CVSS v3.x base-score formula:
  - Parse `CVSS:3.0/...` or `CVSS:3.1/...` into `metric:value` pairs. Require all 8 base metrics
    (AV, AC, PR, UI, S, C, I, A) with valid values. Ignore temporal/environmental metrics. Return `None` for
    a 4.0 vector, a non-3.x prefix, or any missing or invalid base metric. Never raise.
  - Weights: AV N .85/A .62/L .55/P .2; AC L .77/H .44; PR N .85, L .62 (.68 if S:C), H .27 (.5 if S:C);
    UI N .85/R .62; C/I/A H .56/L .22/N 0.
  - ISS = 1 − (1−C)(1−I)(1−A). Impact = 6.42·ISS when S:U, and 7.52·(ISS−0.029) − 3.25·(ISS−0.02)^15 when S:C.
    Exploitability = 8.22·AV·AC·PR·UI. If Impact ≤ 0 the score is 0.0. Otherwise S:U gives
    Roundup(min(Impact+Exploitability, 10)) and S:C gives Roundup(min(1.08·(Impact+Exploitability), 10)).
  - Roundup: for 3.1, use the spec's integer-safe version (`i = round(x*100000)`; `i/100000.0` if
    `i % 10000 == 0`, else `(floor(i/10000)+1)/10.0`). For 3.0, use `ceil(x*10)/10`.
- Change `CVSS.score` to `float | None` and update its docstring: None means "not computed (e.g. CVSS 4.0 from OSV)".
- In `CVEToolkit._parse_osv`, replace `score=0.0` with `cvss3_base_score(vector)` for 3.x and `None` for
  `4.0`.
- In `_render_markdown`, render the score as `n/a` when it is `None`.
- Tests (in `test_cve_toolkit.py`, or a new `test_cve_models.py` in the same directory):
  - The fixture vector `CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:H/I:N/A:N` gives 5.3.
  - `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H` gives 9.8.
  - `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H` gives 10.0.
  - `CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:N` gives 6.4.
  - `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N` gives 0.0.
  - Truncated or garbage vectors and a `CVSS:4.0/...` vector give `None`.
  - `CVEToolkit(enrich_nvd=False)` lookup of the fixture CVE gives severity `medium` and an OSV cvss entry
    with score 5.3.
  - Extend `test_lookup_cve_nvd_failure_degrades_to_osv` to assert severity `medium`.

**NOT in scope**: CVSS 4.0 scoring; changing the `> 0` filter in `_lookup`; issue:b26901f15d12
(malformed-body handling and the response size cap); new dependencies.

## Files to Create / Modify
- MODIFY `packages/ai-parrot-tools/src/parrot_tools/security/cve/models.py`
- MODIFY `packages/ai-parrot-tools/src/parrot_tools/security/cve/toolkit.py`
- MODIFY `packages/ai-parrot-tools/tests/security/cve/test_cve_toolkit.py`

## Codebase Contract
- Verified: `models.py:36-42` `class CVSS(BaseModel)` with `version: Literal["3.0","3.1","4.0"]`, `score: float`,
  `vector: str`, `source: Literal["osv","nvd"]`.
- Verified: `models.py:111` `def severity_from_score(score: float | None) -> SeverityLevel` (None → UNKNOWN).
- Verified: `toolkit.py:38` `_CVSS_VERSION_RE = re.compile(r"^CVSS:(3\.0|3\.1|4\.0)/")`.
- Verified: `toolkit.py:289` `cvss.append(CVSS(version=m.group(1), score=0.0, vector=vector, source="osv"))`.
- Verified: `toolkit.py:258-259` severity derived from `c.score is not None and c.score > 0`.
- Verified: `toolkit.py:230` renders `meta_value(c.score)`.
- Verified: `CVEToolkit.__init__(..., enrich_nvd: bool = True, ...)` at `toolkit.py:62`.
- Verified: the tests use `_install(tk, _default_routes(...))` and `tk.lookup_cve(CVE)` (`test_cve_toolkit.py:31-60`).
- Does NOT exist: any CVSS calculator in the repo; the `cvss` PyPI package in the venv.

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/security/cve/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/security/cve/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/security/cve/test_cve_toolkit.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/security/cve/models.py#CVSS",
    "sym:packages/ai-parrot-tools/src/parrot_tools/security/cve/models.py#severity_from_score",
    "sym:packages/ai-parrot-tools/src/parrot_tools/security/cve/toolkit.py#CVEToolkit._parse_osv",
    "sym:packages/ai-parrot-tools/src/parrot_tools/security/cve/toolkit.py#CVEToolkit._lookup",
    "sym:packages/ai-parrot-tools/src/parrot_tools/security/cve/toolkit.py#CVEToolkit._render_markdown"
  ]
}
```

## Acceptance Criteria
- An OSV-only lookup (NVD off, 429, or timeout) of the fixture CVE reports severity `medium` and an OSV score of 5.3.
- All the reference vectors above score exactly as listed. Invalid and 4.0 vectors give `None` without raising.
- The existing tests still pass, and the NVD-merged path still reports NVD's 5.3.
- `ruff check` passes on the changed files.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/security/cve/test_cve_toolkit.py -q`

## Completion Note
