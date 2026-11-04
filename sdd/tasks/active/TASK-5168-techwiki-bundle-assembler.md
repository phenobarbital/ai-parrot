# TASK-5168: Bundle assembler, Home and Sidebar

**Feature**: FEAT-801 — GitHub Wiki as the Technical Reference
**Spec**: `sdd/specs/github-wiki-technical-reference.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5166, TASK-5167
**Assigned-to**: unassigned

---

## Context

> Spec §3 M3. Merges authored pages from `wiki/`, generated API reference from M2, and
> ADRs from `docs/decisions/` into a flat, publish-ready directory. Produces `Home.md`,
> `_Sidebar.md`, `techwiki-report.json`, `techwiki-manifest.json`. Detects page-name
> collisions and dangling links (exit 1).

---

## Scope

- CREATE `parrot.sdd.techwiki.bundle` module: `BundlePage`, `BundleReport`, `collect_authored`,
  `collect_adrs`, `assemble`, `write_bundle`
- CREATE `techwiki/templates/home.md.j2`, `techwiki/templates/sidebar.md.j2`
- CREATE `parrot.sdd.scripts.techwiki_bundle` CLI shim
- CREATE `test_techwiki_bundle.py`
- CREATE test fixture `tests/sdd/fixtures/techwiki_repo/` (mini repo)

**NOT in scope**: API generator (TASK-5167), check command (TASK-5170), workflow (TASK-5171).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` | CREATE | Bundle assembler |
| `packages/ai-parrot/src/parrot/sdd/techwiki/templates/home.md.j2` | CREATE | Home page template |
| `packages/ai-parrot/src/parrot/sdd/techwiki/templates/sidebar.md.j2` | CREATE | Sidebar template |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py` | CREATE | CLI entrypoint |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/sdd/config.json` | CREATE | Fixture config |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/wiki/_index.yaml` | CREATE | Fixture index |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/wiki/a/one.md` | CREATE | Fixture authored page |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/wiki/b/two.md` | CREATE | Fixture page (dangling link) |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/wiki/b/two-copy.md` | CREATE | Fixture page (collision) |
| `packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/docs/decisions/one.md` | CREATE | Fixture ADR |
| `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.techwiki.config import TechwikiConfig, load_techwiki_config  # TASK-5166
from parrot.sdd.techwiki.naming import page_name, page_title, rewrite_links, PageNameError  # TASK-5166
from parrot.sdd.techwiki.api import generate, RenderedPage, GriffeUnavailable  # TASK-5167
import yaml       # verified: stdlib/PyYAML 6.0.3
import json       # stdlib
```

### Existing Signatures to Use
```python
# From TASK-5166:
def page_name(section: str | None, title: str) -> str: ...
def page_title(path: Path, text: str) -> str: ...
def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str: ...

# From TASK-5167:
@dataclass(frozen=True)
class RenderedPage:
    module: str; section: str; title: str; body: str

def generate(cfg: TechwikiConfig, root: Path, *, release: str | None) -> tuple[list[RenderedPage], list[dict]]: ...
```

### Does NOT Exist
- ~~`parrot.sdd.techwiki.bundle`~~ — created by this task
- ~~`parrot.sdd.scripts.techwiki_bundle`~~ — created by this task
- ~~`wiki/`~~ directory at repo root — created by TASK-5172 (M7)
- ~~`techwiki/templates/home.md.j2`~~, ~~`sidebar.md.j2`~~ — created by this task

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/templates/home.md.j2", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/templates/sidebar.md.j2", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_bundle.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Links resolve through the manifest (source path or `ref:` module → page name), never title strings (S9)
- Collisions and dangling links → exit 1 with report still written (AC-5)
- `--dry-run` writes nothing (only the report) (AC-6)
- `--sidebar-only` renders only `Home.md` and `_Sidebar.md`
- Home.md includes: release tag, commit SHA, link to informative site (AC-6)
- Sidebar: sections in `_index.yaml` order, then Decisions, then API Reference per distribution (AC-6)
- `techwiki-manifest.json`: source path/module id → page name for every page (S9)

---

## Implementation Blueprint

### Steps (in order)
1. Create `bundle.py` with data models and collection functions — *why*: core assembler
2. Create Home/Sidebar templates — *why*: generated pages for the wiki
3. Create CLI shim — *why*: `parrot sdd techwiki bundle` and `sidebar` commands
4. Create fixture repo and tests — *why*: AC-5, AC-6, S9

### `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` (CREATE)
```python
"""Bundle assembler — merge authored pages, generated API reference and ADRs."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from parrot.sdd.techwiki.config import TechwikiConfig, load_techwiki_config
from parrot.sdd.techwiki.naming import page_name, page_title, rewrite_links, PageNameError

if TYPE_CHECKING:
    from parrot.sdd.techwiki.api import RenderedPage

logger = logging.getLogger(__name__)


@dataclass
class BundlePage:
    """One page in the assembled bundle."""

    source: Path | None
    section: str
    title: str
    name: str
    body: str


@dataclass
class BundleReport:
    """Summary of the bundle assembly."""

    release: str | None
    commit: str | None
    authored: int = 0
    generated: int = 0
    adrs: int = 0
    skipped_modules: list[dict] = field(default_factory=list)
    collisions: list[dict] = field(default_factory=list)
    dangling: list[dict] = field(default_factory=list)

    def ok(self) -> bool:
        """True when no collisions or dangling links."""
        return not self.collisions and not self.dangling


def collect_authored(cfg: TechwikiConfig, root: Path) -> list[BundlePage]:
    """Collect authored pages from the wiki source directory.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.

    Returns:
        List of BundlePage for each authored markdown file.
    """
    # FILL IN: walk cfg.source_dir, read _index.yaml for sections, parse frontmatter — bounded by AC-6
    raise NotImplementedError


def collect_adrs(cfg: TechwikiConfig, root: Path) -> list[BundlePage]:
    """Collect ADR pages from docs/decisions/.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.

    Returns:
        List of BundlePage, each under the ADR section.
    """
    # FILL IN: glob include_adrs patterns, read-only inclusion — bounded by AC-6 (ADRs present)
    raise NotImplementedError


def assemble(
    cfg: TechwikiConfig,
    root: Path,
    *,
    release: str | None = None,
    commit: str | None = None,
    with_api: bool = True,
) -> tuple[list[BundlePage], BundleReport]:
    """Collect, name, rewrite links, detect collisions/dangling; never writes.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.
        release: Release tag.
        commit: Commit SHA.
        with_api: Whether to include generated API reference pages.

    Returns:
        (pages, report) — report includes collision and dangling info.
    """
    # FILL IN: collect_authored + collect_adrs + generate (if with_api),
    #   detect name collisions, rewrite links via manifest, collect dangling — bounded by AC-5, S9
    raise NotImplementedError


def write_bundle(
    pages: list[BundlePage],
    report: BundleReport,
    cfg: TechwikiConfig,
    out: Path,
) -> None:
    """Write the flat directory: one .md per page + Home.md + _Sidebar.md + report + manifest.

    Args:
        pages: Assembled pages.
        report: Bundle report.
        cfg: Techwiki configuration.
        out: Output directory.
    """
    # FILL IN: write each page as <name>.md, render Home.md and _Sidebar.md from templates,
    #   write techwiki-report.json and techwiki-manifest.json — bounded by AC-6
    raise NotImplementedError
```
**Why this shape**: Pure functions separating collection, assembly (link resolution + collision detection), and writing. The manifest is the authority for link resolution (S9).

### FILL IN checklist
- [ ] `bundle.py::collect_authored` — walk source_dir, parse _index.yaml, read frontmatter; bounded by AC-6
- [ ] `bundle.py::collect_adrs` — glob patterns, read-only inclusion; bounded by AC-6
- [ ] `bundle.py::assemble` — merge layers, collision detection, link rewriting via manifest; bounded by AC-5, S9
- [ ] `bundle.py::write_bundle` — flat output + Home/Sidebar templates + JSON files; bounded by AC-6
- [ ] `home.md.j2` — release, commit, site_url, sections summary; bounded by AC-6
- [ ] `sidebar.md.j2` — sections in order, Decisions, API Reference per dist; bounded by AC-6
- [ ] `techwiki_bundle.py::main` — CLI with --out/--root/--release/--dry-run/--json/--sidebar-only; bounded by AC-5

---

## Acceptance Criteria

- [ ] Collision and dangling links → exit 1 with report written (AC-5)
- [ ] `PageNameError` on hyphenated title reported in collisions (AC-5)
- [ ] Home.md has release, commit, site link; Sidebar has sections in order + Decisions + API Reference (AC-6)
- [ ] Every ADR from `docs/decisions/**` included read-only (AC-6)
- [ ] Manifest resolves every rewritten link target (S9)
- [ ] `--dry-run` writes nothing (only report)
- [ ] No `requests`/`httpx`/LangChain; `ruff check` passes (AC-14)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
import pytest
from pathlib import Path


@pytest.fixture
def techwiki_repo(tmp_path: Path) -> Path:
    """Copy the fixture repo into tmp_path and git init it."""
    # FILL IN: copy fixtures/techwiki_repo, git init + commit


class TestBundle:
    def test_bundle_collision_and_dangling_exit_1(self, techwiki_repo):
        """Report lists both; exit 1; files still written."""

    def test_bundle_home_sidebar_from_index(self, techwiki_repo):
        """Sections in _index.yaml order; ADR section present; release/commit on Home."""

    def test_bundle_dry_run_writes_nothing(self, techwiki_repo):
        """Only the report."""

    def test_bundle_manifest_resolves_links(self, techwiki_repo):
        """Every rewritten link target exists in techwiki-manifest.json (S9)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
2. **Check dependencies** — TASK-5166 and TASK-5167 must be `done`
3. **Verify** `parrot.sdd.techwiki.api.generate` and `parrot.sdd.techwiki.naming` exist
4. **Implement** — complete every FILL IN
5. **Run tests** — `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py -q`
6. **Commit** only the listed files
7. **Close** with `parrot sdd task close TASK-5168 github-wiki-technical-reference verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
