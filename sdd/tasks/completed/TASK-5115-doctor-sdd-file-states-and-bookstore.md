# TASK-5115: doctor reports missing/foreign SDD files and flags the bookstore cross-repo entry

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12 — ledger fixes)
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5114
**Assigned-to**: unassigned
**Discovered-from**: `issue:dcd763dd04f9`, `issue:a7deda11b8c3`

---

## Context

Two `parrot self doctor` gaps filed against FEAT-633 (`/sdd-fix`, 2026-11-03):

- `issue:dcd763dd04f9`: `_check_sdd_assets` builds `sdd: files current` from `sdd_status()` but only reads the
  `outdated` and `edited` groups. A deleted installed file (`missing`) or a hand-copied one (`foreign`) passes as
  "all installed SDD files current". Separately, `not any(hosts.values())` is always false, because `sdd_status()`
  returns a states dict for every supported host, so "SDD flow not installed" is never reported.
- `issue:a7deda11b8c3`: `_check_host_configs` flags user-global Google entries baked for another repo only when the
  key is `wikitoolkit` or `parrot-*`. The `bookstore` entry the same installers write
  (`.venv/bin/python3 -m parrot.knowledge.bookstore.cli mcp`, `cwd=<repo>`) is never reported.

---

## Scope

- A host counts as installed when any of its `current`/`outdated`/`edited`/`foreign` groups is non-empty
  (`plan_install` writes every selected manifest entry, so a `missing` target on an installed host is always a gap).
  No installed host → informational "SDD flow not installed".
- `sdd: files current` also fails on `missing` targets of installed hosts (fix: `parrot sdd install`).
- New informational check `sdd: foreign files` when any installed host has `foreign` targets, with the
  delete-and-reinstall hint (C25 rule for hand-copied agents).
- Cross-repo collision: an entry is parrot-managed when its key is `wikitoolkit`, `bookstore` or `parrot-*`, OR its
  command basename is a parrot entry point (`parrot`, `wikitoolkit`, `bookstore`), OR its args run a `parrot.*`
  module (`-m parrot.…`).

**NOT in scope**: changing `sdd_status()`'s shape; the hooks-path or version checks (TASK-5116/5117).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `_check_sdd_assets` states, `_is_parrot_entry` + collision filter |
| `packages/ai-parrot/tests/self_/test_doctor_sdd.py` | MODIFY | missing / foreign / not-installed tests |
| `packages/ai-parrot/tests/self_/test_doctor.py` | MODIFY | bookstore collision test |

---

## Codebase Contract (Anti-Hallucination)

Verified on `feat-FEAT-633-parrot-installer` at `3d66594c6b` (2026-11-03).

```python
# packages/ai-parrot/src/parrot/self_/doctor.py
def _check_sdd_assets(root: Path, status: dict[str, Any] | None) -> list[DoctorCheck]   # line 260
def _other_root(entry: Any, root: Path) -> str | None                                  # line 389
def _check_host_configs(root: Path) -> list[DoctorCheck]                               # line 412 (collision at 453)
RUNTIME_ENTRYPOINTS: tuple[str, ...] = ("parrot", "wikitoolkit", "bookstore")          # line 29
# packages/ai-parrot/src/parrot/sdd/installer.py
FileState = Literal["missing", "current", "outdated", "edited", "foreign"]             # line 72
def sdd_status(root: Path) -> dict[str, Any]                                           # line 1290
```

### Does NOT Exist
- ~~a receipt-based "installed hosts" list in `sdd_status()`~~: derive it from the state groups.

---

## Acceptance Criteria

- [ ] An installed host with a `missing` target fails `sdd: files current` with fix `parrot sdd install`.
- [ ] A `foreign` target yields an informational `sdd: foreign files` check (never fails doctor).
- [ ] With every host all-`missing`, `sdd: files current` is informational "SDD flow not installed".
- [ ] A user-global `bookstore` entry with a foreign `cwd` is reported as a cross-repo collision.
- [ ] Existing `test_doctor.py` / `test_doctor_sdd.py` tests pass; `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor.py -q`

## Agent Instructions

Work in `feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`; stage only the files
above; close with `parrot sdd task close TASK-5115 parrot-installer verified`.

---

## Completion Note
**Completed by**: Claude Opus 5.5 (/sdd-fix, sequential)
**Date**: 2026-11-03
**Notes**: Installed host = any non-missing state group. `missing` on an installed host fails `sdd: files current` (fix `parrot sdd install`); `foreign` is an informational `sdd: foreign files` check. The old `not any(hosts.values())` branch was dead (sdd_status lists every supported host), so "SDD flow not installed" is reachable again. Collision filter is `_is_parrot_entry` (known keys, parrot entry-point command basename, `-m parrot.*` args). 5 new tests; test_doctor.py + test_doctor_sdd.py 35 passed; ruff clean.
