---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [sdd-flow, necessity-ladder, spec-lint, cli]
docs:
  policy: required
  pages: [wiki/sdd-tooling/sdd/necessity-ladder.md]
  api_modules: [parrot.sdd.scripts.check_spec_ladder]
---

# Feature Specification: `parrot sdd spec ladder` — deterministic check of a spec's Necessity Ladder

**Feature ID**: FEAT-909
**Date**: 2026-11-17
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 2.1.4

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-908 (`sdd/specs/ponytail-like-stairway.spec.md`) adds a `#### Necessity Ladder` table to every
spec and a Lean Review (checks L1–L10) to `/sdd-spec`. Six of those checks are mechanical —
coverage (L1), reuse evidence (L2), new-code proof (L3), files (L4), dependencies (L5) and tests
(L9) — but FEAT-908 leaves them in the prompt: the model runs `grep`/`sed` by hand and decides
whether they passed. That is the same situation the task graph was in before
`parrot sdd task graph` existed: a rule written in prose and trusted to the author of the text it
checks. The model also adds up the `Totals` line and the `Ladder:` output line itself.

FEAT-908 §8 Q1 resolved that these checks become a command, specified separately. This is that
spec.

### Goals

- **G1 — One command checks the mechanical part.** `parrot sdd spec ladder <spec>` runs L1–L5 and
  L9 over a spec and reports each failure with a stable code.
- **G2 — Exit codes a command can branch on**, in the style of `parrot sdd spec consequences`:
  `0` pass or skipped · `1` findings · `2` invalid table.
- **G3 — The totals are computed, not typed.** The command verifies the table's `Totals` line and
  prints the `Ladder:` line that `/sdd-spec` §7 outputs.
- **G4 — Old specs are not broken.** A spec with no `#### Necessity Ladder` table is `skipped`
  (exit 0).
- **G5 — `/sdd-spec` §5a uses it** and refuses `approved` on a non-zero exit; the checks that need
  judgement (L6, L7, L8, L10) stay in the prompt.

### Non-Goals (explicitly out of scope)

- Changing the table format, the rungs or the Lean Review rules — FEAT-908 owns them.
- Judging whether a reuse is the right one, or whether a module is needed. The command checks that
  the evidence a row cites exists, not that the decision is good.
- Deferred: checking that the cited symbol actually appears on the cited line (the second half of
  L2) — justified once anchors that point at the right file but the wrong line are seen in real
  specs; today the "Reuses" cell is free text and a symbol match would be a heuristic.
- Deferred: the L7 speculation scan as a finding — its hits need a person to judge, so it stays as
  the fenced `grep` in §5a.
- Deferred: an `--advisory` mode for `/sdd-task` (like `consequences --advisory`) — justified if
  specs reach decomposition with a failing ladder.
- Deferred: comparing an implementation's `git diff --numstat` with "Est. LOC" — FEAT-908 §8 Q3
  settled that exceeding the estimate is a review finding, not a gate.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:c2f0e78a4a911449e738c1036fbd547fb3d60be34123573ae37c722092bd080a evaluation_digest=sha256:76865dfa84b4d1144910a204c35ff5fc3ae33b446b0500d2c51ae0b1ea869537 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One new helper module, `parrot.sdd.scripts.check_spec_ladder`, registered as the `ladder` verb of
the existing `spec` noun in `parrot sdd`. It reads one spec file, parses five things out of it —
the ladder table, the `### Module N` blocks with their `**Path**` bullets, the §4 Unit Tests
table, the §6 Edit Sites table and the §7 External Dependencies table — and checks them against
each other and against the files under `--root`. It never writes.

```
parrot sdd spec ladder sdd/specs/<feature-name>.spec.md [--root .] [--json]
```

Checks and their finding codes (an **error** fails the check, a **warning** does not):

| Lean Review | Code | Level | Fails when |
|---|---|---|---|
| L1 | `module-without-row` | error | a `### Module N` heading has no ladder row |
| L1 | `row-without-module` | error | a ladder row names a module with no `### Module N` heading |
| L1 | `duplicate-row` | error | a module has more than one row |
| L1 | `unknown-rung` | error | the Rung cell is not one of R2–R7 |
| L2 | `evidence-missing` | error | an R2, R4 or R5 row cites no `path:NN` |
| L2 | `evidence-path-missing` | error | a cited path does not exist under `--root` |
| L2 | `evidence-line-out-of-range` | error | the cited file has fewer than `NN` lines |
| L2 | `evidence-not-in-contract` | error | an R2 row's cited path does not appear in §6 |
| L2 | `single-change-without-edit-site` | error | an R6 module has no MODIFY row in §6 Edit Sites |
| L3 | `new-code-without-proof` | error | an R7 row does not contain both `Does NOT Exist` and `query:` |
| L4 | `create-outside-new-module` | error | a CREATE row in Edit Sites belongs to no R7 module's `**Path**` list |
| L5 | `undeclared-dependency` | error | a §7 External Dependencies package is in no tracked manifest and no R7 row names it |
| L9 | `new-code-without-test` | warning | an R7 module has no §4 Unit Tests row |
| L9 | `test-for-reused-code` | warning | a §4 Unit Tests row targets an R2–R6 module |
| Totals | `totals-mismatch` | error | the `Totals` line is missing or disagrees with the rows and the `Deferred:` lines |
| — | `manifests-unreadable` | warning | `git ls-files` failed, so L5 was not run |

L9 is a warning because the rule is "every R7 row *with logic*" and the command cannot tell
whether a row has logic.

Statuses and exit codes: `pass` → 0 · `skipped` (no table) → 0 · `fail` (at least one error) → 1 ·
`invalid` (the table exists but cannot be parsed: wrong column count, no rows, or the spec file is
unreadable) → 2.

Text output, one line per finding plus the computed line:

```
sdd/specs/<feature-name>.spec.md: fail — 6 modules, 2 error(s), 1 warning(s)
  ERROR   create-outside-new-module: M2 — `src/pkg/new.py` is CREATE but M2 is R2
  ERROR   totals-mismatch: Totals says new 3, rows say new 2
  WARNING new-code-without-test: M4 — R7 with no §4 Unit Tests row
Ladder: reuse 1 · stdlib/platform 0 · dependency 1 · single change 0 · new 2 · deferred 3 · est. new LOC 140
```

`/sdd-spec` §5a then starts with this command; L6, L7, L8 and L10 remain as prompt checks.

### Component Diagram

```
/sdd-spec §5a ──→ parrot sdd spec ladder <spec>
                        │
        parrot.sdd.cli VERBS["spec"]["ladder"] ──→ check_spec_ladder.main()
                        │
            check_ladder(spec, root) ──→ LadderReport ──→ text | --json ──→ exit 0 | 1 | 2
                        │
        reads: the spec file · files cited as evidence · `git ls-files` (manifests)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.cli.VERBS` | extends | One entry under `"spec"`; the helper is imported lazily like every other verb |
| `parrot.sdd.scripts.check_task_graph` | follows | Same shape: Pydantic `Finding`/report models, `format_report`, `main(argv) -> int`, `--root`, `--json` |
| `/sdd-spec` §5a (added by FEAT-908) | extends | Runs the command before the manual checks |
| `test_wheel_only_foreign_repo.py` `SCENARIOS` | extends | Every `parrot sdd <noun> <verb>` named in installed markdown needs a scenario, or the release's `smoke-sdd-foreign` job fails |
| `scripts/sdd/check_asset_sync.py` | uses | Regenerates `_assets/` after the command twins change |

### Data Models

```python
class LadderRow(BaseModel):
    """One row of a spec's `#### Necessity Ladder` table."""
    module: str            # normalized id, "M1"
    name: str
    rung: str              # "R2" … "R7" (validated by the check, not by the model)
    reuses: str            # raw cell text
    serves: str
    new_code: str
    est_loc: int | None    # None when the cell holds no number


class LadderFinding(BaseModel):
    """One problem found in a ladder table."""
    level: str             # "error" | "warning"
    code: str
    modules: list[str] = Field(default_factory=list)
    message: str


class LadderReport(BaseModel):
    """Result of checking one spec."""
    spec: str
    status: str            # "pass" | "fail" | "skipped" | "invalid"
    rows: list[LadderRow] = Field(default_factory=list)
    deferred: int = 0
    ladder_line: str = ""
    findings: list[LadderFinding] = Field(default_factory=list)
```

### New Public Interfaces

```python
def parse_ladder(spec_md: str) -> list[LadderRow] | None: ...
def check_ladder(spec_path: Path, root: Path) -> LadderReport: ...
def format_report(report: LadderReport) -> str: ...
def main(argv: list[str] | None = None) -> int: ...
```

---

## 3. Module Breakdown

#### Necessity Ladder

<!-- Written in the FEAT-908 format so this spec can be the command's first real input. -->

| Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC |
|---|---|---|---|---|---|
| M1: Ladder check helper | R7 | Report/CLI shape of `check_task_graph` — verified: `packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py:83`, `:710`. Nothing covers it: Does NOT Exist `parrot.sdd.scripts.check_spec_ladder`, and no reusable Markdown-table parser (query: `grep -rnE "def .*(table\|row)[a-z_]*\(" packages/ai-parrot/src/parrot/sdd packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder packages/ai-parrot/src/parrot/flows/dev_loop/test_scope` → no table parser; `parse_declared_files` reads only a task's file list) | G1–G4 | 3 models, 4 public functions, 7 private checks | ~260 |
| M2: CLI verb | R6 | `VERBS["spec"]` — verified: `packages/ai-parrot/src/parrot/sdd/cli.py:314` | G1 | one dict entry | ~1 |
| M3: `/sdd-spec` §5a calls the command | R7 | §5a Lean Review (FEAT-908) and the §5b wording for exit codes — verified: `.claude/commands/sdd-spec.md:612`. Nothing covers it: Does NOT Exist a `parrot sdd spec ladder` mention (query: `git grep -l -F "spec ladder" -- .claude .agent .agents` → 0 files) | G5 | one paragraph + one fenced command × 2 full twins, one bullet in the codex twin | ~25 |
| M4: Tests and release-smoke scenario | R7 | Scenario pattern — verified: `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:417`. Nothing covers it: Does NOT Exist `packages/ai-parrot/tests/sdd/test_check_spec_ladder.py` (query: `ls` → no such file) | G1–G5 | one `SCENARIOS` entry (the test file itself is test code) | ~5 |
| M5: Documentation and packaged assets | R7 | Asset regeneration — verified: `scripts/sdd/check_asset_sync.py:26`. Nothing covers it: Does NOT Exist a "Command" section in `wiki/sdd-tooling/sdd/necessity-ladder.md` (query: the page is created by FEAT-908 without it) | G1, G2 | one wiki section; `_assets/` regenerated by the existing script | ~40 |

Totals: 5 modules — reuse 0 · stdlib/platform 0 · dependency 0 · single change 1 · new 4 · deferred 4 · est. new LOC ~331

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Ladder check helper | yes | Models, signatures, finding codes, levels and exit codes are fixed in §2 and below | — |
| M2: CLI verb | yes | Exact line below | — |
| M3: `/sdd-spec` §5a | yes | Exact text below | — |
| M4: Tests and scenario | yes | Test names in §4, scenario line below | — |
| M5: Documentation and assets | yes | Section content from §2 | — |

### Module 1: Ladder check helper

- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/check_spec_ladder.py`
- **Responsibility**: Parse a spec's ladder and the sections it refers to; report findings; exit with the status code.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/check_spec_ladder.py  (new)
  # shape follows check_task_graph — verified: packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py:83-104, 695-726
  """``check_spec_ladder.py`` — deterministic check of a spec's Necessity Ladder (FEAT-909).

  Exit matrix: 0 pass|skipped · 1 fail (at least one error finding) · 2 invalid (unparseable table or spec).
  """
  from __future__ import annotations

  import argparse
  import json
  import re
  import subprocess
  from pathlib import Path

  from pydantic import BaseModel, Field

  LADDER_HEADING: str = "#### Necessity Ladder"
  RUNGS: tuple[str, ...] = ("R2", "R3", "R4", "R5", "R6", "R7")
  MANIFEST_GLOBS: tuple[str, ...] = ("*pyproject.toml", "*package.json", "*Cargo.toml", "*requirements*.txt", "*go.mod")
  EXIT_BY_STATUS: dict[str, int] = {"pass": 0, "skipped": 0, "fail": 1, "invalid": 2}


  class LadderRow(BaseModel): ...        # fields in §2 Data Models
  class LadderFinding(BaseModel): ...    # fields in §2 Data Models
  class LadderReport(BaseModel):         # fields in §2 Data Models
      @property
      def errors(self) -> list[LadderFinding]:
          """Findings that fail the check."""


  def parse_ladder(spec_md: str) -> list[LadderRow] | None:
      """Rows of the `#### Necessity Ladder` table, in order.

      Returns None when the spec has no such heading. The table is the first run of `|` lines after the
      heading; HTML comments, the header row and the separator row are skipped.

      Raises:
          ValueError: The heading exists but a row does not have six cells, or there are no rows.
      """


  def check_ladder(spec_path: Path, root: Path) -> LadderReport:
      """Run L1–L5, L9 and the Totals check over one spec.

      Never raises for a bad spec: an unreadable file or a ValueError from `parse_ladder` yields
      status "invalid" with one error finding (`unreadable-spec` / `malformed-table`).
      Module ids are normalized ("### Module 3: X" and "M3: X" both → "M3").
      Evidence citations are every `path:NN` inside backticks in the "Reuses" cell.
      Manifests are the tracked files matching MANIFEST_GLOBS (`git ls-files` with cwd=root);
      when git fails, L5 is skipped with the `manifests-unreadable` warning.
      """


  def format_report(report: LadderReport) -> str:
      """Human-readable report: a status line, one line per finding (errors first), then the `Ladder:` line."""


  def main(argv: list[str] | None = None) -> int:
      """CLI entry point: `<spec> [--root .] [--json]`; returns EXIT_BY_STATUS[report.status]."""


  # private, one per check — each returns list[LadderFinding]
  def _check_coverage(rows: list[LadderRow], modules: dict[str, list[str]]) -> list[LadderFinding]: ...            # L1
  def _check_reuse_evidence(rows: list[LadderRow], spec_md: str, edit_sites: dict[str, str], modules: dict[str, list[str]], root: Path) -> list[LadderFinding]: ...  # L2
  def _check_new_code_proof(rows: list[LadderRow]) -> list[LadderFinding]: ...                                    # L3
  def _check_create_rows(rows: list[LadderRow], edit_sites: dict[str, str], modules: dict[str, list[str]]) -> list[LadderFinding]: ...  # L4
  def _check_dependencies(rows: list[LadderRow], packages: list[str], root: Path) -> list[LadderFinding]: ...     # L5
  def _check_tests(rows: list[LadderRow], tested_modules: list[str]) -> list[LadderFinding]: ...                  # L9
  def _check_totals(rows: list[LadderRow], deferred: int, spec_md: str) -> tuple[str, list[LadderFinding]]: ...   # returns (ladder_line, findings)
  ```
  Section readers the checks need (private; each takes the spec text):
  `modules` = `{"M1": [paths in the module's **Path** bullet]}` from `### Module N` blocks;
  `edit_sites` = `{path: "CREATE" | "MODIFY"}` from the table under `### Edit Sites`;
  `packages` = backticked first cells of the table under `### External Dependencies`;
  `tested_modules` = normalized Module cells of the table under `### Unit Tests`;
  `deferred` = number of `- Deferred:` lines under `### Non-Goals`.
  The `Ladder:` line format is exactly the one in `/sdd-spec` §7:
  `Ladder: reuse <R2> · stdlib/platform <R3+R4> · dependency <R5> · single change <R6> · new <R7> · deferred <k> · est. new LOC <sum>`.

### Module 2: CLI verb

- **Path**: `packages/ai-parrot/src/parrot/sdd/cli.py`
- **Responsibility**: Expose the helper as `parrot sdd spec ladder`.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/cli.py — new entry in VERBS["spec"], after the "consequences" line
  # verified: packages/ai-parrot/src/parrot/sdd/cli.py:314
          "ladder": ("check_spec_ladder", (), "Check a spec's Necessity Ladder (FEAT-909)."),
  ```

### Module 3: `/sdd-spec` §5a calls the command

- **Path**: `.claude/commands/sdd-spec.md`, `.agent/workflows/sdd-spec.md`, `.agents/skills/sdd-spec/SKILL.md`
- **Responsibility**: Make the Lean Review start with the command.
- **Depends on**: M2 (the text names a verb that must exist); FEAT-908 (§5a must exist).
- **Interface Skeleton**:
  ````text
  # .claude/commands/sdd-spec.md and .agent/workflows/sdd-spec.md (same lines in both)
  # inserted directly under the "### 5a. Lean Review (checks the Necessity Ladder — never asks)" heading,
  # before its first paragraph (anchor exists only after FEAT-908 merges — unverified, check before use)
  Run the mechanical checks first:

  ```bash
  parrot sdd spec ladder sdd/specs/<feature-name>.spec.md
  ```

  Exit codes: `0` pass or skipped · `1` findings · `2` invalid table. It covers L1–L5 and L9 and
  verifies the `Totals` line; fix every `ERROR` in the spec and re-run. **Refuse
  `**Status**: approved` on a non-zero exit.** Copy the `Ladder:` line it prints into the §7
  output. L6, L7, L8 and L10 are still checked by hand, below.

  # .agents/skills/sdd-spec/SKILL.md — extend the Lean Review bullet FEAT-908 adds to step 10 with:
      Start with `parrot sdd spec ladder <spec>` (exit 0 pass/skipped · 1 findings · 2 invalid).
  ````

### Module 4: Tests and release-smoke scenario

- **Path**: `packages/ai-parrot/tests/sdd/test_check_spec_ladder.py`, `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py`
- **Responsibility**: Cover every finding code and exit code; keep the release smoke job green.
- **Depends on**: M1, M2, M3.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/sdd/test_check_spec_ladder.py  (new)
  # import style verified: packages/ai-parrot/tests/sdd/test_techwiki_check.py:7
  from parrot.sdd.scripts import check_spec_ladder

  def _spec(tmp_path: Path, **overrides: str) -> Path:
      """Write a minimal valid spec (2 modules: one R2, one R7) with the named sections replaced."""

  # packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py — new SCENARIOS entry, before "check_task_graph"
  # verified: packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:417-422  (the seeded spec has no table → skipped, exit 0)
      "check_spec_ladder": Scenario(prepare=_seed_feature, placeholders={"<feature-name>": SLUG}),
  ```

### Module 5: Documentation and packaged assets

- **Path**: `wiki/sdd-tooling/sdd/necessity-ladder.md`, `packages/ai-parrot/src/parrot/sdd/_assets/` (regenerated)
- **Responsibility**: Document the command; bring the packaged command copies in line.
- **Depends on**: M3 (assets are copied from the final command text).
- **Interface Skeleton**:
  ```text
  # wiki/sdd-tooling/sdd/necessity-ladder.md — new "## Command" section (page created by FEAT-908):
  #   usage line, the finding-code table of §2, statuses and exit codes, one sample report.
  # packaged assets: python scripts/sdd/check_asset_sync.py --write   # verified: scripts/sdd/check_asset_sync.py:26
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_parse_ladder_returns_rows_in_order` | M1 | Six cells per row, ids normalized, `~80` → 80 |
| `test_parse_ladder_none_without_heading` | M1 | No heading → `None` |
| `test_parse_ladder_rejects_wrong_column_count` | M1 | `ValueError` |
| `test_valid_spec_passes_and_prints_ladder_line` | M1 | Status `pass`, exit 0, exact `Ladder:` line |
| `test_spec_without_table_is_skipped` | M1 | Status `skipped`, exit 0 |
| `test_malformed_table_is_invalid` | M1 | Status `invalid`, exit 2, no traceback |
| `test_coverage_findings` | M1 | `module-without-row`, `row-without-module`, `duplicate-row`, `unknown-rung` |
| `test_reuse_evidence_findings` | M1 | `evidence-missing`, `evidence-path-missing`, `evidence-line-out-of-range`, `evidence-not-in-contract`, `single-change-without-edit-site` |
| `test_new_code_needs_proof` | M1 | `new-code-without-proof` when either `Does NOT Exist` or `query:` is absent |
| `test_create_row_must_belong_to_new_module` | M1 | `create-outside-new-module` for an R2 module and for an unowned path |
| `test_dependency_must_be_declared_or_justified` | M1 | `undeclared-dependency`; passes when a tracked manifest names it or an R7 row does |
| `test_manifests_unreadable_is_a_warning` | M1 | Outside a git repository L5 is skipped with the warning, exit unaffected |
| `test_test_rows_are_warnings` | M1 | `new-code-without-test`, `test-for-reused-code`; exit 0 |
| `test_totals_mismatch` | M1 | Wrong count, wrong LOC sum and missing line each raise `totals-mismatch` |
| `test_json_output_is_the_report` | M1 | `--json` prints `LadderReport.model_dump()` |
| `test_cli_dispatches_ladder` | M2 | `VERBS["spec"]["ladder"]` resolves to `check_spec_ladder` |
| `test_sdd_spec_twins_call_the_command` | M3 | Both full twins and the codex skill name `parrot sdd spec ladder` |

### Integration Tests

| Test | Description |
|---|---|
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | The verb table stays consistent |
| `packages/ai-parrot/tests/sdd/test_sdd_cli_import_light.py` | Importing the CLI still does not import the helpers |
| `tests/sdd_scripts/test_check_asset_sync.py` | `_assets/` matches its sources |

### Validation Contract

> The release-only `test_wheel_only_foreign_repo.py` is not listed: it needs a built wheel. Its
> scenario is covered by AC 7.

tests:
- packages/ai-parrot/tests/sdd/test_check_spec_ladder.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/sdd/test_sdd_cli_import_light.py
- tests/sdd_scripts/test_necessity_ladder_contract.py
- tests/sdd_scripts/test_check_asset_sync.py
- tests/sdd_scripts/test_command_contracts.py
- packages/ai-parrot/tests/sdd/test_consult_step_twins.py
markers: none

### Test Data / Fixtures

```python
# A minimal valid spec written under tmp_path by `_spec()`; `git init` + one commit in tmp_path for the L5 tests.
```

---

## 5. Acceptance Criteria

- [ ] AC 1 — `parrot sdd spec ladder <spec>` exists and `parrot sdd spec --help` lists `ladder`.
- [ ] AC 2 — Exit codes: 0 for `pass` and `skipped`, 1 for `fail`, 2 for `invalid`; no input produces a traceback.
- [ ] AC 3 — Every finding code in the §2 table is produced by at least one test, at the level the table states.
- [ ] AC 4 — On a passing spec the command prints a `Ladder:` line in the exact `/sdd-spec` §7 format.
- [ ] AC 5 — `parrot sdd spec ladder sdd/specs/ponytail-like-stairway.spec.md` and `parrot sdd spec ladder sdd/specs/sdd-spec-ladder-check.spec.md` exit 0 from the repository root.
- [ ] AC 6 — `.claude/commands/sdd-spec.md` §5a starts with the command and states the refusal on non-zero exit; `.agent/workflows/sdd-spec.md` stays byte-identical below its frontmatter; the codex skill names the command.
- [ ] AC 7 — `SCENARIOS` in `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` has a `check_spec_ladder` entry.
- [ ] AC 8 — `python scripts/sdd/check_asset_sync.py --check` exits 0.
- [ ] AC 9 — Every test in the §4 Validation Contract passes; `ruff check` passes on the new files.
- [ ] AC 10 — `wiki/sdd-tooling/sdd/necessity-ladder.md` has a `## Command` section (`parrot sdd techwiki check`).
- [ ] AC 11 — No public symbol, file or dependency beyond §3 Interface Skeletons, §6 Edit Sites and §7 External Dependencies (the §3 Necessity Ladder holds).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from pydantic import BaseModel, Field          # as used in packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py:69
from parrot.sdd.cli import VERBS               # verified: packages/ai-parrot/src/parrot/sdd/cli.py:247
from parrot.sdd.scripts import check_spec_ladder   # after M1 — same form as packages/ai-parrot/tests/sdd/test_techwiki_check.py:7
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py  — the shape to follow, not to import
class Finding(BaseModel):                                   # line 83
    level: str  # "error" | "warning"
    code: str
    tasks: list[str] = Field(default_factory=list)
    message: str
class GraphReport(BaseModel):                               # line 92
    @property
    def errors(self) -> list[Finding]: ...
def format_report(report: GraphReport) -> str: ...          # line 695
def main(argv: list[str] | None = None) -> int: ...         # line 710 — argparse, `--root`, `--json`, print with `# noqa: T201`

# packages/ai-parrot/src/parrot/sdd/cli.py
_HELPER_PACKAGE = "parrot.sdd.scripts"                      # line 22
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {   # line 247 — noun → verb → (helper module, argv prefix, help)
    "spec": { ...,
        "consequences": ("check_spec_consequences", (), "Decision-audit gate for a spec (FEAT-784)."),   # line 314
    },
main = importlib.import_module(f"{_HELPER_PACKAGE}.{module}").main   # line 371 — helpers load lazily and expose main(argv) -> int

# packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py
SLUG = "demo-feature"                                       # line 59
def _seed_feature(clone: Path) -> None: ...                 # line 132 — writes sdd/specs/demo-feature.spec.md (no ladder table)
@dataclass class Scenario: placeholders, prepare, expect_exit=(0,), …   # line 367
SCENARIOS: dict[str, Scenario] = {                          # line 404 — keyed by helper module name
    "check_spec_consequences": Scenario(prepare=_seed_feature, expect_exit=(0, 1, 2, 3), placeholders={...}),   # line 417
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `check_spec_ladder.main` | `parrot sdd` dispatcher | `VERBS["spec"]["ladder"]` | `packages/ai-parrot/src/parrot/sdd/cli.py:314`, `:371` |
| `/sdd-spec` §5a text | the new verb | fenced `bash` command | `.claude/commands/sdd-spec.md` §5a (after FEAT-908) |
| `SCENARIOS["check_spec_ladder"]` | release smoke test | dict entry | `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:404` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.sdd.scripts.check_spec_ladder`~~, ~~`parrot sdd spec ladder`~~ — created by this feature (`ls` → no such file; `parrot sdd spec --help` has no `ladder`)
- ~~A reusable Markdown-table parser in `parrot.sdd` or `parrot.flows.dev_loop`~~ — the only table reader is `check_task_graph.parse_declared_files`, specific to a task's file list; write the small row splitter inside M1
- ~~`scripts/sdd/check_spec_ladder.py`~~ — the files under `scripts/sdd/` are compatibility shims for helpers that moved; a new helper gets none
- ~~`### 5a. Lean Review` in `.claude/commands/sdd-spec.md` today~~ — it arrives with FEAT-908; do not start M3 before that merge
- ~~`wiki/sdd-tooling/sdd/necessity-ladder.md` today~~ — created by FEAT-908
- ~~`tests/sdd_scripts/test_necessity_ladder_contract.py` today~~ — created by FEAT-908
- ~~An `--advisory` flag on the new command~~ — deferred (§1)
- ~~`packages/ai-parrot/tests/sdd/test_check_spec_ladder.py`~~ — created by M4

### Edit Sites (Blueprint Anchors)

Verified against: `3fb0f4c6e7`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/check_spec_ladder.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `"consequences": ("check_spec_consequences", (), "Decision-audit gate for a spec (FEAT-784)."),` | `cli.py:314` | 1 |
| `.claude/commands/sdd-spec.md` | MODIFY | `### 5a. Lean Review (checks the Necessity Ladder — never asks)` | (unverified — exists after FEAT-908) | — |
| `.agent/workflows/sdd-spec.md` | MODIFY | `### 5a. Lean Review (checks the Necessity Ladder — never asks)` | (unverified — exists after FEAT-908) | — |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | the Lean Review bullet in step `10. Write the spec:` | (unverified — exists after FEAT-908) | — |
| `packages/ai-parrot/tests/sdd/test_check_spec_ladder.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | `"check_task_graph": Scenario(` | `test_wheel_only_foreign_repo.py:422` | 1 |
| `wiki/sdd-tooling/sdd/necessity-ladder.md` | MODIFY | end of file (new `## Command` section) | (unverified — exists after FEAT-908) | — |
| `packages/ai-parrot/src/parrot/sdd/_assets/**` + `manifest.json` | MODIFY | regenerated by `python scripts/sdd/check_asset_sync.py --write` — never by hand | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow `check_task_graph.py` for structure: Pydantic models, pure `check_*` function returning a
  report, `format_report`, `main(argv) -> int`, `print` only in `main` with `# noqa: T201`.
- The helper must import nothing heavy: standard library and `pydantic` only, so
  `test_sdd_cli_import_light.py` keeps passing and the command stays fast.
- The helper ships to other repositories: nothing in it may assume ai-parrot's layout. Paths come
  from the spec and `--root`; manifests come from `git ls-files`.
- Command twins: edit `.claude/commands/sdd-spec.md` and `.agent/workflows/sdd-spec.md` identically,
  then regenerate `_assets/` with `check_asset_sync.py --write` and verify with `--check`.

### Known Risks / Gotchas

- **Depends on FEAT-908 being merged.** Three edit sites do not exist before it. Start this
  feature's worktree only after FEAT-908 is on `dev`.
- **Table cells contain `|`.** A cell may hold an escaped pipe (`\|`, as this spec's M1 row does)
  or a pipe inside backticks. Split rows on unescaped pipes outside backtick spans, and test it.
- **Citations in free text.** A `path:NN` is taken only from inside backticks, and only when the
  part before the colon contains a `/` or a `.` — otherwise `:108`-style continuations (`…/pyproject.toml:108`, `:116`)
  would be misread. A bare `` `:116` `` continuation refers to the previous path in the same cell.
- **Release smoke.** `test_wheel_only_foreign_repo.py` collects every `parrot sdd <noun> <verb>`
  in installed markdown and fails the release when a helper has no scenario. It runs only in the
  release workflow, so dev CI will not catch a missing entry — AC 7 does.
- **False failures block approval.** An over-strict check stops `/sdd-spec` from marking a spec
  approved. That is why L9 and the unreadable-manifests case are warnings, and why the symbol
  check is deferred.
- **`import parrot` side effects.** `parrot` changes the working directory on import in some
  setups; resolve `spec_path` and `--root` to absolute paths in `main` before reading anything.

### External Dependencies

None. `pydantic` is already a dependency of the core package.

---

## Consequences

<!-- decision-audit: input_digest=sha256:c2f0e78a4a911449e738c1036fbd547fb3d60be34123573ae37c722092bd080a evaluation_digest=sha256:76865dfa84b4d1144910a204c35ff5fc3ae33b446b0500d2c51ae0b1ea869537 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-spec-ladder-check.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: cli, necessity-ladder, sdd-flow, spec-lint
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
      "cli",
      "necessity-ladder",
      "sdd-flow",
      "spec-lint"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-spec-ladder-check.spec.md"
    }
  ],
  "evaluation_digest": "sha256:76865dfa84b4d1144910a204c35ff5fc3ae33b446b0500d2c51ae0b1ea869537",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:c2f0e78a4a911449e738c1036fbd547fb3d60be34123573ae37c722092bd080a",
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

- [x] Should the mechanical Lean Review checks become a command? — *Resolved in FEAT-908 §8 Q1 by
  Jesus Lara (2026-11-17)*: yes, as this separate spec.
- [x] Does exceeding "Est. LOC" fail anything? — *Resolved in FEAT-908 §8 Q3*: no; this command
  does not look at implementations.
- [ ] Should `new-code-without-test` become an error once specs have used the table for a while?
  It is a warning here because "with logic" cannot be checked mechanically. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Status: skipped (no accepted exploration document — the spec follows from FEAT-908 §8 Q1).
> Expert consultation (§3c) was skipped for the same reason.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree; each task in its own sub-worktree.
- **Module dependency graph**: M2 → M1 (the verb names M1's module). M3 → M2 (the command text
  names a verb that must exist). M4 → M1, M2, M3 (it imports M1, asserts M2's entry and M3's
  text). M5 → M3 (assets are copied from the final command text). M1 has no dependency.
- **Shared files**: none between modules.
- **Exclusive resources**: `python scripts/sdd/check_asset_sync.py --write` rewrites
  `_assets/manifest.json` — the M5 task is `parallel: false`.
- **Cross-feature dependencies**: FEAT-908 (`ponytail-like-stairway`) must be merged into `dev`
  first.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/sdd-tooling/sdd/necessity-ladder.md` — update: add the `## Command` section (usage,
    finding codes, exit codes, sample output).
- **API modules**:
  - `parrot.sdd.scripts.check_spec_ladder`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-17 | Jesus Lara (with Claude) | Initial draft |
