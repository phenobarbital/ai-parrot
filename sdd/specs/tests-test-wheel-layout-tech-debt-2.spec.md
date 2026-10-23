---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-embeddings, ai-parrot-server, ai-parrot-integrations, ai-parrot-tools, parrot-formdesigner, ci, sdd-tooling]
tags: [pytest, conftest, test-collection, import-mode, tech-debt]
---

# Feature Specification: One Importable Identity per Package Test Tree

**Feature ID**: FEAT-720
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved (rev 0.3 — Amendment B, 2026-10-23)
**Target version**: 1.3.0

> **Slug note.** The slug `tests-test-wheel-layout-tech-debt-2` is inherited
> verbatim from `wikitoolkit ledger plan-fix`'s `suggested_slug` for
> `fixgroup:c11379671f03` (derived from the first `about` anchor, plus a `-2`
> because FEAT-618 already owns the un-suffixed form). It under-describes the
> feature; `/sdd-fix` forbids re-deriving a planner-supplied slug.

**Resolves**: `issue:45cf6a054e06` — *Every `packages/*/tests` tree resolves to
the same import name `tests`, so no two can be collected in one pytest session*
(kind `tech_debt`, severity `major`, `discovered_from: spec:FEAT-618`).

> **Why this is not FEAT-618.** The planner reports FEAT-618 as an `open`
> parent, and `/sdd-fix`'s SDD lane would normally reuse that spec. It must not
> here: FEAT-618 **rev 0.4** (2026-10-22, `c2fd0ae28`) split this work out
> deliberately, and its **AC10 forbids** that feature from touching any
> `packages/*/tests/__init__.py`, any `test_scope/` module, or the root
> `pyproject.toml` — the exact files this feature exists to change. FEAT-618 is
> `open` only because its unrelated `parrot-formdesigner` baseline repair is
> unstarted. Landing both under one id would re-merge a scope cut that was made
> on measurement.

---

## 1. Motivation & Business Requirements

### Problem Statement

Every package test root in this monorepo claims the same top-level import name,
`tests`. Collecting any two in one pytest session therefore collides:

```
$ python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py \
                   packages/parrot-formdesigner/tests/unit/test_version_and_docs.py --co -q
_pytest.pathlib.ImportPathMismatchError: ('tests.conftest',
  '…/packages/ai-parrot-embeddings/tests/conftest.py',
  PosixPath('…/packages/parrot-formdesigner/tests/conftest.py'))

$ python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q
15 passed in 1.34s
```

*(Both reproduced on `dev 986601b4b`, pytest 9.1.1, 2026-10-22.)*

The cost is not theoretical. `coder_run_validation(tier="merge")` is the gate
that decides whether an `sdd-coder` task may merge, and any plan that reaches
two distributions at once hits this before it runs a single assertion — a hard
collection **error**, not a failure, so the gate cannot distinguish it from a
real break. It is also why `test_wheel_layout.py` has been reported red for
months while passing 15/15 on its own.

**`--import-mode=importlib` alone does NOT fix this.** Verified: pytest still
derives `tests.conftest` from the `__init__.py` chain and fails one layer later
with `ValueError: Plugin already registered under a different name: …`. The
`__init__.py` files are the defect; the import mode is at most half the remedy.

### Why it has not been fixed

Twice attempted, twice stopped at the same place — the fix is cheap and the
fallout is not. FEAT-618's `TASK-3908` measured both candidate strategies and
paused rather than guess; this spec exists to carry that measurement to a
decision rather than repeat it.

### Goals

1. Any two package test trees — any pair, not just the reported one — collect
   in **one** pytest session with no `ImportPathMismatchError` and no pluggy
   double-registration.
2. Every test that passes today still passes afterwards, in every one of the 28
   package test roots. This feature changes **how tests are imported**, never
   what they assert.
3. The collision cannot regress silently: a test asserts the invariant.
4. The change lands in one window with a stated conflict cost, not as a slow
   drip that every in-flight worktree has to rebase through.

### Non-Goals (explicitly out of scope)

- The `parrot-formdesigner` red baseline (40 failures) — **FEAT-618** owns it.
  This feature must not fix, skip or touch any of those tests; a collection
  change that *reveals* them is expected and is not this feature's to repair.
- Merge-tier scope selection, `detect_core()`, `source_fanin()` or `CORE_PATHS`
  — FEAT-604/FEAT-620 own those and FEAT-620 is merged.
- Changing what any test asserts, adding coverage, or deleting a test.
- Reorganising the test trees into a different directory layout.
- The `tests/` tree at the repo root (not under `packages/`), which has no
  sibling to collide with.

---

## 2. Architectural Design

### Overview

One module, deliberately: the change is atomic. A partial landing leaves the
monorepo in a state where *some* test trees import one way and some another,
which is strictly worse than either end state.

```
M1 ── spike: re-measure (a) on current dev ──→ evidence only, no product change
M2 ── collection identity ───────────────────→ packages/*/tests/__init__.py + pyproject.toml
M3 ── repair the import sites (a)(i)–(vi) ───→ ~60 sites across 6 distributions
M4 ── regression test + CI guard ────────────→ a new test asserting the invariant
```

M1 gates everything. M2 and M3 **land in one commit** — see *Landing* below.

## 2a. Amendment B (rev 0.3, 2026-10-23) — the remedy is `pytest.ini`, not file deletion

**Supersedes every statement below that says top-level or nested `packages/*/tests/__init__.py` files are deleted, and
the "25 deletions / 242 nested survive" numbers.** Two measured facts (`sdd/state/FEAT-720/spike-namespace-packages.md`,
verdict **`STRATEGY (a″) CONFIRMED`**; M1's first verdict `STRATEGY (a) REFUTED` is in `spike-collect.md`):

1. **The live pytest config is the tracked root `pytest.ini`, not `pyproject.toml`.** pytest gives `pytest.ini` precedence, so
   `[tool.pytest.ini_options]` in `pyproject.toml` (`:247`) is dead config. §6 "pytest configuration exists only in the root
   `pyproject.toml:247`" is wrong.
2. **`--import-mode=importlib` plus `consider_namespace_packages = true`, in `pytest.ini`, with every `__init__.py` kept, gives every
   test module a path-derived identity.** The reported pair collects with 0 identity collisions; all 28 roots in one session collect
   42,978 items with 0 `Plugin already registered` / `ImportPathMismatchError` / `import file mismatch`; every root collects
   standalone at its baseline count. Importlib mode *alone* still fails (the original `tests.conftest` error) — both lines are required.

Consequences: **M2 is two lines in `pytest.ini`** (no deletion, no landing-window problem, nothing for ~60 worktrees to rebase
through). **M3 is unchanged in kind** — the class (i)/(iii)/(v)/(vi) sites — measured now at: `ai-parrot-tools` 2 files and
`parrot-formdesigner` 5 files fail even standalone; the other `from tests.<x>` sites fail only in mixed sessions and are repaired too.
Class (ii)/(iv)/(vii)–(x) do not arise (nothing is removed). **M4** guards the config, the pair collect, and the absence of `tests.<x>` imports.
Class (xi) — test modules that replace `sys.modules[...]` at import, visible only when many trees share a session — is out of scope (ledger).
**AC4 becomes: all 267 `__init__.py` under `packages/*/tests` are unchanged.**

### Follow-up fixes after review (2026-10-23)

The independent review and the 28-way session surfaced residue that is now fixed: (1) `agentd` dotted targets follow `__package__` and the
guard rejects `"tests.<x>:Name"` strings; (2) the dead root `[tool.pytest.ini_options]` is removed and guarded; (3) class (xi) pollution —
the spatial tests restore their `aiohttp`/`parrot._imports` stubs, `ai-parrot/tests` no longer puts its own directory on `sys.path` (which made
`tests/mcp` and `tests/benchmarks` shadow the real `mcp` SDK and the repo-root `benchmarks`), and the formdesigner build-script test loads the script by
path instead of a global `sys.path` entry. Entry-point targets must not contain the hyphens of a path-derived package name (`test_factory_discovery`
uses a plain alias). Result: all 28 roots in one session collect **44,118** items with **0** identity collisions and only the 2 pre-existing
`fakeredis` errors (a package missing from the shared `.venv`); ruff is clean on every changed file; the 57 failures in the touched files are identical
on `origin/dev`.

### The two strategies, and why (b) is already rejected

| | Strategy | Verdict |
|---|---|---|
| **(a)** | Delete the 25 top-level `packages/*/tests/__init__.py`, set `--import-mode=importlib` in the root `addopts` | **Refuted** by M1 (leaves 129 errors) |
| **(a″)** | `--import-mode=importlib` + `consider_namespace_packages = true` in **`pytest.ini`**; no `__init__.py` change | **Selected — CONFIRMED** (Amendment B) |
| **(b)** | Rename each `packages/<dist>/tests` to a unique importable name | **Rejected on measurement** |

**(b) is rejected** because the directory name is load-bearing far outside the
test trees. Re-measured 2026-10-22 on `dev 986601b4b`:

| Surface | Count |
|---|---|
| `sdd/` files containing a `packages/<dist>/tests` path literal | **4,059** |
| CI workflows referencing package test paths | **5** (`ci.yml`, `e2e.yml`, `nightly-tests.yml`, `release.yml`, `lancedb-vector-store.yml`) |
| `ruff.toml` per-file ignores keyed on a test path | `**/tests/**` + 5 explicit `packages/<dist>/tests/...` entries |

Renaming would invalidate every validation contract and task file in `sdd/`.
Rejected; recorded here so it is not re-proposed.

### (a)'s measured fallout — the real work

FEAT-618 `TASK-3908` round 2 (pytest 9.1.1) established the load-bearing fact:

> After `git rm packages/*/tests/__init__.py` and adding `--import-mode=importlib`,
> `pytest packages/parrot-formdesigner/tests/unit/test_version_and_docs.py
> packages/ai-parrot-client-openai/tests/unit --collect-only` collects **58
> items with 0 errors**. Nested `unit/__init__.py` files did **not** need
> deleting under pytest 9.1.1.

That last clause is what makes this feature tractable: the earlier round-1
estimate of 267 deletions does not apply. The scope is **25 deletions**, plus
repairing what those 25 files were silently providing.

**Breakage classes**, re-measured on `dev 986601b4b`:

| | Class | Current measurement | Repair |
|---|---|---|---|
| (i) | `from tests.<x> import …` | **34 files**: `ai-parrot` 24, `parrot-formdesigner` 4, `ai-parrot-tools` 3, `ai-parrot-integrations` 3 | rewrite to a relative import, or to a `conftest`-provided fixture |
| (ii) | relative imports with no known parent package | surfaced by M1's per-dist collect | give the file's own directory an `__init__.py` (nested ones are kept) |
| (iii) | reliance on prepend-mode `sys.path` insertion (e.g. `scripts.build_snippet_bundles`) | surfaced by M1 | explicit `sys.path` setup in the owning `conftest.py` |
| (iv) | relative imports inside test files | **343 imports across 231 files** — kept working by the *nested* `__init__.py`, which (a) does not delete | expected to need **no change**; M1 confirms |
| (v) | runtime string targets such as `"tests.agentd.fakes:EchoAgent"` | **68 occurrences** under `packages/*/tests` | re-point to the new import name |
| (vi) | `packages/ai-parrot-server/tests/mcp/__init__.py` shadowing the real `mcp` package once its parent is importable | 1 file, confirmed present | rename the directory or scope the import |

Round 2 measured the aggregate as **~60 broken collection sites in 6
distributions**: embeddings 1, integrations 25, loaders 1, server 6, tools 9,
formdesigner 5 — plus `ai-parrot` exiting 4 on a conftest error **not yet
attributed** to the change. M1 exists to attribute it.

### Landing

The deletion is monorepo-wide, so **every in-flight worktree rebases through
it**. There are ~60 live worktrees at spec time. Two consequences, both binding:

1. M2+M3 land as **one commit** on one PR. No incremental merge.
2. The PR is announced before merge and merged in a quiet window. This is a
   process constraint, not a code one, and it is why the issue says the work
   "needs a landing-window decision".

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| root `[tool.pytest.ini_options]` (`pyproject.toml:247`) | modifies | adds `--import-mode=importlib` to `addopts` |
| `addopts` (`pyproject.toml:248-251`) | extends | currently `--strict-config`, `--strict-markers` |
| `packages/*/tests/__init__.py` (25 files) | deletes | top level only; nested `__init__.py` are **kept** |
| nested `packages/*/tests/**/__init__.py` (242) | **unchanged** | load-bearing for class (iv)'s 343 relative imports |
| `ruff.toml` per-file ignores | **unchanged** | keyed on paths, which (a) does not move |
| `.github/workflows/*` | **unchanged** | keyed on paths, which (a) does not move |

---

## 3. Module Breakdown

> **Amendment B**: M2 = `pytest.ini` (two lines). M3 = the class (i)/(iii)/(v)/(vi) sites. M4 = config + pair + no-`tests.<x>` guards.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 | yes | the commands and the artefact shape are fixed below; it only records | — |
| M2 | yes | exactly 25 deletions + one `addopts` entry, both fully specified | — |
| M3 | no | each of the ~60 sites is an individual judgement about what the file meant to import | — |
| M4 | yes | the invariant and its assertion are fixed below | — |

### Module 1: Spike — re-measure strategy (a) on current `dev`

- **Path**: none (evidence only; **no product change may be committed**)
- **Responsibility**: re-run round 2's experiment on the current tree and
  record what breaks, per distribution, so M3 is scoped from today's evidence
  rather than from a three-week-old note. Specifically resolve the one thing
  round 2 left open: **why `ai-parrot` exits 4**, and whether that conftest
  error pre-exists the change.
- **Method**:
  1. Record the per-distribution `--collect-only` baseline **before** any change
     (round 2 could not: the sandbox denied it in the shared checkout — run it
     in the worktree).
  2. Apply (a): delete the 25 top-level `__init__.py`, add
     `--import-mode=importlib` to `addopts`.
  3. Re-run the same per-distribution collect; diff against the baseline.
  4. Classify every new error into (i)–(vi); anything that fits none of them is
     a **new** class and must be added to this spec before M3 starts.
  5. **Revert.** The spike commits evidence, never the change.
- **Artefact**: `sdd/state/FEAT-720/spike-collect.md` — the two collect
  matrices, the diff, the per-class tally, and an explicit verdict line:
  `STRATEGY (a) CONFIRMED` or `STRATEGY (a) REFUTED — <why>`.
- **Gate**: if REFUTED, **stop**. M2–M4 do not start; the spec is revised.
- **Depends on**: nothing.

### Module 2: Collection identity

- **Path**: `pytest.ini` (Amendment B; the former 25 deletions and the `pyproject.toml` edit are void)
- **Responsibility**: make every package test root resolve to a distinct import
  name — by configuration in `pytest.ini` (Amendment B), not by deleting files.
- **Depends on**: M1 (`STRATEGY (a″) CONFIRMED` in `spike-namespace-packages.md`).
- **Interface Skeleton**:
  ```toml
  # pyproject.toml  (modifies :248)   # verified: pyproject.toml:247
  [tool.pytest.ini_options]
  addopts = [
      "--strict-config",
      "--strict-markers",
      "--import-mode=importlib",
  ]
  ```
  ```
  # Deleted — exactly these 25, all 0 bytes, top level only:
  packages/ai-parrot/tests/__init__.py
  packages/ai-parrot-embeddings/tests/__init__.py
  packages/ai-parrot-integrations/tests/__init__.py
  packages/ai-parrot-loaders/tests/__init__.py
  packages/ai-parrot-pipelines/tests/__init__.py
  packages/ai-parrot-server/tests/__init__.py
  packages/ai-parrot-tools/tests/__init__.py
  packages/ai-parrot-visualizations/tests/__init__.py
  packages/parrot-formdesigner/tests/__init__.py
  packages/ai-parrot-client-{amazon,anthropic,gemma4,google,grok,groq,hf,jev,
                             local,meta,moonshot,nvidia,openai,openrouter,
                             vllm,zai}/tests/__init__.py          # 16 files
  # KEPT — all 242 nested packages/*/tests/**/__init__.py.
  ```
- **Constraint**: `testpaths`, `python_files`, `python_functions`,
  `filterwarnings` and `markers` are unchanged. `--import-mode=importlib` is
  **appended**, never replacing an existing entry.

### Module 3: Repair the import sites

- **Path**: the ~60 sites M1 enumerates, across `ai-parrot`,
  `ai-parrot-embeddings`, `ai-parrot-integrations`, `ai-parrot-loaders`,
  `ai-parrot-server`, `ai-parrot-tools`, `parrot-formdesigner`
- **Responsibility**: every test that collected before M2 collects after it,
  and asserts exactly what it asserted before.
- **Depends on**: M2 (same commit — see *Landing*).
- **Constraint — the hard one**: a repair may change **only** an import
  statement, a `conftest.py`, or a dotted string target. It may not change an
  assertion, a fixture's behaviour, a test's parameters, or skip a test. A site
  that appears to need more than an import change is a finding for the
  Completion Note, not a licence to edit the test.
- **Per-distribution budget** (from round 2, to be replaced by M1's numbers):
  integrations 25, tools 9, server 6, formdesigner 5, embeddings 1, loaders 1.

### Module 4: Regression test + guard

- **Path**: `packages/ai-parrot/tests/` (new file)
- **Responsibility**: assert the invariant directly, so the collision cannot
  come back through a new package's `tests/__init__.py`.
- **Depends on**: M2.
- **Interface Skeleton** (Amendment B):
  ```python
  # packages/ai-parrot/tests/test_package_test_collection.py   (new)
  def test_pytest_ini_enables_path_derived_test_identities() -> None:
      """`pytest.ini` must set `--import-mode=importlib` in addopts and `consider_namespace_packages = true`.

      Parses the live config file with configparser. Guards the real defect: both lines are required, and
      pyproject.toml's pytest table is dead config (pytest.ini takes precedence).
      """

  def test_two_package_test_trees_collect_together() -> None:
      """`pytest <embeddings tree> <formdesigner tree> --collect-only` exits 0 in a subprocess; neither
      "ImportPathMismatchError" nor "already registered" nor "import file mismatch" appears."""

  def test_no_test_imports_the_ambiguous_tests_package() -> None:
      """No packages/*/tests/**/*.py contains `from tests.<x>`/`import tests.<x>` — `tests` is not a unique name."""
  ```
- **Note**: the second test shells out to pytest; it must be marked so it is
  never collected by the very session it spawns.

---

## 4. Test Specification

### Unit Tests
- M4's two tests (above).
- M3: for each repaired site's module, its own existing tests still pass — no
  new test is added for a repaired import.

### Integration Tests
- Each of the 28 package test roots collects standalone with exit 0, before and
  after, with an identical item count.
- The reported pair collects together with exit 0.
- `packages/ai-parrot-embeddings/tests/test_wheel_layout.py` passes 15/15.

### Validation Contract

tests:
- packages/ai-parrot/tests/test_package_test_collection.py
- packages/ai-parrot-embeddings/tests/test_wheel_layout.py
- packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py
- packages/ai-parrot/tests/unit/clients/test_factory_discovery.py
- packages/ai-parrot/tests/tools/test_obsidian_toolkit.py
- packages/ai-parrot-integrations/tests/agentd/test_cli.py
- packages/ai-parrot-integrations/tests/agentd/test_service.py
- packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py
- packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py
- packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py
- packages/parrot-formdesigner/tests/unit/test_org_graph_service.py
markers: none

### Test Data / Fixtures
None. M1's artefact is evidence, not a fixture.

---

## 5. Acceptance Criteria

- [ ] **AC1** `python -m pytest packages/ai-parrot-embeddings/tests packages/parrot-formdesigner/tests --collect-only -q`
      exits 0 — no `ImportPathMismatchError`, no pluggy double-registration.
- [ ] **AC2** Every one of the 28 package test roots collects standalone with
      exit 0 **and the same item count as before the change**. The before/after
      matrix is pasted in the Completion Note. A changed count is a defect, not
      a result.
- [ ] **AC3** `python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q` passes 15/15.
- [ ] **AC4** (Amendment B) **No** `__init__.py` is deleted. One may be *added* only where a relative import has no parent package
      (class (ii)); found so far: `packages/ai-parrot/tests/loaders/obsidian/__init__.py` (`find packages/*/tests -name __init__.py | wc -l`
      → **267 + the additions listed in the Completion Notes**), and `pytest.ini` carries `addopts = --import-mode=importlib` and
      `consider_namespace_packages = true`.
- [ ] **AC5** No test's assertions change. Every M3 edit is an import statement,
      a `conftest.py`, or a dotted string target — reviewable as such in the diff.
- [ ] **AC6** No test is skipped, xfailed or deleted to make collection pass.
- [ ] **AC7** `packages/parrot-formdesigner`'s 40-failure baseline is neither
      repaired nor worsened — it is FEAT-618's. Its failure count is stated
      before and after.
- [ ] **AC8** M4's regression test fails if any `packages/*/tests/__init__.py`
      is reintroduced (demonstrated by adding one, observing red, removing it).
- [ ] **AC9** `ruff check` clean on every changed file; `ruff.toml`, `pyproject.toml` and
      `.github/workflows/*` are unmodified.
- [ ] **AC10** M1's artefacts exist: `spike-collect.md` (`STRATEGY (a) REFUTED`) and `spike-namespace-packages.md`
      carrying an explicit `STRATEGY (a″) CONFIRMED` line.

---

## 6. Codebase Contract

> Verified against base commit **`c2fd0ae28`** (`dev`, 2026-10-22), pytest 9.1.1.

### Measured facts

| Fact | Value | How measured |
|---|---|---|
| top-level `packages/*/tests/__init__.py` | **25** (all 0 bytes) | `ls packages/*/tests/__init__.py \| wc -l` |
| all `__init__.py` under `packages/*/tests` | **267** (⇒ 242 nested) | `find packages/*/tests -name '__init__.py' \| wc -l` |
| files importing `from tests.<x>` | **34** | `grep -rln -E '^\s*(from\|import)\s+tests[.\s]' packages/` |
| … by distribution | ai-parrot 24, formdesigner 4, tools 3, integrations 3 | same, piped through `sed`/`uniq -c` |
| relative imports in test files | **343** across **231** files | `grep -rn -E '^\s*from\s+\.' packages/*/tests` |
| dotted string targets `"tests.…"` | **68** | `grep -rn "['\"]tests\." packages/*/tests` |
| `sdd/` files with a package test path literal | **4,059** | `grep -rl "packages/[a-z0-9-]*/tests" sdd/` |
| CI workflows referencing package test paths | **5** | `grep -rln "packages/.*tests" .github/workflows/` |
| pytest | **9.1.1** | `python -m pytest --version` |

### Existing Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]           # line 247
addopts = [                         # line 248
    "--strict-config",              # line 249
    "--strict-markers",             # line 250
]                                   # line 251
testpaths = ["tests"]               # line 252
python_files = "test_*.py"          # line 253
python_functions = "test_*"         # line 254
```

### Verified reproduction

```
$ python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py \
                   packages/parrot-formdesigner/tests/unit/test_version_and_docs.py --co -q
ImportError while loading conftest '…/packages/parrot-formdesigner/tests/conftest.py'.
_pytest.pathlib.ImportPathMismatchError: ('tests.conftest',
  '…/packages/ai-parrot-embeddings/tests/conftest.py',
  PosixPath('…/packages/parrot-formdesigner/tests/conftest.py'))

$ python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q
15 passed in 1.34s
```

### Does NOT Exist (Anti-Hallucination)
- ~~a per-package `pytest.ini` / `setup.cfg` / `[tool.pytest]` block~~ — pytest
  configuration exists **only** in the root `pyproject.toml:247`. Do not look
  for a per-distribution override to change instead.
- ~~`--import-mode` anywhere in the repo today~~ — `grep -n "import-mode"
  pyproject.toml` returns nothing. M2 introduces it.
- ~~an `__init__.py` in 3 of the 28 test roots~~ — `ai-parrot-advisors`,
  `ai-parrot-openlit-bridge` and `navrules` have none and need no change.
- ~~`packages/ai-parrot/.venv`~~ — only the repo-root `.venv` exists.
- ~~a fix via `--import-mode=importlib` alone~~ — **verified**: pytest still
  derives `tests.conftest` from the `__init__.py` chain and fails with
  `ValueError: Plugin already registered under a different name`. Both halves
  are required.
- ~~`consider_namespace_packages`~~ — not set in `pyproject.toml`; if M1 finds
  it helps, it is a **new** finding to add to this spec, not an assumed option.

### Edit Sites (Blueprint Anchors)

> Verified against `c2fd0ae28`. `/sdd-task` MUST re-run `grep -c` per row.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `pytest.ini` | MODIFY | `asyncio_mode = auto` (Amendment B: add the two settings below it) | `pytest.ini:3` | 1 |
| `packages/ai-parrot/tests/test_package_test_collection.py` | CREATE | — | — | — |
| ~60 import sites in 6 distributions | MODIFY | enumerated by **M1**, not guessed | `sdd/state/FEAT-720/spike-collect.md` | — |
| `packages/ai-parrot-server/tests/mcp/__init__.py` | MODIFY/RENAME | — (class (vi); shadows the real `mcp`) | confirmed present | 1 |

**Not an edit site** (listed to forestall the guess): all 242 nested
`packages/*/tests/**/__init__.py`, `ruff.toml`, `.github/workflows/*`, every
`packages/parrot-formdesigner/tests/*` assertion, `test_scope/*`.

---

## 7. Implementation Notes & Constraints

- **Worktree test invocation.** The shared `.venv` is editable-installed against
  the main checkout. Inside the worktree, prefix runs with
  `PYTHONPATH=packages/<dist>/src` (one entry per distribution involved). Never
  `uv sync` in a worktree.
- **M1 must run in the worktree.** Round 2's missing baseline is precisely the
  measurement the sandbox denied in the shared checkout. Do not re-attempt it in
  the main checkout.
- **Never `git add -A`.** The deletion set is exactly 25 files; stage them by
  explicit path. A wildcard add in a tree this wide will sweep another session's
  work — see the repo's concurrent-session hazard.
- **Collection, not execution, is the measurement.** AC2 compares `--collect-only`
  item counts. Running all 28 suites is neither required nor wanted: several are
  slow, and `parrot-formdesigner` is red for unrelated reasons (AC7).
- **`-p no:randomly`** when comparing counts, so ordering noise does not appear
  as a difference.
- **Ordering**: M1 → M2 → M3 → M4, with M2+M3 in one commit.
- **Do not fix FEAT-618's failures.** They will become more visible once
  collection works. AC7 makes leaving them alone a pass condition.

---

## 8. Open Questions

- [ ] Does `ai-parrot`'s `--collect-only` exit 4 pre-exist strategy (a)? —
      *Owner: M1.* Round 2 could not attribute it without a baseline. If it
      pre-exists, it is a separate issue and not this feature's to fix.
- [ ] Does any site need more than an import change to collect? — *Owner: M3.*
      The constraint says such a site is a finding, not an edit; this question
      records that the count is expected to be zero and must be stated even so.
- [ ] When is the landing window? — *Owner: Jesus Lara.* ~60 worktrees rebase
      through this commit. Needs a quiet window and an announcement; decide
      before opening the PR, not after.
- [ ] Should `consider_namespace_packages` be set alongside the import mode? —
      *Owner: M1.* Not set today; only adopt it on recorded evidence that (a)
      alone is insufficient.

---

## 9. Design Research Cross-Check

**Model**: —
**Status**: skipped (no `codex` seat was run for this spec. The design space is
two candidate strategies, both already measured against the real repository by
FEAT-618 `TASK-3908`; (b) is rejected on numbers and (a) is gated behind M1's
re-measurement, which is stronger evidence than an external opinion would be.
Re-run `/sdd-spec` with a codex seat if M1 returns `REFUTED`.)

| Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|
| — | — | — | — |

---

## Worktree Strategy

- **Isolation**: ONE feature worktree,
  `.claude/worktrees/feat-FEAT-720-tests-test-wheel-layout-tech-debt-2`, based
  on `origin/dev`.
- **Module dependency graph**: strictly linear — `M1 → M2 → M3 → M4`. M1 gates
  on its verdict line; M3 cannot be scoped until M1 enumerates the sites; M4
  asserts the state M2 creates. **No two tasks in this feature run
  concurrently**, which is unusual and intentional: the modules share
  `pyproject.toml` and the whole test tree.
- **Shared files**: effectively every file M2 and M3 touch — which is why they
  land in one commit rather than being serialized into two.
- **Exclusive resources**: **the entire repository's test collection semantics.**
  Every task here is `parallel: false`. While this feature's commit is in
  flight, no other worktree can trust a local pytest run against it.
- **Cross-feature dependencies**: none blocking. FEAT-618 is independent and
  must stay so (AC7). FEAT-620 is merged.
