---
type: feature
base_branch: dev
feature_id: FEAT-901
projects: [ai-parrot]
tags: [sdd-tooling, ledger-fix]
discovered_from: issue:2693ab44132d
docs:
  policy: none
  pages: []
  api_modules: []
---

# Feature Specification: `parrot sdd task close` closes `/sdd-brief` tasks in place

**Feature ID**: FEAT-901
**Date**: 2026-11-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:2693ab44132d` (minor feature gap, discovered from `task:HOTFIX-sandbox-extra-write-paths-1`):
`parrot sdd task close <ID> <slug> [verification]` only knows the feature layout. `close_task.main`
(`close_task.py:147`) globs `sdd/tasks/active/<ID>-*.md` and `sdd/tasks/completed/<ID>-*.md` and reads the index
at `sdd/tasks/index/<slug>.json`.

A `/sdd-brief` task lives at `sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-<N>-*.md`, with its index at
`sdd/briefs/<slug>.index.json`. For such a task the command prints
`✗ <ID>: no file in active/ and no twin in completed/.` and exits 2. `scripts/sdd/close_task.sh` execs the same
module and fails the same way.

Observed on 2026-11-16 in the brief `sandbox-extra-write-paths` (PR #2143): the task was closed by hand-editing
the task header and the per-brief index. No `task.closed` ledger event was written.

`/sdd-done` step 2b states that briefs close in place (no `active/` → `completed/` move), and `sdd-worker`
documents a `jq` recipe for it. No command performs that close.

### Goals
- `parrot sdd task close <ID> <slug> [verification]` closes a brief task in place when `<slug>` names a brief:
  - the task file's `**Status**` header becomes `done`;
  - its entry in `sdd/briefs/<slug>.index.json` gets `status: "done"`, `completed_at` and `verification`;
  - the index's top-level `completed_at` is stamped once every task is `done`;
  - the index and the task file are staged;
  - a `task.closed` ledger event is emitted, as for a feature task.
- The task file is not moved, and `sdd/tasks/completed/` is not created in brief mode.
- A second run on a closed brief task exits 0 and keeps the recorded `completed_at` and `verification`.
- The feature path keeps its behaviour, output and exit codes.

### Non-Goals (explicitly out of scope)
- `parrot sdd task finalize` and `parrot sdd task heal`. `heal` only reaps `active/` orphans, which a brief
  never has. `finalize` for briefs is a separate gap if it is wanted.
- Rewriting the manual `jq` recipe in `sdd-worker` / `/sdd-brief` / `/sdd-done` (and their Codex and installer
  twins) to call the command. The recipe stays valid.
- Filling in the Completion Note. That stays a hand step, as for feature tasks.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:ec47672c8fbb723fc6aee9cab7b540058a1a50e83bd48295e8b3aa83f2012ce9 evaluation_digest=sha256:dd4fc8305815957dc85978831a4b79142383e5a035e56303832916e05f955704 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One change in `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`:

1. A new constant `BRIEFS_DIR = "sdd/briefs"`.
2. In `main`, after `index` is computed and before `completed_dir.mkdir(...)`: when
   `sdd/tasks/index/<slug>.json` is not a file and `sdd/briefs/<slug>.index.json` is, return
   `_close_brief_task(...)`. A feature index wins a tie, as in `sdd-worker`'s feature resolution.
3. A new private function `_close_brief_task(repo_root, index_rel, task_id, feature_slug, verification, now)
   -> int`:
   - read the brief index; invalid JSON or no task list → `jq: error: …` on stderr, return 5;
   - find the entry whose `id` equals `task_id`; none → `✗ <ID>: not in <index_rel>.`, return 2;
   - take the entry's `file`; when it is missing, not a string, resolves outside `repo_root`, or is not a file →
     `✗ <ID>: task file not found: <file>`, return 2;
   - `sync_status_header(task_file)`; print `✓ <ID>: header **Status** → done` when it changed;
   - `update_index(index, task_id, verification, <file as recorded>, now)`;
   - `git add <index_rel> <file>`; a failing `git add` returns its exit code with its stderr;
   - print `✅ <ID> closed in place (verification=<v>).`, then `_emit_task_closed(...)`; return 0.

`update_index` already keeps `completed_at` and `verification` write-once, so the idempotent path needs no new
code. The entry's `file` value is written back unchanged.

### Component Diagram
```
parrot sdd task close <ID> <slug> [verification]
   └─ close_task.main
         ├─ sdd/tasks/index/<slug>.json exists      → feature path (unchanged: move, index, post-condition)
         ├─ sdd/briefs/<slug>.index.json exists     → _close_brief_task   ← new (in place, no move)
         └─ neither                                 → feature path (unchanged: exit 2 / "already in completed/")
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `close_task.main` | modifies | brief dispatch before `completed_dir.mkdir`; module docstring |
| `close_task._close_brief_task` | new private function | before `main` |
| `close_task.sync_status_header` | reused, unchanged | `close_task.py:51` |
| `close_task.update_index` | reused, unchanged | `close_task.py:65` |
| `close_task._emit_task_closed` | reused, unchanged | `close_task.py:97` |
| `scripts/sdd/close_task.sh` | consumer, unchanged | execs the module |
| `finalize_task._close_task_isolated` | consumer, unchanged | feature tasks only |

### Data Models
None.

### New Public Interfaces
None. The CLI arguments are unchanged.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: in-place close for brief tasks | yes | dispatch rule, function steps, messages and exit codes are fixed in §2; tests are listed in §4 | — |

### Module 1: in-place close for brief tasks
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py`,
  `packages/ai-parrot/tests/sdd/test_scripts_shell_port.py`
- **Responsibility**: `close_task` closes a brief task without moving it.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  BRIEFS_DIR = "sdd/briefs"

  def _close_brief_task(
      repo_root: Path, index_rel: str, task_id: str, feature_slug: str, verification: str, now: str
  ) -> int: ...

  # main — after `index = repo_root / index_rel`
  brief_index_rel = f"{BRIEFS_DIR}/{feature_slug}.index.json"
  if not index.is_file() and (repo_root / brief_index_rel).is_file():
      return _close_brief_task(repo_root, brief_index_rel, task_id, feature_slug, verification, now)
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_close_brief_task_in_place[_module]` / `[_wrapper]` | M1 | a brief fixture with one `in-progress` task → exit 0, `closed in place` on stdout, the task file is still at its path with `**Status**: done`, the entry has `status: done` / `verification: verified` / unchanged `file`, top-level `completed_at` is set, both files are staged, and `sdd/tasks/completed/` does not exist |
| `test_close_brief_task_is_idempotent` | M1 | a second run exits 0 and leaves the entry's `completed_at` and `verification` as the first run wrote them |
| `test_close_brief_task_unknown_id_exits_2` | M1 | an id absent from the brief index → exit 2, index unchanged |
| `test_close_brief_task_missing_file_exits_2` | M1 | the entry's `file` does not exist, or points outside the repository → exit 2, index unchanged |
| `test_close_brief_invalid_index_exits_5` | M1 | `{"tasks": null}` in the brief index → exit 5 |
| `test_feature_index_wins_over_brief_index` | M1 | both `sdd/tasks/index/demo.json` and `sdd/briefs/demo.index.json` exist → `TASK-9001` closes through the feature path and the brief index is unchanged |
| `test_close_moves_marks_done_and_stages`, `test_close_exit_codes`, `test_close_invalid_index_exits_5`, `test_close_removes_orphan_active_copy` | M1 | existing, unchanged: the feature path holds |

### Integration Tests
None.

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_scripts_shell_port.py
markers: none

### Test Data / Fixtures

A new `brief_repo` fixture next to `repo` in `test_scripts_shell_port.py`: a git repository with
`sdd/briefs/demo.index.json` (`"type": "brief"`, one task `HOTFIX-demo-1`, `status: "in-progress"`,
`completed_at: null`, `file: "sdd/briefs/demo/tasks/HOTFIX-demo-1-fix.md"`) and that task file with a
`**Status**: in-progress` header, committed. It has no `sdd/tasks/` tree.

---

## 5. Acceptance Criteria

- [ ] `python -m parrot.sdd.scripts.close_task HOTFIX-demo-1 demo verified` in a brief repository exits 0, leaves
      the task file in place with `**Status**: done`, marks the index entry `done` with `completed_at` and
      `verification`, stamps the top-level `completed_at`, and stages both files.
- [ ] A second run exits 0 and does not change `completed_at` or `verification`.
- [ ] An unknown id, a missing task file and a task file outside the repository exit 2. An invalid brief index
      exits 5.
- [ ] When both a feature index and a brief index exist for the slug, the feature path runs.
- [ ] The existing feature-path tests pass unchanged.
- [ ] The new tests fail on `origin/dev` without the fix and pass with it.
- [ ] `ruff check` passes on the changed files. `black` (line length 120) leaves the changed lines unchanged.

---

## 6. Codebase Contract

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/scripts/close_task.py — already imported at the top of the file
import json        # line 13
import subprocess  # line 17
import sys         # line 18
from collections.abc import Sequence  # line 20
from pathlib import Path              # line 22
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/scripts/close_task.py
ACTIVE_DIR = "sdd/tasks/active"        # line 24
COMPLETED_DIR = "sdd/tasks/completed"  # line 25
INDEX_DIR = "sdd/tasks/index"          # line 26
def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]  # line 30
def _out(line: str) -> None  # line 35
def _err(line: str) -> None  # line 39
def sync_status_header(task_file: Path) -> bool  # line 51 — rewrites the first pending|in-progress header
def update_index(index: Path, task_id: str, verification: str, completed_file: str, now: str) -> None  # line 65
    # raises ValueError on invalid JSON / no task list; completed_at and verification are write-once;
    # an id absent from the index is a silent no-op
def _emit_task_closed(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None  # line 97
def main(argv: Sequence[str] | None = None) -> int  # line 147
    # :163 repo_root; :164 now; :167-168 index_rel / index; :169 completed_dir.mkdir(...)

# packages/ai-parrot/tests/sdd/test_scripts_shell_port.py
def _git(repo: Path, *args: str) -> str  # line 18
def repo(tmp_path: Path) -> Path  # fixture, line 23
def _module(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]  # line 45
def _wrapper(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]  # line 50
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_close_brief_task` | `update_index` | direct call | `close_task.py:65` |
| `_close_brief_task` | `sync_status_header` | direct call | `close_task.py:51` |
| `_close_brief_task` | `_emit_task_closed` | direct call | `close_task.py:97` |
| `main` | `_close_brief_task` | dispatch on the brief index | `close_task.py:168` |

### Does NOT Exist (Anti-Hallucination)
- ~~`close_task.BRIEFS_DIR`, `close_task._close_brief_task`~~ — created by this feature.
- ~~a `--brief` flag or any new CLI argument~~ — none is added; detection is by index file.
- ~~`sdd/briefs/<slug>/tasks/completed/`~~ — briefs have no completed directory.
- ~~`brief_repo` fixture and the six `test_close_brief_*` / `test_feature_index_wins_over_brief_index`
  tests~~ — created by this feature.

### Edit Sites (Blueprint Anchors)

Verified against: `b3dd3ba3b7`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` | MODIFY | `Exit codes: 0 closed (idempotent) · 1 usage · 2 nothing to close · 3 post-condition failed ·` (add a brief paragraph above it) | `close_task.py:8` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` | ADD AFTER | `INDEX_DIR = "sdd/tasks/index"` | `close_task.py:26` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` | ADD BEFORE | `def main(argv: Sequence[str] \| None = None) -> int:` | `close_task.py:147` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` | ADD AFTER | `    index = repo_root / index_rel` | `close_task.py:168` | 1 |
| `packages/ai-parrot/tests/sdd/test_scripts_shell_port.py` | ADD BEFORE | `def test_ports_do_not_shell_out_to_jq_or_bash() -> None:` | `test_scripts_shell_port.py:128` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Messages go through `_out` / `_err`; no `print`, no logger (the module is a CLI port).
- No `jq` and no `bash` in the module (`test_ports_do_not_shell_out_to_jq_or_bash`).
- `black` line length 120, Google-style docstrings, strict type hints.

### Known Risks / Gotchas
- In a worktree the shared venv imports the main checkout. The tests set `PYTHONPATH` to the worktree's
  `packages/ai-parrot/src` themselves (`_env`), so run pytest from the worktree root.
- `update_index` does nothing for an unknown id, so `_close_brief_task` must look the entry up first to return 2.
- Check the recorded `file` with `Path.resolve()` and `is_relative_to(repo_root)` before touching it.
- `git add` of the task file must use the recorded relative path, with `repo_root` as cwd.

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:ec47672c8fbb723fc6aee9cab7b540058a1a50e83bd48295e8b3aa83f2012ce9 evaluation_digest=sha256:dd4fc8305815957dc85978831a4b79142383e5a035e56303832916e05f955704 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/9b942352-4436-40f5-8274-e127a17fb5c7/scratchpad/dev-clone/sdd/specs/scripts-close-task-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: ledger-fix, sdd-tooling
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
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "ledger-fix",
      "sdd-tooling"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/9b942352-4436-40f5-8274-e127a17fb5c7/scratchpad/dev-clone/sdd/specs/scripts-close-task-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:dd4fc8305815957dc85978831a4b79142383e5a035e56303832916e05f955704",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:ec47672c8fbb723fc6aee9cab7b540058a1a50e83bd48295e8b3aa83f2012ce9",
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

- [x] Q1. Detect a brief by a flag or by the index file? — *Resolved*: by the index file. The command line stays
  identical for features and briefs, and `sdd-worker` already resolves briefs from `sdd/briefs/*.index.json`.
- [x] Q2. Which index wins when both exist for one slug? — *Resolved*: the feature index, as in `sdd-worker`.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `none` — one CLI helper gains a branch, described by its module docstring. No wiki page documents
  `close_task`'s layout handling.
- **Pages**: none.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-901-scripts-close-task-fixes` off `origin/dev`.

- Module graph: one module, no edges.
- Shared files: none.
- Exclusive resources: none.
- Cross-feature: none known.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-16 | Jesus Lara | Created by /sdd-fix from `issue:2693ab44132d` (fixgroup:7d78fb71ea0f) |
