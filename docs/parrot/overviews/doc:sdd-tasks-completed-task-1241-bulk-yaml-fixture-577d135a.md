---
type: Wiki Overview
title: 'TASK-1241: Bulk YAML fixture tagger — `scripts/sdd/tag_yaml_fixtures.py`'
id: doc:sdd-tasks-completed-task-1241-bulk-yaml-fixture-tagger-script-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 3 of the spec. Once TASK-1239 lands and `require_tenant=True`
---

# TASK-1241: Bulk YAML fixture tagger — `scripts/sdd/tag_yaml_fixtures.py`

**Feature**: FEAT-183 — FormRegistry Multi-Tenancy
**Spec**: `sdd/specs/formregistry-multi-tenancy.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1239
**Assigned-to**: unassigned

---

## Context

Implements Module 3 of the spec. Once TASK-1239 lands and `require_tenant=True`
becomes the default, every YAML form fixture under
`packages/parrot-formdesigner/tests/` and `examples/forms/` (plus any other
discovered location) must carry a top-level `tenant:` line, or `load_from_directory`
will skip it with a warning at test time.

This task creates an idempotent bulk script that walks the relevant
directories and inserts `tenant: navigator` (matching `default_tenant`) into
files that lack a top-level `tenant:` field. The script does NOT apply
itself — TASK-1242 runs it and commits the resulting diff.

---

## Scope

- Create `scripts/sdd/tag_yaml_fixtures.py`.
- The script walks a configurable list of root directories (default:
  `packages/parrot-formdesigner/tests/`, `examples/forms/`, `tests/forms/`)
  and finds every `*.yaml` / `*.yml` file.
- For each file:
  - Parse the YAML to a Python object (use `pyyaml` — already in deps).
  - If the parsed root is a dict and it contains `form_id` (heuristic: it's
    a form fixture) AND it does NOT contain a `tenant:` key, INSERT a
    `tenant: navigator` line.
  - If the file already has `tenant:`, skip (idempotent).
  - If the file does not look like a form fixture (no `form_id` at root,
    or the root is not a mapping), skip with a debug log.
- Preserve the file's existing formatting as much as practical: insert the
  `tenant: navigator` line immediately after the line containing `form_id:`
  to keep diffs minimal. A full YAML round-trip would reformat the file
  unnecessarily.
- Provide a `--dry-run` flag that reports what would be changed without
  writing.
- Provide a `--roots` flag (repeatable) to override the default root list,
  for use in CI or one-off invocations.
- Print a summary to stdout: files scanned, files tagged, files skipped
  (already-tagged), files skipped (not-a-form-fixture).
- Exit code 0 on success regardless of whether any file was modified.
- Add a unit test that creates a temp directory with two YAML files (one
  tagged, one not), runs the script's entry point in-process, and asserts:
  - The untagged file now has `tenant: navigator`.
  - The already-tagged file is byte-identical.
  - A second run produces no diff (idempotency).

**NOT in scope**:
- Running the script against the real repo (TASK-1242).
- Adding the script to CI (out of feature scope; document in script
  docstring as a follow-up).
- Updating documentation for ops/runbook (mention in script docstring; no
  separate docs).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/tag_yaml_fixtures.py` | CREATE | The bulk tagger script. |
| `scripts/sdd/__init__.py` | MODIFY-OR-VERIFY | Make sure the package init exists; leave alone if it does. |
| `tests/sdd/test_tag_yaml_fixtures.py` | CREATE | Unit test for the tagger. |

Verify `scripts/sdd/__init__.py` exists (other sdd scripts live there per
the existing `scripts/sdd/sdd_meta.py` reference in CLAUDE.md and the spec).
If it doesn't, create an empty `__init__.py`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Standard library imports the script will use:
import argparse
import logging
import sys
from pathlib import Path

# YAML — confirmed via project deps; PyYAML is a transitive dep of
# parrot-formdesigner. If the agent finds it missing, add it via uv.
import yaml
```

### Existing Signatures to Use

```python
# scripts/sdd/sdd_meta.py is referenced by CLAUDE.md as a sibling script —
# verify it exists. The agent should mimic its module-level style for
# consistency (argparse, pathlib, exit codes).
# Do NOT inherit from it; this is a fresh script.
```

### Does NOT Exist

- ~~A pre-existing "form fixture walker" module~~ — the script is new.
- ~~A YAML formatter helper~~ — use plain string insertion to keep diffs
  minimal; do NOT call `yaml.safe_dump()` on the entire file.
- ~~A CI hook for this script~~ — not added by this task.

---

## Implementation Notes

### Pattern to Follow

```python
"""scripts/sdd/tag_yaml_fixtures.py
Idempotently inserts ``tenant: navigator`` into YAML form fixtures that
declare ``form_id:`` but lack a top-level ``tenant:`` field.

Usage:
    python -m scripts.sdd.tag_yaml_fixtures [--dry-run] [--roots PATH ...]

The default roots are the in-repo YAML fixture locations relevant to
parrot-formdesigner (see DEFAULT_ROOTS below).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

DEFAULT_ROOTS = [
    "packages/parrot-formdesigner/tests",
    "examples/forms",
    "tests/forms",
]
DEFAULT_TENANT = "navigator"
LOG = logging.getLogger("tag_yaml_fixtures")


def is_form_fixture(parsed: object) -> bool:
    return isinstance(parsed, dict) and "form_id" in parsed


def already_tagged(parsed: dict) -> bool:
    return "tenant" in parsed


def tag_file(path: Path, dry_run: bool) -> str:
    """Returns one of: 'tagged', 'already', 'not-a-fixture', 'parse-error'."""
    try:
        parsed = yaml.safe_load(path.read_text())
    except Exception as exc:
        LOG.debug("parse error %s: %s", path, exc)
        return "parse-error"
    if not is_form_fixture(parsed):
        return "not-a-fixture"
    if already_tagged(parsed):
        return "already"
    if dry_run:
        return "tagged"
    # Insert immediately after the first form_id: line to minimise diff.
    lines = path.read_text().splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.lstrip().startswith("form_id:"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}tenant: {DEFAULT_TENANT}\n")
            inserted = True
    if not inserted:
        # Fallback: append at end (very unlikely path).
        out.append(f"tenant: {DEFAULT_TENANT}\n")
    path.write_text("".join(out))
    return "tagged"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    counts = {"tagged": 0, "already": 0, "not-a-fixture": 0, "parse-error": 0}
    for root in args.roots:
        root_path = Path(root)
        if not root_path.exists():
            LOG.info("skip missing root %s", root_path)
            continue
        for yaml_file in list(root_path.rglob("*.yaml")) + list(root_path.rglob("*.yml")):
            result = tag_file(yaml_file, dry_run=args.dry_run)
            counts[result] += 1
            if result == "tagged":
                LOG.info("%s %s", "would-tag" if args.dry_run else "tagged", yaml_file)
    LOG.info("summary: %s", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Key Constraints

- Idempotent: a second invocation must produce no diff.
- Diff-minimal: do NOT round-trip the YAML through `yaml.safe_dump()`. Use
  textual insertion after the `form_id:` line.
- Defensive: tolerate files that are not form fixtures (no `form_id` at
  root) and YAML parse errors. Log at debug; do NOT fail the script.
- Re-entrant: the script reads + writes one file at a time; no global
  state.
- The default tenant value `"navigator"` matches the spec's resolved Open
  Question and `PostgresFormStorage.DEFAULT_SCHEMA` (`storage.py:51`).

### References in Codebase

- `scripts/sdd/sdd_meta.py` — sibling SDD script; style reference.

---

## Acceptance Criteria

- [ ] `scripts/sdd/tag_yaml_fixtures.py` exists and is executable as
      `python -m scripts.sdd.tag_yaml_fixtures`.
- [ ] `--dry-run` flag works and reports without writing.
- [ ] `--roots` flag overrides the defaults.
- [ ] Files with `form_id` AND no `tenant:` gain a `tenant: navigator` line
      directly after the `form_id:` line, preserving indentation.
- [ ] Files already tagged are byte-identical after a run.
- [ ] Files without `form_id` at root are skipped.
- [ ] YAML parse errors are logged at debug, do NOT crash the script.
- [ ] Unit test `tests/sdd/test_tag_yaml_fixtures.py` passes; verifies
      idempotency.
- [ ] No lint errors: `ruff check scripts/sdd/tag_yaml_fixtures.py`.

---

## Test Specification

```python
# tests/sdd/test_tag_yaml_fixtures.py
from pathlib import Path

from scripts.sdd.tag_yaml_fixtures import main, tag_file


def test_tags_untagged_form_fixture(tmp_path: Path):
    f = tmp_path / "form.yaml"
    f.write_text("form_id: my-form\nversion: '1.0'\nsections: []\n")
    result = tag_file(f, dry_run=False)
    assert result == "tagged"
    content = f.read_text()
    assert "tenant: navigator" in content
    # Inserted right after form_id:
    lines = content.splitlines()
    assert lines.index("tenant: navigator") == lines.index("form_id: my-form") + 1


def test_skips_already_tagged(tmp_path: Path):
    f = tmp_path / "form.yaml"
    original = "form_id: my-form\ntenant: epson\nversion: '1.0'\nsections: []\n"
    f.write_text(original)
    result = tag_file(f, dry_run=False)
    assert result == "already"
    assert f.read_text() == original


def test_skips_non_form_files(tmp_path: Path):
    f = tmp_path / "not_a_form.yaml"
    f.write_text("some_other_key: value\n")
    result = tag_file(f, dry_run=False)
    assert result == "not-a-fixture"


def test_idempotent(tmp_path: Path):
    f = tmp_path / "form.yaml"
    f.write_text("form_id: my-form\nversion: '1.0'\nsections: []\n")
    tag_file(f, dry_run=False)
    first = f.read_text()
    tag_file(f, dry_run=False)
    second = f.read_text()
    assert first == second


def test_main_returns_zero(tmp_path: Path, monkeypatch):
    # Smoke test of the CLI entry point with --roots override.
    f = tmp_path / "form.yaml"
    f.write_text("form_id: m\nversion: '1.0'\nsections: []\n")
    rc = main(["--roots", str(tmp_path)])
    assert rc == 0
    assert "tenant: navigator" in f.read_text()
```

---

## Agent Instructions

1. **Read the spec** §3 Module 3 and §7 Patterns to Follow.
2. **Check dependencies**: TASK-1239 done.
3. **Verify** `scripts/sdd/__init__.py` exists; create empty if not.
4. **Implement** the script per Implementation Notes.
5. **Write the unit test**, run it, ensure idempotency.
6. **Run** `ruff check scripts/sdd/tag_yaml_fixtures.py` clean.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `done`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Created scripts/sdd/tag_yaml_fixtures.py with tag_file(), is_form_fixture(),
already_tagged(), and main() functions. Supports --dry-run and --roots flags.
Tests placed in tests/sdd_scripts/test_tag_yaml_fixtures.py (11 tests, all pass).
ruff clean. Idempotency verified.

**Deviations from spec**: Tests placed in tests/sdd_scripts/ (existing SDD script
test location) rather than tests/sdd/ (which doesn't exist in this project).
