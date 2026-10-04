---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [dev-loop, dispatcher, agy, google-coding, sandbox, ledger-fix]
---

# Feature Specification: google_coding dispatcher — sandbox-readable JSON schema

**Feature ID**: FEAT-606
**Date**: 2026-09-25
**Author**: Jesus Lara (with Claude, via `/sdd-fix`)
**Status**: approved
**Source**: ledger `issue:e7bdce192812` (fix group `fixgroup:1a7f930d81a4`, severity major)

---

## 1. Motivation & Business Requirements

### Problem Statement

`GoogleCodingDispatcher._materialize_json_schema()` writes the output-model JSON
schema with `tempfile.mkstemp()`, i.e. into the host's `/tmp`, and passes that
path to `agy --json-schema <path>`. When the profile enables `--sandbox`, agy can
only read its workspace (the dispatch `cwd`, a worktree under
`WORKTREE_BASE_PATH`), so it cannot open the schema file and exits in ~0.2s
before the model runs. Every dispatch through a sandboxed `google_coding` seat
fails (observed replaying TASK-3549 through a new `google_coding` strong seat).

### Goals
- The schema file passed to `--json-schema` lives inside the dispatch `cwd`, so a
  sandboxed agy can read it.
- The file never appears as an untracked change in the worktree (`git status`
  stays clean) and can never be committed by the coder, in any repository —
  without depending on that repo's `.gitignore`.
- The file (and its directory) is removed on every exit path, as today.

### Non-Goals
- Changing the codex / claude / gemini dispatchers (their sandboxes read `/tmp`).
- Changing agy CLI flags or the stream-json parsing.

---

## 2. Architectural Design

### Overview

`_materialize_json_schema(output_model, cwd)` creates a unique per-dispatch
directory with `tempfile.mkdtemp(prefix=".dev_loop_agy_", dir=cwd)` (module
constant `_SCHEMA_DIR_PREFIX`), writes a `.gitignore` whose sole line is `*` into
it — git ignores the directory's entire content, including that `.gitignore` —
and writes the schema there. `_cleanup_json_schema(path)` removes the whole
directory in `dispatch()`'s `finally`. Because each dispatch owns its directory,
concurrent dispatches in the same `cwd` never share or race on removing it.
Cleanup failures are swallowed, as today.

### Integration Points
| Existing component | Change |
|---|---|
| `GoogleCodingDispatcher.dispatch()` | pass `cwd` to `_materialize_json_schema`; cleanup via new `_cleanup_json_schema(path)` |
| `GoogleCodingDispatcher._materialize_json_schema()` | writes under `cwd` instead of host temp dir |

### Data Models / New Public Interfaces
None (private helpers only).

---

## 3. Module Breakdown

### Module 1: sandbox-readable schema materialization
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py`
- **Responsibility**: materialize the schema inside `cwd` in a self-ignoring dir;
  clean file + empty dir in `dispatch()`'s `finally`.
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py`

---

## 4. Test Specification

### Unit Tests
| Test | Asserts |
|---|---|
| `test_schema_file_is_inside_cwd` | the `--json-schema` path in the built command is under `cwd` and existed with valid JSON at process-creation time |
| `test_schema_dir_is_git_ignored` | in a `git init` repo used as `cwd`, `git status --porcelain` is empty while the schema file exists |
| `test_schema_cleaned_up_after_dispatch` | after success and after non-zero exit, neither the schema file nor `.dev_loop_agy/` remains |

---

## 5. Acceptance Criteria
- [ ] `--json-schema` points at a file under the dispatch `cwd`.
- [ ] That file is invisible to `git status` in the worktree.
- [ ] Schema file and its directory are removed after success and after failure.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -v` passes.
- [ ] `ruff check` clean on the modified file.

---

## 6. Codebase Contract

### Verified Imports
- `import tempfile`, `import os`, `import json` — already imported in `google_coding.py`.

### Existing Class Signatures
- `GoogleCodingDispatcher._materialize_json_schema(self, output_model: Type[BaseModel]) -> str` (`google_coding.py:361`)
- `GoogleCodingDispatcher._build_command(self, *, profile, schema_path: str, prompt: str) -> List[str]`

### Does NOT Exist (Anti-Hallucination)
- ~~`GoogleCodingDispatchProfile.schema_dir`~~ — not a real field; do not add one.
- ~~agy `--json-schema-inline`~~ — no inline-schema flag is used or assumed.

### Edit Sites (Blueprint Anchors)
Verified against: `30a40663a`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `schema_path = self._materialize_json_schema(output_model)` | `google_coding.py:174` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `os.unlink(schema_path)` | `google_coding.py:290` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `def _materialize_json_schema(self, output_model: Type[BaseModel]) -> str:` | `google_coding.py:361` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | — (append tests) | — | — |

---

## 7. Implementation Notes & Constraints

### Known Risks / Gotchas
- A coder running `git add -A` must not pick the file up — hence the
  self-ignoring directory rather than relying on the repo `.gitignore` (the
  dispatcher is used against other repositories too).
- Concurrent dispatches may share `cwd`; directory removal must tolerate a
  sibling schema file still being present (only `rmdir` when empty).

---

## 8. Open Questions
None.

---

## 9. Design Research Cross-Check
Status: skipped (ledger-driven single-module bugfix via `/sdd-fix`; no brainstorm/proposal to review)

---

## Revision History
| Date | Change |
|---|---|
| 2026-09-25 | Initial spec from ledger issue `issue:e7bdce192812` |
| 2026-09-25 | Shared `.dev_loop_agy/` dir → per-dispatch `mkdtemp` dir (removes an rmdir/mkstemp race between concurrent dispatches) |
