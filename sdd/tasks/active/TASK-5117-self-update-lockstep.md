# TASK-5117: `parrot self update` keeps ai-parrot / ai-parrot-tools in lockstep; doctor reports skew

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12 — ledger fixes; C20 lockstep)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5116
**Assigned-to**: unassigned
**Discovered-from**: `issue:66700eac9b2f`

---

## Context

`parrot/self_/components.py::update_runtime` (no `--version`) upgrades `ai-parrot` first, then installs
`ai-parrot-tools==<resolved ai-parrot version>`. The two are released separately, and `ai-parrot-tools` only
requires `ai-parrot>=1.2.6`. When tools has not yet published that version, the second install fails after the core
has already moved, which leaves mismatched versions. `parrot self doctor` never compares the two.

---

## Scope

- Unpinned `update_runtime()`:
  1. one atomic `uv pip install --upgrade ai-parrot ai-parrot-tools` (nothing installs if resolution fails);
  2. read both installed versions; when they differ, re-pin both to the **lower** one
     (`ai-parrot==V ai-parrot-tools==V`, again one atomic call);
  3. if that alignment fails, keep the upgraded pair and append a `warning:` line to the log naming both versions
     and the `parrot self update --version <V>` fix. Never raise after step 1 succeeded.
- `--version` path unchanged.
- New runtime-scope doctor check `runtime lockstep`: both versions in the managed venv; fails when they differ
  (fix `parrot self update --version <lower>`). Informational when the venv or ai-parrot-tools is absent
  (`parrot_tools.wiki` already reports a missing tools dist).
- Version ordering uses `packaging.version.Version` when importable, else a numeric-tuple fallback.

**NOT in scope**: querying PyPI for available versions; changing `install-parrot.{sh,ps1}`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/components.py` | MODIFY | atomic upgrade + alignment |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `_check_runtime_lockstep` in runtime scope |
| `packages/ai-parrot/tests/self_/test_components.py` | MODIFY | lockstep / skew / alignment-failure tests |
| `packages/ai-parrot/tests/self_/test_doctor.py` | MODIFY | lockstep check tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `feat-FEAT-633-parrot-installer` at `3d66594c6b` (2026-11-03).

```python
# packages/ai-parrot/src/parrot/self_/components.py
CORE_DIST = "ai-parrot"; TOOLS_DIST = "ai-parrot-tools"; BASE_DISTS = (CORE_DIST, TOOLS_DIST)   # lines 23-26
def _run(argv: list[str], log: list[str]) -> None                  # line 195 — subprocess.run(check=True)
def update_runtime(version: str | None = None) -> list[str]        # line 238
def _installed_version(python: Path, dist: str) -> str             # line 258 — check=True (raises)
# packages/ai-parrot/src/parrot/self_/doctor.py
def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]   # line 487
# existing test to update: test_update_runtime_unpinned_keeps_lockstep (test_components.py:88)
```

### Does NOT Exist
- ~~`packaging` as a declared ai-parrot dependency~~: import it lazily with a fallback.

---

## Acceptance Criteria

- [ ] Unpinned update issues one `--upgrade ai-parrot ai-parrot-tools` call; equal versions → no second call.
- [ ] Differing versions → second call pins both to the lower version.
- [ ] Failing alignment → no exception, `warning:` line in the log.
- [ ] Doctor `runtime lockstep` fails on skew with the `--version` fix; passes on equal versions.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/self_/test_components.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`
- `pytest packages/ai-parrot/tests/self_/test_self_cli.py -q`

## Agent Instructions

Work in `feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`; stage only the files
above; close with `parrot sdd task close TASK-5117 parrot-installer verified`.

---

## Completion Note
*(Agent fills this in when done)*
