---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd-tooling, techwiki, static-analysis, bugfix]
docs:
  policy: none
---

# Feature Specification: Techwiki static-only Griffe loading — FEAT-801 review follow-up

**Feature ID**: FEAT-900
**Date**: 2026-11-15
**Author**: Jesus Lara
**Status**: approved
**Discovered-from**: `issue:5af0e518b2e8` (opened from `spec:FEAT-801`)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-801 (`sdd/specs/github-wiki-technical-reference.spec.md`) requires the API reference generator to
load every configured package **statically** — "no imports" (§2), "without importing any of them" (AC-2) —
and gives native code a skip policy: "Cython modules (`.pyx`): griffe reads `.pyi` stubs when present,
otherwise the module is skipped and listed in the report; not an error" (§7).

`load_packages` (`packages/ai-parrot/src/parrot/sdd/techwiki/api.py:114`) calls
`griffe.load(module_root, search_paths=[source_root])`. The installed griffe (2.4.1) defaults
`allow_inspection` to `True`, so a compiled extension under a configured root
(`parrot/utils/types.cpython-312-x86_64-linux-gnu.so`, `parrot/utils/parsers/toml.*.so`) is loaded by
**runtime inspection**: griffe imports it. Three defects follow:

1. The generator executes code from the tree it documents, which the spec forbids.
2. The reference depends on the build state of the checkout: a tree with built `.so` files gets a page for
   `parrot.utils.types`, a clean tree does not, so the "byte-identical output" rule does not hold.
3. A native module with no Python source or stub is never listed in `skipped_modules`. With inspection
   disabled griffe only logs it at debug level (`LoadingError: Cannot load compiled module without
   inspection`), so the documented skip policy is not implemented either way.

### Goals

- G1: `load_packages` never lets griffe inspect (import) a module: `allow_inspection=False` is passed
  explicitly on every `griffe.load` call.
- G2: every public native module under a configured root that has no `.py` source and no `.pyi` stub is
  listed in `skipped_modules`, with a fixed reason and `"kind": "native"`.
- G3: that listing does not depend on the build state: a Cython source (`.pyx`) and a built extension
  (`.so`, `.pyd`) of the same module produce the same single entry.
- G4: a native entry is "not an error" (FEAT-801 §7): `--strict` exit 4 stays reserved for parse and load
  failures, in both `parrot sdd techwiki api` and `parrot sdd techwiki bundle`.
- G5: regression tests cover G1–G4.

### Non-Goals (explicitly out of scope)

- Generating a page for a native module (from a `.pyx`, by inspection, or otherwise). A module that needs a
  page gets a `.pyi` stub; writing stubs for `parrot.utils.types` / `parrot.utils.parsers.toml` is not part
  of this fix.
- `issue:b9829d5f3a2b` (missing configured roots silently pass strict coverage) — a separate open issue on
  the same file; `_root_exists` and the skipped-root behaviour are not touched.
- Sourceless bytecode (`.pyc` / `.pyo`) modules.
- Any change to the report schema beyond the optional `kind` key on a skipped entry, to
  `.github/workflows/techwiki.yml`, to the templates or to the golden files.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:d74ac3751eb76653b4dfdf3d9800854c51053502203bc4a771d9a2c52e8ea2ba evaluation_digest=sha256:2c97799ea2c5951e9f0deb1e5a246af8165a0285de825b80f8e0b892c3a69ed4 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two small changes in `parrot/sdd/techwiki/api.py`, one shared helper used by the two CLIs.

**Static-only loading.** `load_packages` passes `allow_inspection=False`. griffe then visits `.py` / `.pyi`
files only; for a compiled submodule it raises `LoadingError` internally, logs it at debug level and moves
on (verified in `griffe.GriffeLoader._load_module_path` / `_load_submodule`, griffe 2.4.1). `force_inspection`
keeps its default (`False`).

**Native-module report.** A new `_native_modules(cfg, root)` scans the configured roots the same way
`_syntax_errors` does, on the file system, without griffe:

- It walks only *regular packages*: a directory is entered when it holds `__init__.py` or `__init__.pyi`
  (griffe ignores a directory without an init module below a regular package). `__pycache__` is never entered.
- A file is a native candidate when its suffix is `.so`, `.pyd` or `.pyx`. Its module stem is the file
  name up to the first dot (`types.cpython-312-x86_64-linux-gnu.so` → `types`, `_navrules.abi3.so` →
  `_navrules`), the same rule griffe applies.
- A candidate is dropped when: the stem is not a Python identifier; the stem is `__init__`; the stem or any
  package name below the source root starts with `_` (private modules never get a page — `_submodules`
  excludes them); or a sibling `<stem>.py`, `<stem>.pyi` or `<stem>/__init__.py` / `<stem>/__init__.pyi`
  exists (griffe documents that one statically).
- Each remaining module name yields exactly one entry, however many files match it:
  `{"module": "<dotted name>", "reason": NATIVE_SKIP_REASON, "kind": "native"}`.

`_generate` extends `skipped` with these entries right after the syntax-error entries; the final sort by
module name is unchanged.

**Strict mode.** A new public helper `strict_failures(skipped)` returns the entries whose `kind` is not
`"native"`. Both CLIs replace their truthiness check on the skipped list with `strict_failures(...)`.
Native entries are still serialised in the JSON report, the bundle manifest and the `Skipped <module>:
<reason>` stderr lines.

### Integration Points

| Component | Change |
|---|---|
| `parrot.sdd.techwiki.api.load_packages` | passes `allow_inspection=False` |
| `parrot.sdd.techwiki.api._generate` | adds native entries to `skipped` |
| `parrot.sdd.scripts.techwiki_api.main` | strict exit uses `strict_failures` |
| `parrot.sdd.scripts.techwiki_bundle.main` | strict exit uses `strict_failures` |
| `parrot.sdd.techwiki.bundle` | unchanged — it forwards the skipped list as is |

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: static-only loading and native report | yes | constants, signatures, scan rules and entry shape fixed below | — |
| M2: strict mode ignores native entries | yes | helper signature and both call sites fixed below | — |

### Module 1: Static-only loading and native report

File: `packages/ai-parrot/src/parrot/sdd/techwiki/api.py`.

```python
NATIVE_SKIP_KIND = "native"
NATIVE_SKIP_REASON = "native module without Python sources or stubs (static analysis only)"
_NATIVE_SUFFIXES = frozenset({".so", ".pyd", ".pyx"})


def _native_modules(cfg: TechwikiConfig, root: Path) -> list[dict[str, str]]:
    """Report public native modules that have neither a Python source nor a stub."""
```

- `load_packages`: `griffe_module.load(module_root, search_paths=[source_root], allow_inspection=False)`.
  Extend the docstring: inspection is disabled so no configured module is ever imported.
- `_native_modules` implements the scan rules of §2 and returns the entries sorted by module name. A
  configured root that is a single `.py` module (not a directory) has no native modules.
- `_generate`: `skipped.extend(_native_modules(cfg, root))` directly after
  `skipped.extend(_syntax_errors(cfg, root))`.

### Module 2: Strict mode ignores native entries

Files: `packages/ai-parrot/src/parrot/sdd/techwiki/api.py`,
`packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py`,
`packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py`.

```python
def strict_failures(skipped: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return the skipped entries that fail ``--strict``: every entry except native-module ones."""
```

- `techwiki_api.py`: `return 4 if args.strict and strict_failures(skipped) else 0`.
- `techwiki_bundle.py`: `return 4 if args.strict and strict_failures(report.skipped_modules) else 0`.
- Both `--strict` help strings become
  `"Exit 4 when a module was skipped by a parse or load failure (native modules are listed, not fatal)"`.
  The `main` docstring in `techwiki_bundle.py` that describes exit 4 is updated to match.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_load_packages_disables_inspection` | M1 | with `_import_griffe` monkeypatched to a recording fake, every `load` call receives `allow_inspection=False` and `search_paths=[<source root>]` |
| `test_generate_reports_native_modules` | M1 | a fixture package with `fast.cpython-311-x86_64-linux-gnu.so` + `fast.cpython-312-x86_64-linux-gnu.so`, `speed.pyx`, `stubbed.so` + `stubbed.pyi`, `_hidden.so`, and `scripts/tool.so` in a directory without `__init__.py`: `skipped` is exactly the `fast` and `speed` entries (kind `native`, reason `NATIVE_SKIP_REASON`); `pure` and `stubbed` have pages; no fixture module is in `sys.modules` |
| `test_native_report_is_build_state_independent` | M1 | a module with only `mod.pyx` and the same module with `mod.pyx` + `mod.cpython-312-x86_64-linux-gnu.so` yield equal `(pages, skipped)` |
| `test_strict_failures_excludes_native_entries` | M2 | `strict_failures` keeps a syntax-error entry and an entry without `kind`, drops a `kind: native` entry |
| `test_strict_ignores_native_modules` | M2 | `techwiki api --strict --json` on the native fixture exits 0, the report lists the native modules, stderr carries `Skipped <module>`; adding a syntax-error module makes the same command exit 4 |
| `test_bundle_strict_ignores_native_modules` | M2 | `techwiki bundle --strict` exits with the same code as without `--strict` when the only skipped modules are native, and the written report lists them |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_techwiki_api.py
- packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
markers: none

### Test Data / Fixtures

Fixtures are built in `tmp_path` by the tests. The "compiled" files are placeholder bytes: with inspection
disabled nothing ever opens them, which is exactly what the tests prove. No golden file changes.

---

## 5. Acceptance Criteria

- [ ] AC1: every test in the Validation Contract passes, including the six new tests above.
- [ ] AC2: `griffe.load` is called with `allow_inspection=False` at every call site in
  `parrot/sdd/techwiki/` (there is exactly one).
- [ ] AC3: a native module without source or stub is listed in `skipped_modules` with `"kind": "native"`;
  one with a `.pyi` stub is rendered and not listed; a private one is not listed.
- [ ] AC4: `--strict` exits 4 for a syntax-error module and 0 when the only skipped modules are native, in
  both `techwiki api` and `techwiki bundle`.
- [ ] AC5: the existing tests of both files pass unchanged (`test_generate_satellite_coverage` still sees an
  empty skipped list; the golden pages are byte-identical).
- [ ] AC6: `ruff check` is clean on every changed file.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.sdd.techwiki.api import GriffeUnavailable, RenderedPage, _unlink_pageless_refs, generate   # verified: tests/sdd/test_techwiki_api.py:14
from parrot.sdd.techwiki.config import TechwikiConfig, TechwikiPackage                                  # verified: tests/sdd/test_techwiki_api.py:15
from parrot.sdd.scripts.techwiki_api import main                                                        # verified: tests/sdd/test_techwiki_api.py:13
from parrot.sdd.scripts.techwiki_bundle import main                                                     # verified: tests/sdd/test_techwiki_bundle.py:12
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/sdd/techwiki/api.py
def _import_griffe() -> "griffe":                                                          # line 36
def _root_exists(source_root: Path, module_root: str) -> bool:                             # line 85
def load_packages(cfg: TechwikiConfig, root: Path) -> "list[griffe.Module]":               # line 91
def _syntax_errors(cfg: TechwikiConfig, root: Path) -> list[dict[str, str]]:               # line 118
def generate(cfg, root, *, release=None) -> tuple[list[RenderedPage], list[dict[str, str]]]:   # line 626
def _generate(cfg, root, release) -> tuple[list[RenderedPage], list[dict[str, str]]]:      # line 647

# griffe 2.4.1 (optional extra `techwiki`, `griffe>=2.4,<3`)
griffe.load(objspec, /, *, search_paths=None, allow_inspection: bool = True, force_inspection: bool = False, ...)
```

### Does NOT Exist (Anti-Hallucination)

- ~~`_native_modules`, `strict_failures`, `NATIVE_SKIP_KIND`, `NATIVE_SKIP_REASON` in `api.py` today~~ — added by this spec.
- ~~a `kind` key on existing skipped entries~~ — syntax-error and render-failure entries carry only
  `module` and `reason`; they stay that way.
- ~~a `griffe.load` call in `bundle.py` or `check.py`~~ — the only one is `api.py:114`.
- ~~a `static_only` / `inspection` option in `TechwikiConfig`~~ — the behaviour is not configurable.

### Edit Sites (Blueprint Anchors)

Verified against: `22917ab6fe`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` | MODIFY | `                modules.append(griffe_module.load(module_root, search_paths=[source_root]))` | `api.py:114` | 1 |
| `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` | MODIFY | `def _module_all(module: Any) -> set[str] \| None:` (insert the new functions before it) | `api.py:157` | 1 |
| `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` | MODIFY | `    skipped.extend(_syntax_errors(cfg, root))` | `api.py:662` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py` | MODIFY | `    return 4 if args.strict and skipped else 0` | `techwiki_api.py:53` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py` | MODIFY | `    return 4 if args.strict and report.skipped_modules else 0` | `techwiki_bundle.py:75` | 1 |
| `packages/ai-parrot/tests/sdd/test_techwiki_api.py` | MODIFY | append at end of file | — | — |
| `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` | MODIFY | append at end of file | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `_syntax_errors` is the model for `_native_modules`: same configured-root loop, same
  `{"module", "reason"}` entry shape, same sort.
- Tests that render pages call `_require_griffe()` first; `test_load_packages_disables_inspection` and
  `test_strict_failures_excludes_native_entries` do not need griffe and must not skip.

### Known Risks / Gotchas

- **A page disappears locally.** On a checkout with built extensions, `parrot.utils.types` and
  `parrot.utils.parsers.toml` lose their inspected pages and become native entries. That is the intended
  result (G3); `_unlink_pageless_refs` already downgrades links to a module without a page.
- **Strict mode.** The release workflow runs `techwiki bundle --strict`. Listing the two Cython modules
  must not turn that into exit 4 — hence G4 and `strict_failures`.
- **Do not import the fixture.** No test may add the fixture source root to `sys.path`.

### External Dependencies

None. `griffe>=2.4,<3` is already declared in the `techwiki` extra.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-900-fixgroup-d908bfcc4d62`.
- **Module dependency graph**: M2's CLIs import `strict_failures` from M1's file; both modules are one task.
- **Shared files**: `api.py`, `tests/sdd/test_techwiki_api.py` (M1, M2).
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none (FEAT-801 is merged).

---

## Consequences

<!-- decision-audit: input_digest=sha256:d74ac3751eb76653b4dfdf3d9800854c51053502203bc4a771d9a2c52e8ea2ba evaluation_digest=sha256:2c97799ea2c5951e9f0deb1e5a246af8165a0285de825b80f8e0b892c3a69ed4 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/fixgroup-d908bfcc4d62.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: bugfix, sdd-tooling, static-analysis, techwiki
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
      "bugfix",
      "sdd-tooling",
      "static-analysis",
      "techwiki"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/fixgroup-d908bfcc4d62.spec.md"
    }
  ],
  "evaluation_digest": "sha256:2c97799ea2c5951e9f0deb1e5a246af8165a0285de825b80f8e0b892c3a69ed4",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:d74ac3751eb76653b4dfdf3d9800854c51053502203bc4a771d9a2c52e8ea2ba",
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

None.

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document — ledger fix group authored by `/sdd-fix`).

---

## 10. Documentation

- **Policy**: `none`. No wiki page documents the skipped-module report or `--strict`; the CLI help strings
  are updated in M2.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-15 | Jesus Lara | Initial spec from `issue:5af0e518b2e8` |
