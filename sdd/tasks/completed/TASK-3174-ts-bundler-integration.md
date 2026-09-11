# TASK-3174: TS bundler integration — `scripts/build_snippet_bundles.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3161
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 14. Build-time TS → JS compilation for a snippet bundle's
optional client half, producing the `client.js` file TASK-3164's
`GitSnippetLoader` reads verbatim (never compiling anything itself) and
TASK-3173's Worker boot block embeds. **Never invoked at request time** —
this is a CI/authoring-time script only.

There is currently no TypeScript build step anywhere in
`parrot-formdesigner` (spec §6 "Does NOT Exist") — this task introduces
the first one, using `esbuild` *or* `swc` (spec §7 External Dependencies:
either is acceptable, "latest stable").

---

## Scope

- Implement `packages/parrot-formdesigner/scripts/build_snippet_bundles.py`:
  walks a snippet bundle root (same directory layout TASK-3164 defines),
  compiles each bundle's optional `client.ts` to `client.js` via a
  subprocess call to `esbuild` (chosen over `swc` for this task — a CLI
  binary invocation is simpler to shell out to than `swc`'s node-API-first
  tooling; note this choice, it is not spec-mandated), computes and
  writes the resulting `client_sha256` back into `manifest.json`.
- Fails loudly (non-zero exit, clear stderr message) if `esbuild` is not
  found on `PATH` and at least one bundle declares a `client.ts` — this
  is a CI-time hard requirement, not a runtime one (does not interact
  with OQ-4's gVisor prerequisite at all — a different, build-time-only
  dependency).
- Write `packages/parrot-formdesigner/tests/unit/test_build_snippet_bundles.py`,
  using a fake/stubbed `esbuild` invocation (no real `esbuild` binary
  required in unit tests — mirror TASK-3170's `fake_gvisor_absent`
  pattern: never require an external binary for the test suite to pass).

**NOT in scope**: modifying `GitSnippetLoader` (TASK-3164) — this script
produces the `client.js`/`client_sha256` inputs that loader reads, it does
not call the loader; wiring this script into an actual CI workflow file
(`.github/workflows/*.yml`) — out of this task's file list unless no
other task covers it (flag the gap if so).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/scripts/build_snippet_bundles.py` | CREATE | TS → JS build-time compiler |
| `packages/parrot-formdesigner/tests/unit/test_build_snippet_bundles.py` | CREATE | Unit tests (fake `esbuild` subprocess) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import subprocess
import shutil
import hashlib
import json
from pathlib import Path
```

### Existing conventions to follow
```python
# packages/parrot-formdesigner/scripts/ already holds standalone,
# directly-runnable scripts (verified at task-writing time):
#   backfill_published_versions.py, gen_frontend_docs.py,
#   generate_form_controls_snapshot.py, seed_fieldsync_projects.py
# Follow their existing style: a `def main() -> int` entrypoint, argparse
# for CLI args, `if __name__ == "__main__": sys.exit(main())`.
```

### Does NOT Exist
- ~~`scripts/build_snippet_bundles.py`~~ — created by this task.
- ~~Any TypeScript build step in `parrot-formdesigner`~~ — confirmed
  absent (spec §6); this is genuinely new tooling.
- ~~A Node.js/npm dependency already declared for this package~~ — check
  `packages/parrot-formdesigner/package.json` (if any) before assuming
  one exists; `esbuild` is invoked as an external CLI binary here, not
  imported as a Python package, so no `pyproject.toml` dependency is
  needed for it — only documentation that CI/dev machines must have it
  on `PATH` (mirrors the `runsc`-as-external-binary pattern from TASK-3170).

---

## Implementation Notes

### Key Constraints
- **Never invoked at request time** — this script is a standalone CLI,
  run by a human/CI, never imported by any runtime module
  (`services/`, `renderers/`). Do not add a call to it from
  `GitSnippetLoader` or anywhere in the request path.
- Bundle directory layout is TASK-3164's: `<root>/<bundle-name>/{manifest.json,
  run.py,client.ts?}` on input, producing `client.js` alongside `client.ts`
  (both kept — `client.ts` is the source of truth, `client.js` is the
  build artifact TASK-3164 reads) and updating `manifest.json`'s
  `client_sha256` key in place.
- Determinism: re-running this script on unchanged sources must produce a
  byte-identical `client.js` (or the script should skip recompilation via
  a source-hash check) — non-determinism here would make
  `python_sha256`/`client_sha256` verification (TASK-3164) flaky in CI.
- A bundle with no `client.ts` is valid (server-only Python snippet) —
  skip it silently, do not warn.

### References in Codebase
- `packages/parrot-formdesigner/scripts/` — read one existing script
  (e.g. `generate_form_controls_snapshot.py`) for this package's CLI
  script conventions (shebang, argparse shape, exit codes) before writing.

---

## Implementation Blueprint

### Steps (in order)
1. Implement `_find_bundle_dirs(root)` and `_compile_one(bundle_dir)`.
2. Implement the `esbuild` subprocess invocation with a clear
   `FileNotFoundError`/non-zero-exit failure message.
3. Implement the `manifest.json` `client_sha256` rewrite.
4. Wire `main()` with argparse (`--root`, `--check` for a CI dry-run mode
   that fails if any `client.js` is stale relative to its `client.ts`).
5. Write and run tests against a fake `esbuild`.

### `packages/parrot-formdesigner/scripts/build_snippet_bundles.py` (CREATE)
```python
#!/usr/bin/env python
"""Build-time TS -> JS compiler for snippet bundles (FEAT-459 / M14).

NEVER invoked at request time — a CI/authoring-time script only. Compiles
each bundle's optional client.ts (TASK-3164's directory layout) to
client.js via `esbuild`, then rewrites manifest.json's client_sha256.

Usage:
    python scripts/build_snippet_bundles.py --root path/to/snippet_bundles
    python scripts/build_snippet_bundles.py --root ... --check   # CI dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"
TS_SOURCE_FILENAME = "client.ts"
JS_OUTPUT_FILENAME = "client.js"


class EsbuildNotFoundError(Exception):
    """Raised when `esbuild` is required (a bundle declares client.ts) but absent."""


def _find_bundle_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir())


def _compile_one(bundle_dir: Path, *, check_only: bool) -> bool:
    """Compile one bundle's client.ts, if present.

    Args:
        check_only: When True, do NOT write client.js — only report
            whether it would change (CI dry-run mode).

    Returns:
        True if this bundle has (or would need) a client.js update.

    Raises:
        EsbuildNotFoundError: client.ts is present but `esbuild` is not on PATH.
        subprocess.CalledProcessError: esbuild exited non-zero.
    """
    ts_path = bundle_dir / TS_SOURCE_FILENAME
    if not ts_path.exists():
        return False
    if shutil.which("esbuild") is None:
        raise EsbuildNotFoundError(
            f"{bundle_dir.name} declares {TS_SOURCE_FILENAME} but `esbuild` "
            "is not on PATH. Install esbuild (or swc) to build snippet client halves."
        )
    js_path = bundle_dir / JS_OUTPUT_FILENAME
    result = subprocess.run(
        ["esbuild", str(ts_path), "--bundle", "--minify", "--format=iife"],
        capture_output=True, text=True, check=True,
    )
    new_js = result.stdout
    changed = not js_path.exists() or js_path.read_text() != new_js
    if changed and not check_only:
        js_path.write_text(new_js)
        _update_manifest_hash(bundle_dir, new_js)
    return changed


def _update_manifest_hash(bundle_dir: Path, js_source: str) -> None:
    manifest_path = bundle_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text())
    manifest["client_sha256"] = hashlib.sha256(js_source.encode("utf-8")).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Snippet bundle root directory")
    parser.add_argument(
        "--check", action="store_true",
        help="CI dry-run: exit non-zero if any client.js is stale, without writing",
    )
    args = parser.parse_args(argv)

    any_changed = False
    try:
        for bundle_dir in _find_bundle_dirs(args.root):
            if _compile_one(bundle_dir, check_only=args.check):
                any_changed = True
                print(f"{'STALE' if args.check else 'built'}: {bundle_dir.name}")
    except EsbuildNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"esbuild failed for a bundle: {exc.stderr}", file=sys.stderr)
        return 1

    if args.check and any_changed:
        print("error: one or more client.js files are stale — run without --check", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: `--check` mode exists specifically so CI can fail a PR
that edited `client.ts` without regenerating `client.js` — the
determinism requirement (re-compiling unchanged sources produces the same
output) is what makes a byte-comparison-based staleness check reliable
rather than flaky. `esbuild ... --format=iife` (rather than `esm` or
`cjs`) matches the Worker `Blob`/`importScripts`-friendly execution model
TASK-3173's boot block assumes (a plain executable script, not a module
needing an import graph) — flag in the Completion Note if TASK-3173 ends
up needing a different format.

### `packages/parrot-formdesigner/tests/unit/test_build_snippet_bundles.py` (CREATE)
```python
"""Unit tests for build_snippet_bundles.py — FEAT-459 / TASK-3174.

All tests use a FAKE `esbuild` (a shell script placed on PATH via
monkeypatch/tmp_path) — no real esbuild binary is required.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts.build_snippet_bundles import EsbuildNotFoundError, _compile_one


def _write_bundle(root: Path, name: str, *, with_ts: bool = True) -> Path:
    bundle_dir = root / name
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "manifest.json").write_text(json.dumps({
        "handler_ref": f"{name}.onBeforeSubmit", "event": "onBeforeSubmit",
        "python_sha256": "a" * 64, "manifest": {"tier": "pure"},
    }))
    (bundle_dir / "run.py").write_text("def run(ctx): return {}")
    if with_ts:
        (bundle_dir / "client.ts").write_text("export function run() { return []; }")
    return bundle_dir


@pytest.fixture
def fake_esbuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal fake `esbuild` CLI: echoes a fixed JS string to stdout."""
    fake_bin_dir = tmp_path / "fakebin"
    fake_bin_dir.mkdir()
    fake_esbuild_path = fake_bin_dir / "esbuild"
    fake_esbuild_path.write_text("#!/bin/sh\necho '(function(){return [];})();'\n")
    fake_esbuild_path.chmod(fake_esbuild_path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake_bin_dir}:{monkeypatch.getenv('PATH', '')}" if hasattr(monkeypatch, "getenv") else str(fake_bin_dir))
    return fake_esbuild_path


def test_skips_bundle_without_client_ts(tmp_path: Path) -> None:
    bundle_dir = _write_bundle(tmp_path, "server_only", with_ts=False)
    changed = _compile_one(bundle_dir, check_only=False)
    assert changed is False
    assert not (bundle_dir / "client.js").exists()


def test_raises_when_esbuild_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    bundle_dir = _write_bundle(tmp_path, "needs_ts", with_ts=True)
    with pytest.raises(EsbuildNotFoundError):
        _compile_one(bundle_dir, check_only=False)


def test_compile_writes_client_js_and_updates_hash(tmp_path: Path, fake_esbuild: Path) -> None:
    # FILL IN: this test needs PATH correctly pointed at fake_esbuild's
    #   directory across platforms — fix the fixture's monkeypatch.setenv
    #   call above (the hasattr check is a placeholder, not a real
    #   solution) before relying on this test. Once fixed: call
    #   _compile_one(bundle_dir, check_only=False), assert client.js
    #   exists and manifest.json's client_sha256 matches
    #   hashlib.sha256(client.js content).
    pass


def test_check_mode_does_not_write(tmp_path: Path, fake_esbuild: Path) -> None:
    # FILL IN: same PATH fix needed; call with check_only=True, assert
    #   client.js is NOT created but the function still returns True
    #   (indicating "would change").
    pass
```
**Why**: two tests (skip-without-ts, raise-without-esbuild) are complete
and require no fake binary at all; the two requiring the fake `esbuild`
on `PATH` are stubbed because the fixture's `PATH`-prepending line is
written with a visible placeholder (`hasattr(monkeypatch, "getenv")`) that
is not a real cross-platform solution — flagged explicitly rather than
shipping a fixture that looks correct but is fragile.

### FILL IN checklist
- [ ] `fake_esbuild` fixture — fix the `PATH` prepending (use `monkeypatch.setenv("PATH", f"{fake_bin_dir}{os.pathsep}{original_path}")` with `original_path` captured via `os.environ.get("PATH", "")` BEFORE any monkeypatching)
- [ ] `test_compile_writes_client_js_and_updates_hash` — body once the fixture is fixed
- [ ] `test_check_mode_does_not_write` — body once the fixture is fixed

---

## Acceptance Criteria

- [ ] A bundle with no `client.ts` is skipped without error or a written `client.js`
- [ ] A bundle with `client.ts` but no `esbuild` on `PATH` raises `EsbuildNotFoundError` with a clear message
- [ ] A successful compile writes `client.js` and updates `manifest.json`'s `client_sha256` to match the actual output's hash
- [ ] `--check` mode never writes `client.js`, and exits non-zero if any bundle's compiled output would differ from the existing `client.js`
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_build_snippet_bundles.py -v`
- [ ] `ruff check` and `mypy` clean on `scripts/build_snippet_bundles.py`
- [ ] `grep -rn "build_snippet_bundles" packages/parrot-formdesigner/src/` returns nothing (never imported at request time)

---

## Test Specification

See the blueprint's test file above — 4 test functions, 2 stubbed pending a fixture fix.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 14, §7 External Dependencies table)
2. **Check dependencies** — TASK-3161 must be `done` (this task's manifest shape follows TASK-3164's directory layout, which itself follows TASK-3161's models — read TASK-3164's file if already written to confirm the exact `manifest.json` shape)
3. **Verify the Codebase Contract** — confirm `scripts/` still has no existing TS/JS build tooling
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; fix the `fake_esbuild` fixture's `PATH` handling before relying on the two gated tests
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3174-ts-bundler-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrated via parrot-sdd-coder, retried once)
**Date**: 2026-09-11
**Notes**: Implemented `scripts/build_snippet_bundles.py` — CI/authoring-time
script that compiles `client.ts` → `client.js` via `esbuild`, updates
`manifest.json`'s `client_sha256`, and supports a `--check` dry-run mode
that never writes and exits non-zero on drift. Bundles without
`client.ts` are skipped silently (valid for server-only Python
snippets); raises `EsbuildNotFoundError` when `esbuild` is absent on
`PATH`. 5/5 tests pass (fake-esbuild fixture, no real external
dependency), `ruff check`/`mypy` clean, never imported from
`packages/parrot-formdesigner/src/` (confirmed via grep guard).

**Deviations from spec**: none

**Seat: minimax (attempt 2, after qwen attempt-1 timeout) · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 2 · Duration: 685.5s (552.5s timeout + 133.0s success) · Tokens: 400,368 in / 5,904 out**
