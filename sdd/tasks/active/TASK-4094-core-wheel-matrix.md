# TASK-4094: Release: core wheel matrix (macOS arm64, linux aarch64) + clean-install smoke gate

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4068, TASK-4090
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 + §5 ("`release.yml` builds core wheels for linux x86_64 + aarch64, windows
AMD64 and macOS arm64 (cp311–cp313 minimum); the redundant quadruple ubuntu legs are gone").
Today `build-core` (`release.yml:13-82`) runs four ubuntu legs (python 3.11/3.12/3.13/3.14) that
each rebuild the SAME `cp3{11,12,13,14}-*` set with cibuildwheel, plus one windows leg; there is no
macOS or linux-aarch64 core wheel, so `--global` installs on Apple Silicon / ARM Linux fall back to
compiling the two in-repo Cython extensions (spike S1 risk, spec §7).

Codex S11 (spec §9, CONFIRMED): build success is not the gate — each platform's wheels must pass a
clean-environment smoke test (fresh venv, import parrot, the three console scripts `--help`, MCP
`initialize`) before `deploy` publishes. TASK-4068 delivers that harness:
`scripts/install/smoke_install.py` and the reusable `.github/workflows/install-matrix.yml`.

Spec §7 gotcha: `[tool.cibuildwheel] build = "cp3{11,12,13,14}-*"` vs
`requires-python = ">=3.11,<3.14"` — the package refuses to install on 3.14, so cp314 wheels must
not be built. Decision (this task): drop cp314 everywhere; relaxing the ceiling is out of scope.

This task is EXCLUSIVE on `release.yml` and serialized after TASK-4090 (which also edits
`packages/ai-parrot/pyproject.toml` — line numbers below may shift by its package-data edit; re-grep).

---

## Scope

- Rewrite `build-core`'s matrix as one leg per platform: linux x86_64, linux aarch64, windows
  AMD64, macOS arm64 — each building cp311–cp313 once (removes the 4 redundant ubuntu legs).
- Replace the two OS-specific cibuildwheel steps with one step driven by matrix values
  (`--platform`, `CIBW_ARCHS`), `CIBW_BUILD: "cp3{11,12,13}-*"`.
- Keep the sdist built exactly once (linux x86_64 leg).
- Make artifact names unique per leg (`core-dist-<platform>-<arch>`).
- Add a `smoke-core` job that calls `.github/workflows/install-matrix.yml` (TASK-4068) via
  `workflow_call` with the built core wheels, and add it to `deploy.needs`.
- `packages/ai-parrot/pyproject.toml` `[tool.cibuildwheel]`: `build = "cp3{11,12,13}-*"`; drop
  `*-manylinux_aarch64` from `skip`; linux archs native 64-bit; add a `[tool.cibuildwheel.macos]`
  table with `archs = ["arm64"]`.
- Create `packages/ai-parrot/tests/docs/test_release_matrix.py` (YAML + TOML assertions).

**NOT in scope**:
- Any change to the other build jobs (tools, loaders, …, `build-parrot-codec`, `build-clients`).
- Writing/changing `install-matrix.yml` or `smoke_install.py` (TASK-4068 owns them — if their
  `workflow_call` interface is missing, STOP and report; do not edit them here).
- Relaxing `requires-python` to allow 3.14; macOS x86_64 (Intel) wheels (runner retired — see
  `release.yml:422-428`); code signing.
- `[project.scripts]` (TASK-4072) and package-data (TASK-4090) in the same pyproject.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/release.yml` | MODIFY | core matrix (linux x86_64/aarch64, windows AMD64, macOS arm64; cp311–313), smoke gate job, `deploy.needs` |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `[tool.cibuildwheel]`: drop cp314, allow manylinux aarch64, macOS arm64 archs |
| `packages/ai-parrot/tests/docs/test_release_matrix.py` | CREATE | parse release.yml + pyproject and assert the matrix contract |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib               # stdlib (Python >=3.11; requires-python is ">=3.11,<3.14", pyproject.toml:18)
import yaml                  # PyYAML is a CORE dependency: "PyYAML>=6.0.2" (packages/ai-parrot/pyproject.toml:58)
from pathlib import Path     # stdlib
```

### Existing Signatures to Use
```yaml
# .github/workflows/release.yml
jobs:
  build-core:                                   # line 13
    runs-on: ${{ matrix.os }}                   # line 14
    strategy:                                   # line 15
      fail-fast: false                          # line 16
      matrix:                                   # line 17  (`matrix:` occurs 4x in the file)
        os: [ubuntu-latest]                     # line 18  (unique anchor)
        python-version: ["3.11", "3.12", "3.13", "3.14"]   # line 19
        include:                                # line 20
          - os: windows-latest                  # line 21
            python-version: "3.12"              # line 22
    defaults: { run: { working-directory: packages/ai-parrot } }   # lines 23-25
          python-version: ${{ matrix.python-version }}   # line 34 (setup-python)
      - name: Build wheels on Linux             # line 52 — CIBW_ARCHS x86_64 (55), CIBW_BEFORE_BUILD rustup (56),
                                                #           CIBW_ENVIRONMENT (57), CIBW_BUILD "cp3{11,12,13,14}-*" (59)
      - name: Build wheels on Windows           # line 63 — CIBW_ARCHS AMD64 (66), CIBW_BUILD (67)
      - name: Build sdist                       # line 71; if: matrix.python-version == '3.12' && runner.os == 'Linux' (72)
          name: core-dist-${{ matrix.os }}-py${{ matrix.python-version }}   # line 79 (upload-artifact@v7)
  build-parrot-codec:                           # line 408 — precedent: include-list matrix,
          - os: macos-latest                    # line 430, target aarch64-apple-darwin (431)
          # aarch64 linux there is a maturin cross-target on ubuntu-latest (419-421) — NOT applicable to cibuildwheel
  deploy:                                       # line 531
    needs: [build-core, build-tools, ..., build-parrot-codec, build-clients]   # line 532
    if: github.event_name == 'release'          # line 534
        uses: actions/download-artifact@v8      # line 541 — downloads ALL artifacts, `find` collects *.whl/*.tar.gz
```
```toml
# packages/ai-parrot/pyproject.toml
requires-python = ">=3.11,<3.14"                                       # line 18
"PyYAML>=6.0.2",                                                       # line 58
[tool.cibuildwheel]                                                    # line 1043
build = "cp3{11,12,13,14}-*"                                           # line 1044
skip = "pp* *-musllinux* *-manylinux_i686 *-manylinux_aarch64 *-win32" # line 1045
[tool.cibuildwheel.linux]                                              # line 1047
archs = ["x86_64"]                                                     # line 1048
[tool.cibuildwheel.windows]                                            # line 1050
archs = ["AMD64"]                                                      # line 1051
# [build-system] is setuptools + Cython==3.0.11 (lines 1-7); [tool.maturin] (1027-1031) is INERT
# for the core build (comment block 1005-1026) — the rustup CIBW_BEFORE_BUILD is legacy but harmless.
```
- Reusable workflow from TASK-4068: `.github/workflows/install-matrix.yml` with an
  `on: workflow_call` trigger (input names defined by TASK-4068 — read the file before wiring).

### Does NOT Exist
- ~~macOS or linux-aarch64 core wheels~~ — only `parrot-codec` builds them (spec §6).
- ~~`[tool.cibuildwheel.macos]`~~ — no macOS table today.
- ~~`.github/workflows/install-matrix.yml`, `scripts/install/smoke_install.py`~~ — created by
  TASK-4068 (dependency); do not create or edit them here.
- ~~`packages/ai-parrot/tests/docs/test_release_matrix.py`~~ — new here.
- ~~a smoke/verification job in `release.yml`~~ — none today; `deploy` trusts build success.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".github/workflows/release.yml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_release_matrix.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
```yaml
# release.yml build-parrot-codec (408-436): explicit include-list matrix, one entry per target,
# macos-latest for aarch64-apple-darwin.
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: macos-latest
            target: aarch64-apple-darwin
```

### Key Constraints
- linux aarch64: use the native GitHub-hosted ARM runner `ubuntu-24.04-arm` with
  `CIBW_ARCHS: aarch64` — *why*: cibuildwheel under QEMU emulation compiles the Cython C++
  extension and the rust toolchain for three interpreters at ~10x slowdown (hours). FILL IN: if the
  repository cannot use `ubuntu-24.04-arm` (private-repo/plan limits), fall back to
  `ubuntu-latest` + `docker/setup-qemu-action@v3` (platforms: arm64) — bounded by spec M8 "add
  QEMU/archs config".
- macOS: `macos-latest` is arm64; set `CIBW_ARCHS: arm64` and FILL IN
  `MACOSX_DEPLOYMENT_TARGET` (recommend `11.0`, the first arm64 macOS) — bounded by the oldest
  macOS the managed Python 3.12 supports.
- Keep `CIBW_BEFORE_BUILD` / `CIBW_ENVIRONMENT` rustup lines LINUX-ONLY (use
  `CIBW_BEFORE_BUILD_LINUX` / `CIBW_ENVIRONMENT_LINUX`) — *why*: they reference `/root/.cargo`,
  which exists only inside the manylinux container.
- Host Python for running cibuildwheel is fixed at `"3.12"` — *why*: cibuildwheel builds every
  `CIBW_BUILD` interpreter itself; the old per-leg python-version only multiplied identical work.
- `deploy` must `need` the smoke job, and the smoke job must `need` `build-core` — *why*: codex
  S11, an unsmoked wheel never reaches PyPI. Keep `deploy`'s `if: github.event_name == 'release'`.
- Reusable-workflow calls are a job with `uses:` + `with:` (no `runs-on`/`steps`); the called
  workflow sees this run's artifacts, so pass the artifact-name pattern (`core-dist-*`), not files.
- PyYAML parses the top-level `on:` key as boolean `True` — the test must not depend on `on`.

### References in Codebase
- `.github/workflows/release.yml:13-82` — `build-core`.
- `.github/workflows/release.yml:408-468` — macOS/aarch64 precedent (maturin, different tool).
- `.github/workflows/release.yml:531-564` — `deploy`.

---

## Implementation Blueprint

### Steps (in order)
1. Re-grep every anchor (TASK-4090 may have shifted pyproject lines) — *why*: anchors go stale.
2. Replace the `build-core` matrix with the 4-entry include list — *why*: one leg per platform.
3. Repoint setup-python to `"3.12"`, merge the two cibuildwheel steps into one, fix the sdist
   condition and artifact name — *why*: the old steps keyed on `matrix.python-version`.
4. Add `smoke-core` calling `install-matrix.yml` and add it to `deploy.needs` — *why*: codex S11.
5. Update `[tool.cibuildwheel]` in pyproject — *why*: cp314 vs `<3.14`; aarch64 skip removal.
6. Create the test — *why*: lock the matrix contract against regressions.

### `.github/workflows/release.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '        os: \[ubuntu-latest\]' .github/workflows/release.yml)
#   (`matrix:` occurs 4x — anchor on the os line, context: `      matrix:` / `        os: [ubuntu-latest]` /
#    `        python-version: ["3.11", "3.12", "3.13", "3.14"]`)
# REPLACE — lines 18-22 (`        os: [ubuntu-latest]` … `            python-version: "3.12"`)
#   (verified: .github/workflows/release.yml:18) with:
        include:
          - { os: ubuntu-latest,    platform: linux,   archs: x86_64, sdist: true }
          - { os: ubuntu-24.04-arm, platform: linux,   archs: aarch64, sdist: false }
          - { os: windows-latest,   platform: windows, archs: AMD64,  sdist: false }
          - { os: macos-latest,     platform: macos,   archs: arm64,  sdist: false }

# occurrences: 1 (verified: grep -c '          python-version: ${{ matrix.python-version }}' .github/workflows/release.yml)
# REPLACE — :34 with:
          python-version: "3.12"

# occurrences: 1 each (verified: grep -c '      - name: Build wheels on Linux' and '      - name: Build wheels on Windows')
# REPLACE — both steps (:52-69) with ONE step:
      - name: Build wheels (${{ matrix.platform }} ${{ matrix.archs }})
        env:
          CIBW_ARCHS: ${{ matrix.archs }}
          CIBW_BUILD: "cp3{11,12,13}-*"
          CIBW_BEFORE_BUILD_LINUX: "curl https://sh.rustup.rs -sSf | sh -s -- -y && source $HOME/.cargo/env"
          CIBW_ENVIRONMENT_LINUX: "PATH=/root/.cargo/bin:$PATH"
          RUST_SUBPACKAGE_PATH: src/parrot/yaml_rs
          # FILL IN: MACOSX_DEPLOYMENT_TARGET for the macos leg — bounded by Key Constraints
        run: cibuildwheel --platform ${{ matrix.platform }} --output-dir ${{ github.workspace }}/dist

# occurrences: 1 (verified: grep -c "        if: matrix.python-version == '3.12' && runner.os == 'Linux'" .github/workflows/release.yml)
# REPLACE — :72 with:
        if: matrix.sdist

# occurrences: 1 (verified: grep -c '          name: core-dist-${{ matrix.os }}-py${{ matrix.python-version }}' .github/workflows/release.yml)
# REPLACE — :79 with:
          name: core-dist-${{ matrix.platform }}-${{ matrix.archs }}

# AFTER — the build-core upload step (end of job, :82), before `  build-tools:` (:84) — insert:
  smoke-core:
    needs: [build-core]
    uses: ./.github/workflows/install-matrix.yml
    # FILL IN: `with:` inputs exactly as declared by TASK-4068's `on: workflow_call` (e.g. an
    #          artifact pattern `core-dist-*`); if install-matrix.yml has no workflow_call trigger,
    #          STOP and report — bounded by NOT-in-scope (TASK-4068 owns that file)

# occurrences: 1 (verified: grep -c '    needs: \[build-core, build-tools' .github/workflows/release.yml)
# REPLACE — :532: insert `smoke-core` right after `build-core` in the needs list:
    needs: [build-core, smoke-core, build-tools, build-loaders, build-embeddings, build-pipelines, build-visualizations, build-integrations, build-formdesigner, build-server, build-advisors, build-navrules, build-parrot-codec, build-clients]
```
**Why this shape**: four legs × three interpreters = every target wheel exactly once; the smoke
gate sits between build and deploy (codex S11). Do not touch `deploy`'s `if:` or publish step.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'build = "cp3{11,12,13,14}-\*"' packages/ai-parrot/pyproject.toml)
# REPLACE — `build = "cp3{11,12,13,14}-*"` (verified: packages/ai-parrot/pyproject.toml:1044) with:
# cp314 is NOT built while requires-python is "<3.14" (spec §7) — keep both in sync.
build = "cp3{11,12,13}-*"

# occurrences: 1 (verified: grep -c 'skip = "pp\* \*-musllinux\* \*-manylinux_i686 \*-manylinux_aarch64 \*-win32"' packages/ai-parrot/pyproject.toml)
# REPLACE — :1045 with:
skip = "pp* *-musllinux* *-manylinux_i686 *-win32"

# occurrences: 1 (verified: grep -c 'archs = \["x86_64"\]' packages/ai-parrot/pyproject.toml)
# REPLACE — :1048 (`[tool.cibuildwheel.linux]` table) with:
archs = ["auto64"]   # x86_64 on x86 runners, aarch64 on ARM runners; CI overrides via CIBW_ARCHS

# AFTER — `archs = ["AMD64"]` (end of `[tool.cibuildwheel.windows]`, :1051) — append:

[tool.cibuildwheel.macos]
archs = ["arm64"]
```
**Why**: the toml is the local/default config; CI's `CIBW_ARCHS` per leg wins. `auto64` keeps a
local `cibuildwheel` run on x86_64 from attempting an emulated aarch64 build.

### `packages/ai-parrot/tests/docs/test_release_matrix.py` (CREATE)
```python
"""Release-matrix contract for the core wheel (FEAT-633, TASK-4094)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
PYPROJECT = REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"


def _jobs() -> dict[str, Any]:
    """Return release.yml's `jobs` mapping (the `on:` key parses as True — never read it)."""
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]


def _core_legs() -> list[dict[str, Any]]:
    """Return build-core's matrix include entries."""
    return _jobs()["build-core"]["strategy"]["matrix"]["include"]


def _cibw() -> dict[str, Any]:
    """Return the [tool.cibuildwheel] table."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["cibuildwheel"]


def test_core_matrix_covers_all_platforms() -> None:
    """linux x86_64 + aarch64, windows AMD64 and macOS arm64 — one leg each."""
    pairs = {(leg["platform"], leg["archs"]) for leg in _core_legs()}
    assert pairs == {("linux", "x86_64"), ("linux", "aarch64"), ("windows", "AMD64"), ("macos", "arm64")}
    assert len(_core_legs()) == 4, "redundant build-core legs are back"


def test_no_cp314_while_requires_python_excludes_it() -> None:
    """Neither pyproject nor release.yml builds cp314 while requires-python is <3.14."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    if "<3.14" in project["requires-python"]:
        assert "14" not in _cibw()["build"]
        assert not re.search(r"CIBW_BUILD:.*14", RELEASE.read_text(encoding="utf-8"))


def test_aarch64_not_skipped_and_macos_declared() -> None:
    """manylinux aarch64 is no longer skipped; the macOS table targets arm64."""
    cibw = _cibw()
    assert "manylinux_aarch64" not in cibw["skip"]
    assert cibw["macos"]["archs"] == ["arm64"]


def test_deploy_needs_smoke_gate() -> None:
    """deploy waits for the clean-install smoke job, which waits for build-core (codex S11)."""
    jobs = _jobs()
    assert "smoke-core" in jobs["deploy"]["needs"]
    assert jobs["smoke-core"]["uses"].endswith("install-matrix.yml")
    assert "build-core" in jobs["smoke-core"]["needs"]
```
**Why**: parses the real files (no string greps for structure) so a re-indent cannot fool it; the
cp314 check is conditional on the ceiling so a future relaxation only needs pyproject edits.

### FILL IN checklist
- [ ] `release.yml::build-core` — `ubuntu-24.04-arm` availability; QEMU fallback otherwise.
- [ ] `release.yml::build-core` — `MACOSX_DEPLOYMENT_TARGET` value for the macOS leg.
- [ ] `release.yml::smoke-core` — `with:` inputs per TASK-4068's `workflow_call` declaration.
- [ ] Verify via `workflow_dispatch` on the feature branch that all four legs + smoke pass (release
      verification needs a tag — spec Worktree Strategy: PR-CI / dispatch only).

---

## Acceptance Criteria

- [ ] `build-core` has exactly four legs: linux x86_64, linux aarch64, windows AMD64, macOS arm64,
      each building cp311–cp313 (spec §5 wheel-matrix AC); the quadruple ubuntu legs are gone.
- [ ] No cp314 wheel is built anywhere while `requires-python` is `<3.14` (spec §7).
- [ ] `*-manylinux_aarch64` is no longer skipped; `[tool.cibuildwheel.macos] archs = ["arm64"]`.
- [ ] The sdist is built once (linux x86_64 leg); artifact names are unique per leg.
- [ ] `smoke-core` runs TASK-4068's install matrix against the built wheels and `deploy` needs it (codex S11).
- [ ] `test_release_matrix.py` passes; `yaml.safe_load` of release.yml succeeds.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_release_matrix.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_release_matrix.py — see blueprint (whole file)
def test_core_matrix_covers_all_platforms(): ...
def test_no_cp314_while_requires_python_excludes_it(): ...
def test_aarch64_not_skipped_and_macos_declared(): ...
def test_deploy_needs_smoke_gate(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4094 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
