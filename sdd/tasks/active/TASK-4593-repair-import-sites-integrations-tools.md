# TASK-4593: Repair the integrations and tools import sites

**Feature**: FEAT-720 — One Importable Identity per Package Test Tree
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4592
**Assigned-to**: unassigned
**Discovered-from**: `issue:45cf6a054e06`

---

## Context

Implements spec **Module 3** for `ai-parrot-integrations` and `ai-parrot-tools`.

These two carried the **largest collect-error counts** in round 2 — integrations
25 and tools 9, against 3 class-(i) import sites each. That gap is the point of
this task: most of the breakage here is **not** plain `from tests.x` imports but
class-(v) **runtime dotted string targets** such as
`"tests.agentd.fakes:EchoAgent"`, which collect fine and fail at execution. They
are invisible to a grep for import statements and will not be found by fixing
imports alone.

---

## Scope

- Repair the 3 class-(i) sites in `packages/ai-parrot-integrations/tests` and the
  3 in `packages/ai-parrot-tools/tests`.
- Repair every class-(v) dotted string target in
  `packages/ai-parrot-integrations/tests` (6 files, concentrated in `agentd/`).
- Repair every class-(ii)/(iii) site TASK-4590 §3 attributes to these two
  distributions.

**NOT in scope**: any other distribution (TASK-4592/4594); restoring a top-level
`__init__.py`; the regression test (TASK-4595); changing any assertion, fixture
behaviour, parameter or skip.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/agentd/test_e2e.py` | MODIFY | class (i) import |
| `packages/ai-parrot-integrations/tests/agentd/test_scheduler_boot.py` | MODIFY | class (i) import |
| `packages/ai-parrot-integrations/tests/agentd/test_service.py` | MODIFY | class (i) import |
| `packages/ai-parrot-integrations/tests/agentd/test_cli.py` | MODIFY | class (v) dotted targets |
| `packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py` | MODIFY | class (i) import |
| `packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py` | MODIFY | class (i) import |
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | MODIFY | class (i) import |

The remaining class-(v) files in `ai-parrot-integrations` (6 total, located by
the command in the contract below) and any class-(ii)/(iii) file named by
TASK-4590 §3 are added to this table by the implementing agent **before**
editing, so the Complexity Contract stays accurate.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

The sites being repaired, sampled verbatim on `dev c2fd0ae28`:

```python
# packages/ai-parrot-integrations/tests/agentd/test_service.py:39
from tests.agentd.fakes import EchoAgent

# packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py:32
from tests.scraping.fixtures.local_site import TEST_PASSWORD, TEST_USERNAME
```

Note the second one reaches **across sibling subtrees** inside the same
distribution (`business_automation/` → `scraping/`), so a relative import needs
to climb to the test root and back down.

### Class-(v) dotted targets, verbatim

```python
# packages/ai-parrot-integrations/tests/agentd/test_cli.py:51
            'name: my-agent\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
# packages/ai-parrot-integrations/tests/agentd/test_cli.py:60
        assert _FakeDaemon.last_config.agent.target == "tests.agentd.fakes:EchoAgent"
# packages/ai-parrot-integrations/tests/agentd/test_cli.py:67
            agentd_cli.serve, ["tests.agentd.fakes:EchoAgent", "--name", "cli-agent"]
# packages/ai-parrot-integrations/tests/agentd/test_cli.py:72
        assert _FakeDaemon.last_config.agent.target == "tests.agentd.fakes:EchoAgent"
# packages/ai-parrot-integrations/tests/agentd/test_cli.py:76
        result = runner.invoke(agentd_cli.serve, ["tests.agentd.fakes:EchoAgent"])
# packages/ai-parrot-integrations/tests/agentd/test_cli.py:83
            'name: my-agent\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
```

These are resolved by the agentd loader at **runtime**, not by pytest. A string
that no longer resolves produces a test failure, not a collection error — so
collection going green here is **not** evidence this task is done.

### Verified facts (measured on `dev c2fd0ae28`)

| Fact | Value | Command |
|---|---|---|
| class-(i) sites, integrations | **3 files** | `grep -rln -E '^\s*(from\|import)\s+tests[.\s]' packages/ai-parrot-integrations/tests` |
| class-(i) sites, tools | **3 files** | same, for `packages/ai-parrot-tools/tests` |
| class-(v) files, integrations | **6 files** | `grep -rln "['\"]tests\." packages/ai-parrot-integrations/tests` |
| round-2 collect errors | integrations 25, tools 9 | `sdd/state/FEAT-720/spike-collect.md` §2 supersedes |

### Does NOT Exist
- ~~a `tests` package after TASK-4591~~ — do not restore one to make a dotted
  target resolve.
- ~~an importable `tests.agentd.fakes` once the test root is not a package~~ —
  the target string must name whatever the module is actually importable as, or
  the loader must be given a path. Decide from the loader's real contract, not
  from the old string's shape.
- ~~a shared fixture package across distributions~~ — `tools`' `scraping/fixtures`
  and `integrations`' `agentd/fakes` are unrelated trees.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/tests/agentd/test_e2e.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/agentd/test_scheduler_boot.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/agentd/test_service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/agentd/test_cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints — the hard one
A repair may change **only** an import statement, a `conftest.py`, or a dotted
string target. It may **not** change an assertion, a fixture's behaviour, a
test's parameters, or add a skip/xfail. A site needing more is a **finding for
the Completion Note**, not a licence to edit the test (AC5, AC6).

### Other constraints
- **Collection green ≠ done here.** The class-(v) targets only fail when the
  agentd loader resolves them, so this task's Validation Commands *run* the
  affected files rather than collecting them.
- `test_cli.py` has **6 occurrences of the same string** across 4 distinct
  contexts (a YAML blob, two equality assertions, two CLI argv lists). Change all
  six consistently; a partial rename leaves a test asserting the old form.
- `broker.py` is a fixture module, not a test module — it is imported by other
  tests, so breaking it breaks them silently at collection.
- `PYTHONPATH=packages/ai-parrot-integrations/src` and
  `packages/ai-parrot-tools/src` respectively when running in the worktree.

### References in Codebase
- `sdd/state/FEAT-720/spike-collect.md` §3 — the authoritative per-site list
- `packages/ai-parrot-integrations/tests/agentd/fakes.py` — the module every
  class-(v) target names

---

## Implementation Blueprint

### Steps (in order)
1. Read TASK-4590's §3 table for these two distributions — *why*: round 2's
   25-and-9 error counts against 6 import sites means most of the work is not
   class (i), and the table is the only list of the rest.
2. Determine what the agentd loader can actually resolve after TASK-4591 — *why*:
   every class-(v) decision follows from the loader's contract, and guessing a
   new string shape produces a test that passes against a fake.
3. Repair the 6 class-(i) imports — *why*: `broker.py` is imported by other
   tests, so it must resolve before anything in `business_automation/` collects.
4. Repair all 6 class-(v) occurrences in `test_cli.py` together — *why*: they are
   the same logical value in four syntactic contexts; a partial change leaves an
   assertion comparing the new form to the old.
5. Run (not just collect) the affected files — *why*: class (v) fails at runtime
   and is invisible to `--collect-only`.

### `packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from tests.scraping.fixtures.local_site import TEST_PASSWORD, TEST_USERNAME' packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py)
# REPLACE — the line `from tests.scraping.fixtures.local_site import TEST_PASSWORD, TEST_USERNAME` (verified: packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py:32)
# FILL IN: the replacement import — bounded by AC5 (import-only change). Note this
#          reaches ACROSS sibling subtrees (business_automation/ → scraping/), so a
#          relative import must climb to the test root first; verify the dot count
#          against this file's actual depth.
```
**Why**: this is the only cross-subtree import in the two distributions, so it is
the one most likely to get a wrong dot count. It is also a fixture module rather
than a test module, which means a mistake here surfaces as a collection error in
unrelated test files.

### `packages/ai-parrot-integrations/tests/agentd/test_cli.py` (MODIFY)
```python
# occurrences: 6 (verified: grep -c 'tests.agentd.fakes:EchoAgent' packages/ai-parrot-integrations/tests/agentd/test_cli.py)
# FILL IN: disambiguate — the same string appears at :51, :60, :67, :72, :76 and :83
#          in four different contexts (YAML blob, two `==` assertions, two argv
#          lists). Quote 2-3 lines of surrounding context per edit.
# FILL IN: the replacement target string — bounded by AC5 and by what the agentd
#          loader can resolve after TASK-4591 (decide from the loader's contract,
#          verified in packages/ai-parrot-integrations/src, not from the old shape).
```
**Why**: the occurrence count is 6, so per the blueprint rules a bare one-line
anchor is not usable and each edit must carry surrounding context. All six must
move together — two of them are assertions comparing against the literal, so
changing the YAML blob alone turns a passing test into a confusing failure.

### FILL IN checklist
- [ ] `broker.py:32` — cross-subtree replacement import; bounded by AC5 + file depth
- [ ] the other 5 class-(i) sites — one per file; bounded by AC5
- [ ] `test_cli.py` ×6 — disambiguated per occurrence; bounded by AC5 + the loader contract
- [ ] the remaining 5 class-(v) files in integrations; bounded by AC5
- [ ] any class-(ii)/(iii) site TASK-4590 §3 attributes to these two distributions

---

## Acceptance Criteria

- [ ] No `from tests.<x>` or `import tests.<x>` remains under
      `packages/ai-parrot-integrations/tests` or `packages/ai-parrot-tools/tests`.
- [ ] No unresolved `"tests.…"` dotted string target remains in either tree.
- [ ] `pytest packages/ai-parrot-integrations/tests --collect-only -q -p no:randomly`
      and the same for `ai-parrot-tools` exit 0 with the **same item counts** as
      TASK-4590's baseline (AC2).
- [ ] The agentd CLI tests **pass**, not merely collect — class (v) is a runtime
      failure mode.
- [ ] Every edit is an import statement, a `conftest.py`, or a dotted string
      target (AC5).
- [ ] No test is skipped, xfailed or deleted (AC6).
- [ ] `ruff check` clean on every changed file (AC9).

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/agentd/test_cli.py -q`
- `pytest packages/ai-parrot-integrations/tests/agentd/test_service.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py -q`
- `pytest packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py -q`

---

## Test Specification

No new test code. Each repaired file's existing tests are the specification: they
must pass exactly as they did before TASK-4591, with the same item count.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** §2 breakage classes and **TASK-4590's `sdd/state/FEAT-720/spike-collect.md` §3**
3. **Check dependencies** — TASK-4592 must be `"done"` in the per-spec index
4. **Verify the Codebase Contract** — re-run the `grep` counts, especially the
   `grep -c` for the 6 `test_cli.py` occurrences; update this task's tables FIRST
   if anything moved
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file
6. **Implement** — imports first, then the dotted targets as one coherent change
7. **Verify** by **running** the affected files, not just collecting them
8. **Commit the code** — stage only this task's files, never `git add .` / `-A`
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4593 tests-test-wheel-layout-tech-debt-2 verified`
10. **Fill in the Completion Note** — list any site that needed more than an
    import change, as a finding rather than an edit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
