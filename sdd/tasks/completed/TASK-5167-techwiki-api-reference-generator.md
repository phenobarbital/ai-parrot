# TASK-5167: API reference generator

**Feature**: FEAT-801 — GitHub Wiki as the Technical Reference
**Spec**: `sdd/specs/github-wiki-technical-reference.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5166
**Assigned-to**: unassigned

---

## Context

> Spec §3 M2. Builds on TASK-5166's config and naming to statically load every configured
> workspace package with griffe and render one markdown page per public module through Jinja
> templates. The output is deterministic (AC-4) and golden-tested (S8). The generator never
> imports any package it documents — it reads source only.

---

## Scope

- CREATE `parrot.sdd.techwiki.api` module: `RenderedPage`, `GriffeUnavailable`, `load_packages`,
  `is_public`, `render_module`, `generate`
- CREATE `techwiki/templates/module.md.j2` Jinja template for one API reference page
- CREATE `parrot.sdd.scripts.techwiki_api` CLI shim (`main(argv) -> int`)
- CREATE test fixture package `tests/sdd/fixtures/techwiki_pkg/samplepkg/`
- CREATE golden output file `tests/sdd/fixtures/techwiki_golden/samplepkg.core.md` (the single generated page for fixture module `samplepkg.core`; if the generator's page name differs, name the file exactly after the generated page)
- CREATE `test_techwiki_api.py` covering: static loading, determinism, `__all__` filter, griffe
  unavailable exit 3, golden output match, `--strict` exit 4 on skipped modules, satellite
  distribution coverage

**NOT in scope**: Bundle assembler (TASK-5168), CLI mounting (done by TASK-5166).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` | CREATE | API reference generator |
| `packages/ai-parrot/src/parrot/sdd/techwiki/templates/module.md.j2` | CREATE | Jinja2 template |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py` | CREATE | CLI entrypoint |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_pkg/samplepkg/__init__.py` | CREATE | Fixture package init |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_pkg/samplepkg/core.py` | CREATE | Fixture module |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_golden/samplepkg.core.md` | CREATE | Golden output file |
| `packages/ai-parrot/tests/sdd/test_techwiki_api.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.techwiki.config import TechwikiConfig, TechwikiPackage, load_techwiki_config  # created by TASK-5166
from parrot.sdd.techwiki.naming import page_name, PageNameError                               # created by TASK-5166
import importlib.resources                                                                     # stdlib
```

### Existing Signatures to Use
```python
# From TASK-5166 (created by predecessor):
# parrot/sdd/techwiki/config.py
class TechwikiPackage(BaseModel):
    dist: str; src: str; roots: list[str]

class TechwikiConfig(BaseModel):
    packages: list[TechwikiPackage] = []
    reference_section: str = "API Reference"
    source_url: str | None = None

# parrot/sdd/techwiki/naming.py
def page_name(section: str | None, title: str) -> str: ...
```

### Does NOT Exist
- ~~`parrot.sdd.techwiki.api`~~ — created by this task
- ~~`parrot.sdd.scripts.techwiki_api`~~ — created by this task
- ~~`griffe`~~ in any pyproject.toml or the venv at task creation time (installed via the `techwiki` extra from TASK-5166)
- ~~`parrot.sdd.techwiki.templates/`~~ directory — created by this task

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/api.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/templates/module.md.j2", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/fixtures/techwiki_pkg/samplepkg/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/fixtures/techwiki_pkg/samplepkg/core.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/fixtures/techwiki_golden/samplepkg.core.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_api.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror `check_e2e_closeout.py`: pure functions, a `main(argv) -> int` CLI shim, JSON stdout.

### Key Constraints
- **Static analysis only** — `sys.modules` must be unchanged after `generate()` (AC-2 test asserts this)
- **Deterministic** — two runs on the same commit must produce byte-identical output (AC-4)
- Members sorted by source order within a class, alphabetically across modules
- Rendering rules (S8): `__all__` honoured, `_private` excluded, `__init__` merged into class,
  re-exports as one-line links, `@overload` collapsed, properties under "Attributes", Pydantic/dataclass
  fields under "Fields", nested classes with dotted headings
- `--strict` exit 4 when any module was skipped (parse failure)
- PEP 420 namespace roots (`parrot` split across distributions) loaded with all `src` paths on the search
  path at once so satellite subpackages merge into one tree
- Representative modules from client and satellite distributions must actually render (AC-2)

### References in Codebase
- `packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py` — CLI shim pattern

---

## Implementation Blueprint

### Steps (in order)
1. Create `techwiki/templates/` directory with `__init__.py` — *why*: `importlib.resources` needs it
2. Create `module.md.j2` template — *why*: rendering target for each public module
3. Create `api.py` with the generator logic — *why*: core M2 deliverable
4. Create `techwiki_api.py` CLI shim — *why*: mounted as `parrot sdd techwiki api`
5. Create fixture package and golden files — *why*: deterministic testing (S8)
6. Create tests — *why*: AC-2, AC-3, AC-4, AC-7b

### `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` (CREATE)
```python
"""API reference generator — static analysis via griffe, one markdown page per public module."""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from parrot.sdd.techwiki.config import TechwikiConfig

if TYPE_CHECKING:
    import griffe
    import jinja2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedPage:
    """One rendered API reference page."""

    module: str
    section: str
    title: str
    body: str


class GriffeUnavailable(RuntimeError):
    """griffe is not importable: install ``ai-parrot[techwiki]``."""


def _import_griffe() -> "griffe":
    """Lazy import; raises GriffeUnavailable with the extra name."""
    try:
        import griffe as _griffe
        return _griffe
    except ImportError as exc:
        raise GriffeUnavailable(
            "griffe is not installed. Install with: pip install ai-parrot[techwiki]"
        ) from exc


def load_packages(cfg: TechwikiConfig, root: Path) -> "list[griffe.Module]":
    """Statically load every configured root with griffe.

    PEP 420 namespace roots (``parrot`` split across distributions) are loaded with every
    configured ``src`` on the search path at once, so satellite subpackages merge into one tree.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.

    Returns:
        List of loaded griffe Module objects.
    """
    # FILL IN: build search_paths from cfg.packages, group by root name for namespace merging,
    #   call griffe.load() per unique root — bounded by AC-2 (satellite coverage)
    raise NotImplementedError


def is_public(obj: "griffe.Object") -> bool:
    """Determine whether a griffe object should be rendered.

    Rules (S8, golden-tested):
    - name does not start with ``_`` (``__init__`` merged into its class)
    - when the module defines ``__all__``, only those names
    - otherwise every non-underscore member
    """
    # FILL IN: __all__ check, underscore filter — bounded by AC-4 determinism + golden test
    raise NotImplementedError


def render_module(
    mod: "griffe.Module",
    *,
    template: "jinja2.Template",
    source_url: str | None,
    release: str | None,
) -> RenderedPage | None:
    """Render one page; None when the module has no public member.

    Args:
        mod: The griffe Module to render.
        template: Jinja2 template for the page.
        source_url: Base URL for source links.
        release: Release tag for source links.

    Returns:
        RenderedPage or None if no public members.
    """
    # FILL IN: filter public members, sort by source order within class / alphabetically across,
    #   render via template — bounded by AC-4 determinism
    raise NotImplementedError


def generate(
    cfg: TechwikiConfig, root: Path, *, release: str | None = None
) -> tuple[list[RenderedPage], list[dict]]:
    """Generate API reference pages for all configured packages.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.
        release: Release tag for source links.

    Returns:
        (pages, skipped) — skipped lists modules griffe could not parse.
    """
    # FILL IN: load_packages → iterate modules → render_module → collect pages and skipped
    #   — bounded by AC-2 (coverage), AC-4 (determinism)
    raise NotImplementedError
```
**Why this shape**: Pure functions, lazy griffe import, TYPE_CHECKING guard. The generator must never import any documented package.

### `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py` (CREATE)
```python
"""CLI shim for ``parrot sdd techwiki api``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the markdown API reference for the configured packages.

    Exit codes:
        0: success
        2: usage or config error
        3: griffe unavailable (message names the extra)
        4: ``--strict`` and at least one module was skipped
    """
    parser = argparse.ArgumentParser(description="Generate techwiki API reference")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--release", type=str, default=None, help="Release tag for source links")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON report on stdout")
    parser.add_argument("--strict", action="store_true", help="Exit 4 when any module is skipped")
    args = parser.parse_args(argv)

    from parrot.sdd.techwiki.api import GriffeUnavailable, generate
    from parrot.sdd.techwiki.config import load_techwiki_config

    try:
        cfg = load_techwiki_config(args.root)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    try:
        pages, skipped = generate(cfg, args.root, release=args.release)
    except GriffeUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3

    # FILL IN: write pages to args.out, print report/JSON, handle --strict — bounded by AC-7b
    raise NotImplementedError
```
**Why this shape**: Same pattern as `check_e2e_closeout.py` main — argparse, deferred imports, exit codes as contract.

### FILL IN checklist
- [ ] `api.py::load_packages` — search-path grouping for PEP 420 namespace merging; bounded by AC-2
- [ ] `api.py::is_public` — `__all__` check, underscore filter; bounded by golden test
- [ ] `api.py::render_module` — member sorting, template rendering; bounded by AC-4 determinism
- [ ] `api.py::generate` — orchestration of load → render → collect; bounded by AC-2, AC-4
- [ ] `techwiki_api.py::main` — write output, JSON report, `--strict` check; bounded by AC-7b
- [ ] `module.md.j2` — rendering layout: classes/methods/functions/parameter tables/returns/raises/examples/source links; bounded by golden test
- [ ] Fixture package: `__all__`, private methods, Pydantic model, re-export, overload, property, nested class — bounded by S8
- [ ] Golden files: frozen rendered output of fixture package — bounded by AC-4

---

## Acceptance Criteria

- [ ] `sys.modules` unchanged after `generate()` on the fixture package (AC-2)
- [ ] Representative modules from client and satellite distributions render (AC-2)
- [ ] `GriffeUnavailable` raised → exit 3 with message naming `ai-parrot[techwiki]` (AC-3)
- [ ] Two consecutive runs produce byte-identical output (AC-4)
- [ ] `--strict` exits 4 when any module was skipped (AC-7b)
- [ ] Golden output matches fixture package rendering (S8)
- [ ] Rendering rules: `__all__`, re-exports, overloads, properties, Pydantic fields, nested classes (S8)
- [ ] No `requests`/`httpx`/LangChain; `ruff check` passes (AC-14)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_api.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_techwiki_api.py
import pytest
import sys
from pathlib import Path


class TestGenerate:
    def test_generate_static_no_import(self, techwiki_repo):
        """Fixture package renders without being importable (sys.modules untouched)."""
        # FILL IN: snapshot sys.modules, call generate, assert no new keys from fixture

    def test_generate_is_deterministic(self, techwiki_repo):
        """Two runs → identical bytes."""
        # FILL IN: call generate twice, compare all page bodies

    def test_generate_satellite_coverage(self):
        """Representative modules from client/satellite distributions actually render."""
        # FILL IN: use the real repo config, assert at least one page from a client dist


class TestPublicFilter:
    def test_private_excluded(self):
        """_private names are excluded."""
        # FILL IN

    def test_all_honoured(self):
        """When __all__ is defined, only those names appear."""
        # FILL IN


class TestCli:
    def test_griffe_unavailable_exit_3(self, monkeypatch):
        """Monkeypatched import failure → exit 3 with extra named."""
        # FILL IN

    def test_strict_fails_on_skipped_module(self, techwiki_repo):
        """A fixture module with a syntax error → listed in report; --strict exit 4."""
        # FILL IN

    def test_generate_matches_golden(self, techwiki_repo):
        """Fixture package output == golden files byte-for-byte."""
        # FILL IN


class TestRenderingRules:
    def test_rendering_rules(self, techwiki_repo):
        """__all__, re-export alias, overload collapse, property, Pydantic field, nested class."""
        # FILL IN: assert specific patterns in rendered output
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug github-wiki-technical-reference --feature-id FEAT-801`
2. **Read the spec** at `sdd/specs/github-wiki-technical-reference.spec.md` (§3 M2)
3. **Check dependencies** — TASK-5166 must be `done`
4. **Verify** that `parrot.sdd.techwiki.config` and `parrot.sdd.techwiki.naming` exist (created by TASK-5166)
5. **Install griffe**: `uv sync --package ai-parrot --extra techwiki`
6. **Implement** — complete every FILL IN
7. **Run tests** and verify golden output is deterministic
8. **Commit** only the listed files
9. **Close** with `parrot sdd task close TASK-5167 github-wiki-technical-reference verified`

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-terra (codex), attempt 1 (uid 265e0482…), 386s, 0 retries.
**Date**: 2026-11-05
**Notes**: All 7 listed paths delivered (golden dir replaced by the single file `techwiki_golden/samplepkg.core.md` — table/contract fixed beforehand, commit fa45cc8fc8). Engine lint commit 16f1878473. Merge-tier validation exit 0 but **2 passed, 5 skipped**: the `griffe` extra is not installed in the shared env and the sandbox has no route to PyPI, so the generator/golden/determinism tests did NOT execute. Verification therefore `partial` — re-run `pytest packages/ai-parrot/tests/sdd/test_techwiki_api.py` with `ai-parrot[techwiki]` installed before merging. `coder_record_review` is broken server-side (not recorded).

**Deviations from spec**: golden output is a single file instead of a directory.
