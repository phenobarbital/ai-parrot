---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd, tests, ledger-fix]
docs:
  policy: none
---

# Feature Specification: Wheel-Only Foreign-Repo Test Maps the `task review record` Placeholders

**Feature ID**: FEAT-870
**Date**: 2026-11-10
**Author**: /sdd-fix (agent:sdd-fix:88be2347)
**Status**: approved
**Target version**: 2.1.3

**Discovered-from**: `issue:4e0a0d2635aa`

> Ledger-driven fix. Drains the `/sdd-fix` group `fixgroup:ba7c8a97592d` (`issue:4e0a0d2635aa`, major bug), found
> while validating FEAT-866. No brainstorm or proposal: the issue body is the requirement.

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py::test_install_then_every_documented_helper_invocation`
installs the SDD assets into a foreign repository from wheels, collects every documented `parrot sdd <noun> <verb>`
command line from the installed markdown, substitutes its placeholders, and runs it. Any token still containing `<`,
`$` or `...` after substitution fails the test (`_argv_for`, `:585-586`).

PR #2070 (HOTFIX-review-evidence-producer-3, commit `7308d681b4`) added this line to `/sdd-start`, in all four shipped
copies (`.claude/commands/sdd-start.md:278`, `.agents/skills/sdd-start/SKILL.md:133` and their `_assets` twins):

```
parrot sdd task review record --feature <slug> --task <id> --worktree <path> --summary "<review>"
```

`<slug>` and `--worktree <path>` are in the test's `COMMON` table (`:292-337`), but `<id>` and `<review>` are in
neither `COMMON` nor the `review_checkpoint` scenario (`:405`). On `dev` the test fails 1 of its 110 documented
invocations:

```
review_checkpoint: unresolved placeholder(s) ['<id>', '<review>'] in documented argv
'record --feature demo-feature --task <id> --worktree ... --summary "<review>"'
```

The test is marked `integration` and runs in the release workflow, so it blocks the release smoke job.

### Goals
- The `review_checkpoint` scenario maps `<id>` to `TASK-001` (the value `COMMON` already gives `<TASK-ID>`) and
  `<review>` to a fixed summary string.
- `test_install_then_every_documented_helper_invocation` passes on `dev` again, with the documented `record` line
  dispatched like every other helper invocation.

### Non-Goals (explicitly out of scope)
- Renaming the placeholders in the four `sdd-start` copies. `--task <id>` and `--summary "<review>"` read clearly,
  `<id>` and `<review>` occur only in that line of the shipped assets, and a rename would touch four byte-identical
  copies kept in sync by the asset tests, for no reader benefit.
- Adding `<id>` or `<review>` to `COMMON`: a bare `<id>` is too generic to fix globally for every helper.
- Tightening `review_checkpoint`'s accepted exit codes (`(0, 1, 2, 3)`); they apply to `prepare` and `validate` too.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:cd922d61de1a4b3015ae3c49e3468463fa9ab6e604e50139d39c7bb94d403e6d evaluation_digest=sha256:ce56699cd0712f3e0ae76b2b7689e9bbe675d58d8b311d7e0b062a108c83b376 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One test file, one edit, no source change. The `review_checkpoint` entry in `SCENARIOS` gains a scenario-scoped
`placeholders` mapping:

```python
"review_checkpoint": Scenario(
    prepare=_seed_worktree,
    expect_exit=(0, 1, 2, 3),
    placeholders={"<id>": "TASK-001", "<review>": "demo review"},  # `task review record` (sdd-start)
),
```

`_argv_for` merges `{**COMMON, **scenario.placeholders}` and replaces keys longest first, so the scenario entries
apply only to `review_checkpoint` invocations and cannot shadow a longer `COMMON` key (`<idx>` does not contain
`<id>`). In the shipped assets, `<id>` and `<review>` occur only in the `record` line; the `prepare` and `validate`
lines (`sdd-worker` agent docs) use `<FEAT-ID>`, `<path>` and `<uuid>`, which `COMMON` already maps. `_seed_worktree`
gives `record` a real feature worktree with a HEAD, so it runs past argument parsing.

### Integration Points
| Existing component | Interaction |
|---|---|
| `SCENARIOS["review_checkpoint"]` | gains `placeholders`; `prepare` and `expect_exit` unchanged |
| `_argv_for`, `COMMON` | unchanged |
| `/sdd-start` docs (four copies) | unchanged |
| `review_checkpoint.main` (`record`) | unchanged; now exercised by the test |

## 3. Module Breakdown

### Module 1: `review_checkpoint` scenario placeholders
- **Path**: `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py`
- **Responsibility**: the edit above.
- **Tests**: the file itself.

### Delegation-eligible modules
| Module | Eligible | Decided patterns / contracts |
|---|---|---|
| 1 | no | one-entry edit; implemented in the `/sdd-fix` session |

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_install_then_every_documented_helper_invocation` | 1 | existing; fails on `dev` (unresolved `<id>`/`<review>`), passes with the fix |
| rest of `test_wheel_only_foreign_repo.py` | 1 | existing; unchanged |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py
markers: none

## 5. Acceptance Criteria
- [ ] `SCENARIOS["review_checkpoint"]` maps `<id>` → `TASK-001` and `<review>` → a fixed summary; `prepare` and
      `expect_exit` are unchanged.
- [ ] `COMMON` and the four `sdd-start` copies are unchanged.
- [ ] `test_install_then_every_documented_helper_invocation` fails without the edit and passes with it, and its run
      dispatches the documented `task review record` line without a traceback.
- [ ] The Validation Contract file passes; `ruff check` is clean on it.

## 6. Codebase Contract

Verified against `origin/dev` @ `0db60f667e`.

### Verified Imports
None added. The test already defines `Scenario`, `SCENARIOS`, `COMMON`, `_seed_worktree` and `_argv_for`.

### Existing Signatures
```python
# packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py
pytestmark = pytest.mark.integration  # :26
def _seed_worktree(clone: Path) -> None  # :153; _seed_feature + `git worktree add .parrot/worktrees/feat-<FEAT>-<SLUG>`
COMMON: dict[str, str]  # :292; "<TASK-ID>": "TASK-001" :298; "--worktree <path>": ... :333
@dataclass class Scenario: placeholders: dict[str, str] = field(default_factory=dict); prepare; expect_exit: tuple[int, ...]  # :342
SCENARIOS: dict[str, Scenario]  # :364; "review_checkpoint": Scenario(prepare=_seed_worktree, expect_exit=(0, 1, 2, 3)) :405
def _argv_for(name: str, argv: str, scenario: Scenario, clone: Path) -> list[str]  # :572; values = {**COMMON, **scenario.placeholders}; unresolved assert
def test_install_then_every_documented_helper_invocation(managed_home, tools_dir, foreign_repo, tmp_path) -> None  # :598
# packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py
record_parser flags: --feature, --task, --worktree, --summary (required); --execution-id, --fix-commit (optional)  # :149-158
```

### Does NOT Exist
- No `<id>` or `<review>` key in `COMMON` or in any scenario's `placeholders`.
- No `placeholders` argument on the `review_checkpoint` scenario.
- No other shipped-asset line using `<id>` or `<review>` (only `sdd-start` :278 / `SKILL.md` :133).

### Edit Sites (Blueprint Anchors)
| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | `    "review_checkpoint": Scenario(prepare=_seed_worktree, expect_exit=(0, 1, 2, 3)),` | 405 | 1 | MODIFY |

## 7. Implementation Notes & Constraints
- The test builds wheels and installs them into a scratch home; it takes minutes. Run it in the background, from the
  worktree, with an absolute `PYTHONPATH=<wt>/packages/ai-parrot/src`.
- Prove the failure first: run the test before the edit and confirm the `review_checkpoint` unresolved-placeholder
  assertion, then after the edit confirm it passes.
- Ledger linkage: `issue:4e0a0d2635aa`.

### Known Risks / Gotchas
- `--summary "<review>"` is quoted in the docs; after substitution `shlex.split` yields one `demo review` token, which
  the unresolved check (`[<$]|\.\.\.`) accepts.
- If `record` raised a traceback in the foreign repo, the scenario would still fail; `review_checkpoint.main` reports
  store and git errors as JSON since FEAT-866 (PR #2073, merged).

## Worktree Strategy
One feature worktree, one module, one task. No shared files, no exclusive resources, no cross-feature dependency.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:cd922d61de1a4b3015ae3c49e3468463fa9ab6e604e50139d39c7bb94d403e6d evaluation_digest=sha256:ce56699cd0712f3e0ae76b2b7689e9bbe675d58d8b311d7e0b062a108c83b376 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/commands-sdd-start-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: ledger-fix, tests
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "ledger-fix",
      "tests"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/commands-sdd-start-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:ce56699cd0712f3e0ae76b2b7689e9bbe675d58d8b311d7e0b062a108c83b376",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:cd922d61de1a4b3015ae3c49e3468463fa9ab6e604e50139d39c7bb94d403e6d",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions
- [x] Fix the test's placeholder table or rename the doc placeholders? — *Resolved in /sdd-fix research*: the test,
      scoped to the `review_checkpoint` scenario; the docs read clearly and live in four synced copies.

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
None: test-only change.

## Revision History
| Date | Change |
|---|---|
| 2026-11-10 | Initial spec from `/sdd-fix` group `fixgroup:ba7c8a97592d` |
