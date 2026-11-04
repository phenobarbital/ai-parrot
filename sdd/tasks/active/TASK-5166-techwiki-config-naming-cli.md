# TASK-5166: Techwiki configuration, naming and CLI noun

**Feature**: FEAT-801 — GitHub Wiki as the Technical Reference
**Spec**: `sdd/specs/github-wiki-technical-reference.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the foundation task (spec §3 M1). It creates the `parrot.sdd.techwiki` package,
> the Pydantic configuration model (`TechwikiConfig`), the `TechwikiPackage` model,
> page-naming utilities, the link-rewriting engine, the `sdd/config.json` `techwiki` key,
> the `pyproject.toml` optional extra, and mounts the `techwiki` CLI noun.
> Every subsequent task imports from these modules.

---

## Scope

- CREATE `parrot.sdd.techwiki` package (`__init__.py`, `config.py`, `naming.py`)
- CREATE `TechwikiPackage` and `TechwikiConfig` Pydantic v2 models with `extra="forbid"`
- CREATE `load_techwiki_config(root)` that reads the `techwiki` section from `sdd/config.json`
- CREATE `page_name(section, title)`, `page_title(path, text)`, `rewrite_links(text, resolver)` in `naming.py`
- MODIFY `SddConfig` to add `techwiki: TechwikiConfig | None = None` field
- MODIFY `packages/ai-parrot/pyproject.toml`: add `techwiki` optional extra and `"techwiki/templates/*.j2"` package-data
- MODIFY `packages/ai-parrot/src/parrot/sdd/cli.py`: add `VERBS["techwiki"]` entry
- MODIFY `sdd/config.json`: add full `techwiki` object with all workspace Python distributions
- CREATE tests: `test_techwiki_config.py`, `test_techwiki_naming.py`

**NOT in scope**: API generator (TASK-5167), bundle assembler (TASK-5168), template changes (TASK-5169), check command (TASK-5170), Jinja templates for rendering.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/__init__.py` | CREATE | Package init |
| `packages/ai-parrot/src/parrot/sdd/techwiki/config.py` | CREATE | TechwikiPackage, TechwikiConfig, load_techwiki_config |
| `packages/ai-parrot/src/parrot/sdd/techwiki/naming.py` | CREATE | page_name, page_title, rewrite_links, PageNameError |
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | Add techwiki field to SddConfig |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | Add VERBS["techwiki"] |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add techwiki extra + package-data entry |
| `sdd/config.json` | MODIFY | Add techwiki key with full packages inventory |
| `packages/ai-parrot/tests/sdd/test_techwiki_config.py` | CREATE | Config unit tests |
| `packages/ai-parrot/tests/sdd/test_techwiki_naming.py` | CREATE | Naming unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict                    # verified: packages/ai-parrot/src/parrot/sdd/config.py:3
from parrot.sdd.config import SddConfig, load_sdd_config, SddConfigError  # verified: config.py:19,106,15
from parrot.sdd.cli import VERBS                              # verified: cli.py:237
import yaml                                                    # verified: check_e2e_closeout.py:22
import re                                                      # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/config.py:19
class SddConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_branch: str = "dev"                       # line 24
    staging_branch: str | None = None              # line ~25
    hotfix_base: str = "main"                      # line ~26
    issue_tracker: str | None = None               # line ~30
    jira_host: str | None = None                   # line ~31
    reviewer: str | None = None                    # line ~33
    test_command: str | None = None                # line ~34
    projects: list[str] | None = None              # line 35

# packages/ai-parrot/src/parrot/sdd/config.py:106
def load_sdd_config(root: Path | None = None) -> SddConfig:
    # reads sdd/config.json → SddConfig(**data)

# packages/ai-parrot/src/parrot/sdd/cli.py:237
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {
    # "worktree": {...}, "task": {...}, ...
    "hooks": {  # line 302
        ...
    },
}
# Mount loop at module bottom iterates VERBS

# packages/ai-parrot/src/parrot/sdd/cli.py:311
def mounted_modules() -> set[str]:  # returns {module_name for each verb entry}

# scripts/sdd/check_asset_sync.py:32
ASSET_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # includes "sdd/templates/*"
)
```

### Does NOT Exist
- ~~`parrot.sdd.techwiki`~~ — created by this task
- ~~`SddConfig.techwiki`~~ — not a field today; `extra="forbid"` rejects the key
- ~~`VERBS["techwiki"]`~~ — not in the dict today
- ~~`griffe`~~ in any pyproject.toml or in the venv
- ~~`parrot.sdd.techwiki.config.TechwikiPackage`~~ — created by this task
- ~~`sdd/config.json` `"techwiki"` key~~ — not present today

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/config.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/naming.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "sdd/config.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_config.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_naming.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#SddConfig",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#load_sdd_config",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#VERBS",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#mounted_modules"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror `check_e2e_closeout.py` and `config.py` patterns:
- Pydantic v2 models with `extra="forbid"` for configuration
- Pure functions returning dataclasses/values, no side effects
- Module logger via `logging.getLogger(__name__)`

### Key Constraints
- `page_name` MUST reject titles with literal hyphens (`PageNameError`) — GitHub stores them as U+2010
- `rewrite_links` handles both relative `.md` links and `ref:<module>` links → `[[Page Name]]`
- `sdd/config.json` must list EVERY Python-bearing workspace member with correct `dist`, `src`, `roots`
- The `techwiki` extra must declare `griffe>=2.4,<3` and `jinja2>=3.1` explicitly
- `test_techwiki_config.py` must compare configured distributions with the workspace's Python-bearing
  members so a new or omitted distribution fails validation

### References in Codebase
- `packages/ai-parrot/src/parrot/sdd/config.py` — pattern for Pydantic config models
- `packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py` — pattern for resolve_policy

---

## Implementation Blueprint

### Steps (in order)
1. Create `techwiki/__init__.py` — *why*: establish the package so other modules can import from it
2. Create `techwiki/config.py` with `TechwikiPackage`, `TechwikiConfig`, `load_techwiki_config` — *why*: every other M depends on the config model
3. Create `techwiki/naming.py` with `PageNameError`, `page_name`, `page_title`, `rewrite_links` — *why*: naming rules are used by M2 (api) and M3 (bundle)
4. Modify `config.py` to add `techwiki` field to `SddConfig` — *why*: `extra="forbid"` requires the field before the key can appear in config.json
5. Modify `cli.py` to add `VERBS["techwiki"]` — *why*: mounts the four sub-commands (api, bundle, check, sidebar)
6. Modify `pyproject.toml` for the extra and package-data — *why*: griffe must be installable, templates must be packaged
7. Modify `sdd/config.json` with the full `techwiki` object — *why*: this is the runtime config for this repository
8. Create tests — *why*: AC-1, AC-2, AC-3b

### `packages/ai-parrot/src/parrot/sdd/techwiki/__init__.py` (CREATE)
```python
"""Technical-wiki pipeline for AI-Parrot (FEAT-801).

Subcommands: ``parrot sdd techwiki api | bundle | check | sidebar``.
"""
```
**Why this shape**: Empty init — sub-modules are imported lazily by the CLI mount loop.

### `packages/ai-parrot/src/parrot/sdd/techwiki/config.py` (CREATE)
```python
"""TechwikiConfig — Pydantic v2 model for the ``techwiki`` section of ``sdd/config.json``."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class TechwikiPackage(BaseModel):
    """One Python distribution in the workspace whose public API is rendered."""

    model_config = ConfigDict(extra="forbid")

    dist: str
    """Distribution name, e.g. ``ai-parrot-tools``."""
    src: str
    """Repository-relative search path for griffe, e.g. ``packages/ai-parrot-tools/src``."""
    roots: list[str]
    """Top-level import names to load, e.g. ``["parrot_tools"]``."""


class TechwikiConfig(BaseModel):
    """Settings for the technical-wiki pipeline."""

    model_config = ConfigDict(extra="forbid")

    source_dir: str = "wiki"
    index_file: str = "wiki/_index.yaml"
    packages: list[TechwikiPackage] = []
    include_adrs: list[str] = ["docs/decisions/**/*.md"]
    adr_section: str = "Decisions"
    reference_section: str = "API Reference"
    site_url: str | None = None
    source_url: str | None = None
    exclude: list[str] = []


def load_techwiki_config(root: Path) -> TechwikiConfig:
    """Return the ``techwiki`` section of ``sdd/config.json`` (defaults when absent).

    Args:
        root: Repository root directory.

    Returns:
        TechwikiConfig parsed from the JSON, or defaults when the key is absent.
    """
    config_path = root / "sdd" / "config.json"
    if not config_path.exists():
        logger.debug("No sdd/config.json at %s — returning defaults", root)
        return TechwikiConfig()
    with open(config_path) as f:
        data = json.load(f)
    raw = data.get("techwiki")
    if raw is None:
        return TechwikiConfig()
    return TechwikiConfig(**raw)
```
**Why this shape**: Mirrors `load_sdd_config` — reads the same file, returns a typed model. `extra="forbid"` catches unknown keys early.

### `packages/ai-parrot/src/parrot/sdd/techwiki/naming.py` (CREATE)
```python
"""GitHub Wiki page-naming rules and link rewriting."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import yaml


class PageNameError(ValueError):
    """Raised for a title GitHub would rewrite (literal hyphen) or an empty title."""


def page_name(section: str | None, title: str) -> str:
    """Return the GitHub wiki page name: ``<Section>-<Title>`` with spaces as ``-``.

    Raises:
        PageNameError: When the title contains a literal hyphen (GitHub stores it
            as U+2010 '‐', so ``[[Title]]`` links would point at a different page)
            or when the title is empty.
    """
    if not title or not title.strip():
        raise PageNameError("Page title must not be empty")
    if "-" in title:
        raise PageNameError(
            f"Title {title!r} contains a literal hyphen — GitHub would store it "
            f"as U+2010 ('‐'), breaking [[Title]] links. Use a space instead."
        )
    parts = title.strip().split()
    name = "-".join(parts)
    if section:
        if "-" in section:
            raise PageNameError(f"Section {section!r} contains a literal hyphen")
        sec_parts = section.strip().split()
        prefix = "-".join(sec_parts)
        name = f"{prefix}-{name}"
    return name


def page_title(path: Path, text: str) -> str:
    """Extract the page title: frontmatter ``title``, else the first H1, else the file stem in Title Case.

    Args:
        path: Path to the markdown file (used for stem fallback).
        text: Full file content.

    Returns:
        The resolved title string.
    """
    # FILL IN: YAML frontmatter extraction and H1 regex — bounded by AC-5 naming rules
    raise NotImplementedError


def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str:
    """Rewrite relative ``.md`` links and ``ref:<module>`` links to ``[[Page Name]]``.

    Unknown targets (resolver returns ``None``) are left unchanged and collected
    by the caller as dangling.

    Args:
        text: Markdown content.
        resolver: Maps a relative path or ``ref:<module>`` to a wiki page name,
            or ``None`` when the target is unknown.

    Returns:
        Rewritten markdown content.
    """
    # FILL IN: regex replacement of [text](path.md) and [text](ref:module) links — bounded by AC-5 link rewriting
    raise NotImplementedError
```
**Why this shape**: Pure functions, no side effects. `page_name` enforces the U+2010 rule (spec §7 gotcha). `page_title` and `rewrite_links` are FILL IN because they involve regex/parsing decisions bounded by AC-5.

### `packages/ai-parrot/src/parrot/sdd/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'projects: list\[str\] | None = None' packages/ai-parrot/src/parrot/sdd/config.py)
# AFTER — insert below `    projects: list[str] | None = None` (verified: config.py:35)
    #: FEAT-801 — technical-wiki pipeline settings; ``None`` means defaults.
    techwiki: "TechwikiConfig | None" = None
```
**Why**: `SddConfig` is `extra="forbid"`, so the field MUST exist before `sdd/config.json` carries the key. Forward-ref string avoids circular import; the type is resolved at validation time. Placed after `projects` (last current field).

Note: Add `from __future__ import annotations` at the top of the file if not already present, and add `from parrot.sdd.techwiki.config import TechwikiConfig` inside a `TYPE_CHECKING` block or use the string annotation `"TechwikiConfig | None"` with a model_validator that imports lazily.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "hooks": {' packages/ai-parrot/src/parrot/sdd/cli.py)
# BEFORE — insert above `    "hooks": {` (verified: cli.py:302)
    "techwiki": {
        "api": ("techwiki_api", (), "Generate the markdown API reference for the configured packages."),
        "bundle": ("techwiki_bundle", (), "Assemble the publishable GitHub-wiki bundle (authored + API + ADRs)."),
        "check": ("techwiki_check", (), "Report a spec's declared documentation pages (never blocking)."),
        "sidebar": ("techwiki_bundle", ("--sidebar-only",), "Render Home.md and _Sidebar.md only."),
    },
```
**Why**: VERBS dict maps noun → {verb → (script_module, prefix_args, help)}. The mount loop at module bottom creates the click group and mounts each verb.

### `packages/ai-parrot/pyproject.toml` (MODIFY — extra)
```toml
# occurrences: 1 (verified: grep -c 'wikitoolkit-server = \["ai-parrot-server"\]' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `wikitoolkit-server = ["ai-parrot-server"]` (verified: pyproject.toml:379)
techwiki = ["griffe>=2.4,<3", "jinja2>=3.1"]
```
**Why**: Self-contained extra (AC-3b). jinja2 is otherwise only in `agents` extra.

### `packages/ai-parrot/pyproject.toml` (MODIFY — package-data)
```toml
# occurrences: 1 (verified: grep -c '"_assets/sdd/CODEX.md",' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `    "_assets/sdd/CODEX.md",` (verified: pyproject.toml:~1010)
    "techwiki/templates/*.j2",
    "techwiki/templates/*.md.j2",
```
**Why**: Jinja templates must be packaged under `parrot.sdd` so `importlib.resources` can find them.

### `sdd/config.json` (MODIFY)
```json
// occurrences: 1 (verified: grep -c '"test_command": null' sdd/config.json)
// AFTER — insert below `  "test_command": null` (verified: sdd/config.json:8)
// FILL IN: complete techwiki object with all workspace Python-bearing distributions
// Each entry: {"dist": "<name>", "src": "packages/<name>/src", "roots": ["<import_root>"]}
// For parrot namespace packages (PEP 420), roots = ["parrot"]
// For top-level packages, roots = ["parrot_tools"], ["parrot_loaders"], etc.
// Include all ai-parrot-client-* providers, ai-parrot-openlit-bridge, navrules, parrot-formdesigner
// Bounded by AC-2: test_workspace_python_distribution_coverage validates completeness
```
**Why**: The config drives which packages the API reference renders. Must match every Python-bearing workspace member.

### FILL IN checklist
- [ ] `naming.py::page_title` — YAML frontmatter parsing + H1 regex fallback; bounded by AC-5
- [ ] `naming.py::rewrite_links` — regex for `[text](path.md)` and `[text](ref:module)` → `[[Page Name]]`; bounded by AC-5
- [ ] `sdd/config.json` `techwiki.packages` — enumerate all 30 workspace members with correct dist/src/roots; bounded by AC-2
- [ ] `config.py` import strategy — forward-ref string or TYPE_CHECKING import for `TechwikiConfig` in `SddConfig`; bounded by `extra="forbid"` constraint

---

## Acceptance Criteria

- [ ] `parrot sdd techwiki --help` lists `api`, `bundle`, `check`, `sidebar` (AC-1)
- [ ] `mounted_modules()` includes the three new script modules (AC-1)
- [ ] `SddConfig` accepts `techwiki` key from `sdd/config.json` without `extra="forbid"` rejection
- [ ] `load_techwiki_config` returns defaults when the key is absent
- [ ] `page_name` rejects literal hyphens with `PageNameError` (AC-5)
- [ ] `rewrite_links` converts relative `.md` and `ref:` links to `[[Page Name]]` format
- [ ] `test_workspace_python_distribution_coverage` passes: every Python-bearing workspace member is configured (AC-2)
- [ ] `techwiki` extra installs griffe and jinja2 (AC-3b)
- [ ] No `requests`/`httpx`/LangChain imports; `ruff check` passes on every touched file (AC-14)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_config.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_techwiki_naming.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_config.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_techwiki_config.py
import pytest
from pathlib import Path
from parrot.sdd.techwiki.config import TechwikiPackage, TechwikiConfig, load_techwiki_config
from parrot.sdd.config import SddConfig, load_sdd_config


class TestTechwikiConfig:
    def test_defaults_and_forbid_extra(self):
        """TechwikiConfig defaults; unknown key rejected."""
        cfg = TechwikiConfig()
        assert cfg.source_dir == "wiki"
        with pytest.raises(Exception):
            TechwikiConfig(unknown_key="x")

    def test_sdd_config_techwiki_roundtrip(self, tmp_path: Path):
        """SddConfig.techwiki round-trips sdd/config.json."""
        # FILL IN: write a config.json with techwiki, load it, assert fields

    def test_load_techwiki_config_absent(self, tmp_path: Path):
        """Missing techwiki key returns defaults."""
        (tmp_path / "sdd").mkdir()
        (tmp_path / "sdd" / "config.json").write_text('{"base_branch": "dev"}')
        cfg = load_techwiki_config(tmp_path)
        assert cfg.packages == []

    def test_workspace_python_distribution_coverage(self):
        """Configured distributions cover every Python-bearing workspace member."""
        # FILL IN: read root pyproject.toml workspace members, compare with sdd/config.json techwiki.packages
        # A new or omitted distribution must fail this test — bounded by AC-2


# packages/ai-parrot/tests/sdd/test_techwiki_naming.py
import pytest
from parrot.sdd.techwiki.naming import page_name, page_title, rewrite_links, PageNameError


class TestPageName:
    def test_spaces_to_dashes(self):
        assert page_name("Memory", "Conversation Compaction") == "Memory-Conversation-Compaction"

    def test_section_prefix(self):
        assert page_name("Clients", "Abstract Client") == "Clients-Abstract-Client"

    def test_no_section(self):
        assert page_name(None, "Home") == "Home"

    def test_literal_hyphen_raises(self):
        with pytest.raises(PageNameError):
            page_name(None, "my-page")

    def test_empty_title_raises(self):
        with pytest.raises(PageNameError):
            page_name(None, "")


class TestRewriteLinks:
    def test_relative_md_link(self):
        """Relative .md link → [[Page Name]]."""
        # FILL IN — bounded by AC-5

    def test_ref_link(self):
        """ref:<module> link → [[Reference-module]]."""
        # FILL IN — bounded by AC-5

    def test_unknown_target_collected(self):
        """Unknown target returns None; link left unchanged."""
        # FILL IN — bounded by AC-5
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug github-wiki-technical-reference --feature-id FEAT-801`)
2. **Read the spec** at `sdd/specs/github-wiki-technical-reference.spec.md` for full context
3. **Check dependencies** — this task has no dependencies
4. **Verify the Codebase Contract** — confirm `SddConfig` still has `projects` at line 35, `VERBS` at cli.py:237, `extra="forbid"` on SddConfig
5. **Update status** in `sdd/tasks/index/github-wiki-technical-reference.json` → `"in-progress"`
6. **Implement** starting from the blueprints above; complete every FILL IN
7. **Critical**: enumerate ALL workspace Python-bearing distributions in `sdd/config.json` — the test validates completeness
8. **Verify** all acceptance criteria — run the Validation Commands
9. **Commit** only the files listed above
10. **Close** with `parrot sdd task close TASK-5166 github-wiki-technical-reference verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
