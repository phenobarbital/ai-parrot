# TASK-3317: Spike S3 — xdist safety per distribution → `XDIST_SAFE_DISTRIBUTIONS`

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3305
**Assigned-to**: unassigned

---

## Context

Spec §7 Spikes S3, risks R7 and R13, AC10. The planner (TASK-3305) adds `-n auto` only for
distributions listed in `test_scope.policy.XDIST_SAFE_DISTRIBUTIONS`, which ships **empty**.
Core-change escalation (G7b) runs whole package suites — `ai-parrot` alone is 1,450 modules
(~9 min serial) — so making `ai-parrot` xdist-safe is the single biggest lever on escalation
cost. This spike measures, per distribution, whether `pytest -n auto` produces the **same
outcome per test** as a serial run, and writes only the proven-safe distributions into the
allowlist. No automatic serial retry exists (R7): a distribution is either proven or excluded.

Known hazards (R7): navconfig `os.chdir` on import, 34 `chdir` hits in tests, ~60
session/module-scoped fixtures, fixed ports (~214 hits), shared redis/sqlite, process-wide
singletons (`packages/ai-parrot/tests/conftest.py` autouse reset fixture).

---

## Scope

- For each distribution, **`ai-parrot` first**, then `ai-parrot-tools`, `parrot-formdesigner`,
  `ai-parrot-integrations`, `ai-parrot-server`, `ai-parrot-visualizations`, `ai-parrot-embeddings`,
  `ai-parrot-loaders`, and the repo-root group `root` (`tests/`):
  1. Run the suite **serially** with the agent flags and marker expression, `--junitxml`.
  2. Run it **twice** with `-n auto`, same flags, `--junitxml`.
  3. Compare per-`nodeid` outcomes (passed/failed/error/skipped). Safe ⇔ all three runs agree for
     every nodeid AND the xdist runs are faster than serial.
- Record commands, wall-clock, worker count, disagreeing nodeids (first 30) and verdict per
  distribution in `artifacts/logs/feat-563-s3-xdist.md`.
- Set `XDIST_SAFE_DISTRIBUTIONS` in `test_scope/policy.py` to exactly the safe set (may stay empty).
- Stop early for a distribution when the first xdist run already disagrees (verdict: unsafe).

**NOT in scope**: fixing xdist-unsafe tests (separate follow-up; list the offending nodeids);
`CORE_PATHS` (TASK-3318); planner logic (TASK-3305).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | set `XDIST_SAFE_DISTRIBUTIONS` to the measured safe set |
| `artifacts/logs/feat-563-s3-xdist.md` | CREATE | evidence: commands, timings, disagreements, verdicts |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# None needed in production code. Comparison helper runs inline (stdlib only):
import xml.etree.ElementTree as ET  # stdlib — parse --junitxml output
```

### Existing Signatures to Use
- `.venv`: pytest 9.1.1, pytest-xdist 3.3.1 (pinned at root `pyproject.toml:64`), pytest-asyncio 1.4.0.
- Root `pytest.ini` shadows root `pyproject.toml [tool.pytest.ini_options]`; runs rooted in
  `packages/<dist>/` use that dist's pyproject section (spec §6 Configuration References).
- Worktree rule (`.claude/rules/worktree-management.md` §4): inside a worktree, prefix pytest with
  `PYTHONPATH=packages/ai-parrot/src` (one entry per changed package) — the shared `.venv` is
  editable-installed against the main checkout.

### Created by dependency tasks (TASK-3305 — verify it landed before starting)
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
AGENT_MARKER_EXPRESSION: str = "not e2e and not real_llm and not integration"
AGENT_FLAGS: tuple[str, ...] = ("-q", "--tb=short", "-p", "no:cacheprovider", "-o", "log_cli=false")
XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset()   # the ONLY line this task changes
```
- TASK-3303 log `artifacts/logs/feat-563-s2-conftest-rootdir.md`: any extra invocation flag
  (`--rootdir` / `-c` / `--confcutdir`) decided there MUST be used in every run here, so the
  measured invocation equals what the planner emits.

### Does NOT Exist
- ~~pytest-timeout~~ — not installed; bound runs with an external `timeout` command
- ~~any existing `-n` / `--dist` / `xdist_group` / `worker_id` usage in the repo~~ — none
- ~~`pytest-randomly`~~ — not installed; ordering differences come only from xdist distribution

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py", "action": "MODIFY"},
    {"path": "artifacts/logs/feat-563-s3-xdist.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Evidence logs under `artifacts/logs/` (e.g. `artifacts/logs/feat-566-ledger-core.log`): plain text/markdown, commands verbatim, results verbatim.

### Key Constraints
- **Exclusive task** (`parallel: false`): full-suite runs with `-n auto` saturate the shared machine and
  shared services (redis/ports); concurrent tasks would both slow and corrupt the measurement.
- Wrap every run in `timeout 1800` so a hung worker cannot block the lane.
- Same flags in all three runs; only `-n auto` differs.
- Pre-existing failures are fine — only **disagreement** between runs makes a distribution unsafe.
- Never edit tests or conftests here.

### References in Codebase
- spec §7 R7, R13; spec §5 AC10

---

## Implementation Blueprint

### Steps (in order)
1. Confirm `test_scope/policy.py` has `XDIST_SAFE_DISTRIBUTIONS` and read the TASK-3303 log flags — *why*: the measured command must equal the planner's.
2. For `ai-parrot` run serial → xdist → xdist, each with `--junitxml=/tmp/s3-<dist>-<run>.xml` — *why*: it dominates escalation cost (R13).
3. Compare outcomes per nodeid with the stdlib snippet below; record verdict — *why*: agreement, not green-ness, defines safety.
4. Repeat for the remaining distributions in the Scope order — *why*: satellites are escalated when they import a core module.
5. Write the log, then set `XDIST_SAFE_DISTRIBUTIONS` — *why*: the allowlist must be backed by evidence in the same commit.

### Command template (per distribution)
```bash
# DIST_TESTS = packages/<dist>/tests   (or `tests` for the root group)
FLAGS=(-q --tb=short -p no:cacheprovider -o log_cli=false -m "not e2e and not real_llm and not integration")
# FILL IN: append the TASK-3303 invocation flags (if any) to FLAGS — bounded by S2 decision
( time timeout 1800 pytest "$DIST_TESTS" "${FLAGS[@]}" --junitxml=/tmp/s3-$DIST-serial.xml ) 2>&1 | tail -5
( time timeout 1800 pytest "$DIST_TESTS" "${FLAGS[@]}" -n auto --junitxml=/tmp/s3-$DIST-x1.xml ) 2>&1 | tail -5
( time timeout 1800 pytest "$DIST_TESTS" "${FLAGS[@]}" -n auto --junitxml=/tmp/s3-$DIST-x2.xml ) 2>&1 | tail -5
```

### Outcome comparison (run inline, not committed)
```python
import sys
import xml.etree.ElementTree as ET


def outcomes(path: str) -> dict[str, str]:
    """nodeid-ish key (classname::name) → passed|failed|error|skipped from a junit xml."""
    result: dict[str, str] = {}
    for case in ET.parse(path).iter("testcase"):
        key = f"{case.get('classname')}::{case.get('name')}"
        kinds = [child.tag for child in case]
        # FILL IN: map child tags failure/error/skipped → outcome, none → passed — bounded by S3 definition
        result[key] = "passed" if not kinds else kinds[0]
    return result


serial, x1, x2 = (outcomes(p) for p in sys.argv[1:4])
diff = sorted(k for k in set(serial) | set(x1) | set(x2) if len({serial.get(k), x1.get(k), x2.get(k)}) > 1)
print(len(serial), len(diff), *diff[:30], sep="\n")
```

### `artifacts/logs/feat-563-s3-xdist.md` (CREATE)
```markdown
# FEAT-563 S3 — xdist safety per distribution

Date: YYYY-MM-DD · host cores: N · pytest 9.1.1 · xdist 3.3.1 · flags: <exact FLAGS>

| distribution | tests | serial (s) | -n auto run1 (s) | run2 (s) | workers | disagreements | verdict |
|---|---|---|---|---|---|---|---|
| ai-parrot | … | … | … | … | … | … | safe / unsafe |

## Disagreements (first 30 per unsafe distribution)
<!-- FILL IN: nodeids + serial/x1/x2 outcomes -->

## Decision
XDIST_SAFE_DISTRIBUTIONS = frozenset({...})
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3305: grep -c '^XDIST_SAFE_DISTRIBUTIONS: frozenset\[str\] = frozenset()$' .../test_scope/policy.py)
# REPLACE — `XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset()` with:
# Measured safe under `-n auto` (same per-test outcome as serial, twice) — evidence:
# artifacts/logs/feat-563-s3-xdist.md (FEAT-563 S3). Add a distribution only with new evidence.
XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        # FILL IN: exactly the distributions whose verdict is "safe" in the log — bounded by AC10
    }
)
```
**Why**: AC10 ships the allowlist with the distributions proven safe by S3; an empty set is a valid outcome.

### FILL IN checklist
- [ ] FLAGS include TASK-3303's decided flags; bounded by S2
- [ ] junit outcome mapping; bounded by the S3 agreement definition
- [ ] log table + disagreements; bounded by AC10
- [ ] `XDIST_SAFE_DISTRIBUTIONS` = safe verdicts only; bounded by AC10, R7

---

## Acceptance Criteria

- [ ] AC10 — `XDIST_SAFE_DISTRIBUTIONS` contains exactly the distributions with verdict `safe` in `artifacts/logs/feat-563-s3-xdist.md` (may be empty)
- [ ] `ai-parrot` measured first and present in the log table with timings
- [ ] Every distribution in Scope has a row (or an explicit "skipped: <reason>")
- [ ] The only change to `policy.py` is the `XDIST_SAFE_DISTRIBUTIONS` definition + its comment
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` clean

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`

---

## Test Specification

```bash
test -s artifacts/logs/feat-563-s3-xdist.md
grep -q '^| ai-parrot |' artifacts/logs/feat-563-s3-xdist.md
grep -q '^XDIST_SAFE_DISTRIBUTIONS = ' artifacts/logs/feat-563-s3-xdist.md
python - <<'PY'
import re, pathlib
log = pathlib.Path("artifacts/logs/feat-563-s3-xdist.md").read_text()
safe = {m.group(1) for m in re.finditer(r"^\| (\S+) \|.*\| safe \|$", log, re.M)}
src = pathlib.Path("packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py").read_text()
assert all(f'"{d}"' in src for d in safe), safe
PY
```
The existing planner tests (TASK-3305) must stay green: they assert `-n auto` presence iff a
distribution is in the allowlist, not specific members.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3317-spike-xdist-allowlist.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
