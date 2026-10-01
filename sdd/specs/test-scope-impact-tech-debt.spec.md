---
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop, sdd-tooling]
tags: [test-scope, merge-tier, impact-analysis, core-detection, tech-debt, ledger]
---

# Feature Specification: Direct-Importer Core Detection for the Merge-Tier Gate

**Feature ID**: FEAT-620
**Date**: 2026-10-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.7

**Resolves**: `issue:7f2f3d4d7828` — *Transitive `source_fanin` makes leaf
modules "core", escalating all 26 distributions on a merge-tier plan*
(kind `tech_debt`, severity `major`, `discovered_from: spec:FEAT-618`).

> **Ownership note.** FEAT-618's Non-Goals assign `impact.py` re-architecture
> to FEAT-604, but FEAT-604 closed on 2026-09-25 with all six tasks `done`
> and its spec never mentions `source_fanin` or `detect_core`. The declared
> owner is therefore closed and this work has no open home, so `/sdd-fix`
> provisioned a new spec rather than widening FEAT-618 against its own
> Non-Goals. The slug `test-scope-impact-tech-debt` is the planner's
> `suggested_slug` for `fixgroup:8279902ed9d1`, used verbatim.

---

## 1. Motivation & Business Requirements

### Problem Statement

`coder_run_validation(tier="merge")` decides whether an `sdd-coder` task may
merge. Its cost and its false-failure rate are both driven by *core
detection*: a changed source file judged "core" escalates the **package
suite of every distribution that transitively imports it**. FEAT-618
measured the consequence (`issue:181bd0c01bb4`): ~2800 unrelated tests,
carrying other packages' red baselines, pulled into a single task's gate.

FEAT-618 TASK-3909 added `ScopePolicy.escalate_foreign_dists` to guard the
**cap** path. `issue:7f2f3d4d7828` records that this changed the measured
plan **not at all** — plans were byte-identical with the guard on and off —
because `cap_hits` was empty. The entire blast radius came from
`detect_core()`.

### Root cause

`source_fanin()` (`impact.py:244`) walks `src_importers` **transitively with
no depth bound**. A leaf module imported by one in-package hub inherits that
hub's entire upstream closure. The metric therefore saturates and stops
discriminating.

Measured on `dev` at `76a7d7b22` (2688 source modules, 28 distributions;
reproduce with §6 *Evidence*):

| file | role | direct importers | **transitive (today)** | transitive, cross-dist only |
|---|---|---:|---:|---:|
| `parrot/outputs/a2ui/linked/dsl.py` | self-contained leaf | **2** | **1041** / 26 dists | 551 / 25 dists |
| `parrot/clients/base.py` | genuine core | 35 | 1024 / 26 dists | 544 / 25 dists |
| `parrot/bots/abstract.py` | genuine core | 31 | 1024 / 26 dists | 544 / 25 dists |
| `parrot/tools/abstract.py` | genuine core | 151 | 1024 / 26 dists | 544 / 25 dists |
| `parrot/flows/dev_loop/test_scope/impact.py` | leaf | 1 | 60 / 2 dists | 8 / 1 dist |

Two conclusions, both load-bearing for the design:

1. **The transitive metric has no discriminating power.** The leaf scores
   *higher* (1041) than the genuine core module (1024). `core_fanin_threshold
   = 50` is not mis-tuned — every `ai-parrot` module saturates at ~1024–1041,
   so any threshold in that range is arbitrary.
2. **Restricting the count to foreign distributions does not fix it.** The
   BFS still passes *through* the in-package hub and inherits its foreign
   closure, so `dsl.py` (551/25) remains indistinguishable from
   `clients/base.py` (544/25). This option was measured and rejected.

**Direct-importer count separates cleanly** — a ~15x margin between the leaf
(2) and the genuine core modules (31–151) — and the top of that ranking is
exactly the set of real hubs:

```
174  parrot.conf
151  parrot.tools.abstract  (= parrot_tools.abstract)
105  parrot.tools.toolkit   (= parrot_tools.toolkit)
 60  parrot.models.outputs
 53  parrot._imports
 52  parrot.outputs.a2ui.models
```

Calibration over all 2688 modules: `>= 20` direct importers selects 45
modules (1.7%), `>= 30` selects 29 (1.1%), `>= 50` selects 12 (0.4%).

### The second escalation path: `CORE_PATHS`

`detect_core()` escalates when `forced or fanin >= threshold`, where
`forced = path in policy.core_paths`. `CORE_PATHS` (`policy.py:12`) holds
**724 entries**, every one derived by the FEAT-563 S4 spike from the same
saturated transitive metric (its inline comments read `# fan-in 77 (ast)`).

Measured against direct importers, **96% of `CORE_PATHS` does not clear a
30-importer bar**:

| direct importers | entries of 724 | share |
|---|---:|---:|
| `>= 10` | 116 | 16.0% |
| `>= 20` | 42 | 5.8% |
| `>= 30` | 29 | 4.0% |
| `>= 50` | 12 | 1.7% |

The tail includes entries with **zero** direct importers —
`parrot/core/__init__.py`, `parrot/cli/__init__.py`,
`parrot/knowledge/__init__.py`, `parrot/flows/__init__.py`,
`parrot_formdesigner/__init__.py` — each of which unconditionally escalates
every distribution reached from it. 623 of the 724 are in `ai-parrot` alone.

**Fixing `source_fanin` alone is therefore not sufficient.** It fixes the
`dsl.py`-shaped case (a module absent from `CORE_PATHS`), but any diff
touching one of the 724 force-listed files still escalates the repo. Both
paths must move together or the gate's cost does not change for most diffs.

### Goals

1. `source_fanin()` measures **direct** importers, so a self-contained leaf
   module is never core by fan-in.
2. `core_fanin_threshold` is recalibrated to a value justified by measured
   data, not inherited from the saturated metric.
3. `CORE_PATHS` is re-derived under the new metric, so the forced path
   cannot reintroduce the blast radius the fan-in path just removed.
4. A genuine hub (`parrot.conf`, `tools/abstract.py`, `clients/base.py`,
   `bots/abstract.py`) is still detected as core — the fix must not create
   false negatives on the gate.
5. Regressions of 1–4 are caught by tests that assert the *separation*, not
   just a single value.

### Non-Goals (explicitly out of scope)

- The escalation ledger (`context.py`) and the cap path (`select.py` cap
  handling, `ScopePolicy.impact_cap`). FEAT-604 delivered those and they are
  not implicated: `cap_hits` was empty in the measured plan.
- `ScopePolicy.escalate_foreign_dists` and anything else on the unmerged
  FEAT-618 branch. This feature bases on `origin/dev` and must not depend on
  FEAT-618 landing first; the two changes are independent and compose.
- `impacted_tests()` / `_expand_modules()` / `DEFAULT_IMPACT_DEPTH`. The
  test-impact walk is a different question from core detection and already
  defaults to depth 1.
- The `parrot-formdesigner` red baseline and the `tests/__init__.py`
  collection collision — FEAT-618 owns both.
- Changing what an escalation *runs* once a core hit is declared (the
  package-suite expansion in `select.py`). This feature changes only which
  files are declared core.

---

## 2. Design

### M1 — `source_fanin` counts direct importers

`source_fanin(index, module)` drops its BFS and returns the direct
`src_importers` of `module` (alias-expanded, as today) plus their
distributions. The signature `(int, frozenset[str])` is unchanged, so
`detect_core` and `CoreHit.fanin` keep their shapes; only the semantics of
the number change, which is documented at every definition site.

Cycle safety becomes structural rather than bookkeeping: with no traversal
there is no revisit, so `test_source_fanin_is_cycle_safe` must keep passing
without the `seen`/`visited` machinery.

The existing `# FEAT-563 fix, TASK-3318 S4 finding` comment in
`ImportIndex.build` (`impact.py:140-151`) explains why `src_importers` holds
exact-target edges only, specifically to protect the transitive BFS from
flooding. That rationale is now partly obsolete; the comment is updated, not
deleted, and the exact-target behaviour is **kept** — it is still correct for
a direct count and the alternative would over-count ancestor packages.

### M2 — recalibrate `DEFAULT_CORE_FANIN_THRESHOLD`

`50 → 30`. Justification is the §1 calibration table: 30 selects 29 modules
(1.1% of 2688) as core by fan-in, sits an order of magnitude above the leaf
cases (1–2) and below every genuine hub measured (31, 35, 151). The constant
carries a comment citing the measurement and its date.

### M3 — re-derive `CORE_PATHS`

A script regenerates `CORE_PATHS` from the live import index under the new
metric, and the generated tuple replaces the 724 hand-pasted entries. The
script is committed so the list is reproducible rather than archaeological.

`CORE_PATHS` exists for files the AST under-counts — dynamic imports,
registries, and the `parrot.tools.<x>` ↔ `parrot_tools.<x>` meta_path
redirect. That purpose survives: entries are retained when they are
*measurably* hub-like under the new metric, and the alias pairs
(`parrot/tools/abstract.py` and `parrot_tools/abstract.py` both appear at
151) stay paired. Entries with zero direct importers are dropped — a module
nothing imports cannot be core under any honest reading of "core".

### M4 — documentation

`docs/dev_loop/sdd-coder-orchestrator.md:582-596` describes the metric as
"transitive source fan-in … `≥ DEFAULT_CORE_FANIN_THRESHOLD` (50)" and
carries a 2026-09-17 cost callout saying `CORE_PATHS` has 724 entries and
that `clients/base.py` / `bots/abstract.py` escalate to ~25 of 26
distributions. Both the description and the callout are brought in line with
what ships.

---

## 3. Acceptance Criteria

- **AC1** `source_fanin(index, m)` returns the count of modules importing `m`
  directly, alias-expanded, and their distributions. No transitive hop.
- **AC2** On an index built from the repo, `dsl.py` is **not** a core hit
  under the shipped default policy, and `clients/base.py`,
  `bots/abstract.py`, `tools/abstract.py` and `parrot/conf.py` all **are**.
- **AC3** `DEFAULT_CORE_FANIN_THRESHOLD == 30`, with the measurement cited
  in a comment.
- **AC4** Every retained `CORE_PATHS` entry resolves to a file that exists on
  `dev` and has a non-zero direct-importer count; the regeneration script is
  committed and rerunning it reproduces the committed tuple byte-for-byte.
- **AC5** `forced` escalation still works: a path in `core_paths` is a core
  hit regardless of its fan-in (the mechanism is unchanged, only the list
  shrinks).
- **AC6** A synthetic fixture where module `L` is imported only by hub `H`,
  and `H` is imported by 40 modules, yields `fanin(L) == 1` and
  `fanin(H) == 40` — the inheritance bug cannot return.
- **AC7** `test_source_fanin_is_cycle_safe` passes unchanged.
- **AC8** The full `test_scope` and `sdd_coder` test suites pass.

---

## 4. Risks

- **False negatives on the gate.** A true hub reached mostly through
  re-exporting `__init__.py` shims could drop below 30 direct importers.
  Mitigated by M3 (`CORE_PATHS` keeps the measured exceptions) and by AC2
  pinning the four known hubs. The measured margin (31 vs 2) gives room.
- **`CORE_PATHS` churn.** Shrinking a 724-entry list is a large diff and a
  real behaviour change for every gate run. It is the point of the feature,
  but it lands in its own commit with the generator beside it so it can be
  audited and regenerated.
- **Index-dependent constants.** `CORE_PATHS` is a snapshot of a moving
  codebase. The generator makes drift detectable; keeping the list current
  is not automated here.

---

## 5. Validation

```bash
PYTHONPATH=packages/ai-parrot/src python -m pytest \
  packages/ai-parrot/tests/flows/dev_loop/test_scope -q -p no:randomly
PYTHONPATH=packages/ai-parrot/src python -m pytest \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder -q -p no:randomly
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/
```

## 6. Evidence

Every number in §1 was measured on `dev` at `76a7d7b22` by building a real
`ImportIndex` over the checkout and comparing `source_fanin` against
depth-bounded variants. The measurement harness is reproduced as the
regeneration script in M3; the spike outputs are recorded in the task files.
