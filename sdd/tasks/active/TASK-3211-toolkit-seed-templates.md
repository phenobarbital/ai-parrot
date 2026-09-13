# TASK-3211: Packaged toolkit templates + `.parrot/mcp-toolkits.yaml` seeder

**Feature**: FEAT-556 — `parrot claude install` seeds and authorizes the Parrot MCP servers
**Spec**: `sdd/specs/claude-install-mcp-autoenable.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. Nothing in the codebase creates
`.parrot/mcp-toolkits.yaml` today — `install_claude_integration` persists only
`.parrot/wiki.json` (`installer.py:625`) — so every non-builtin toolkit
(`sdd-coder`, `bounded-source`, `targeted-writer`) has to be hand-appended by
the operator, exactly as `examples/sdd-coder-mcp.yaml:6-17` instructs with a
`sed` pipeline. `.parrot/` is git-ignored by the installer itself
(`_install_gitignore`, `installer.py:568`), so the file can never arrive via
`git clone`: it must be generated from templates that ship in the wheel.

This task builds the tool-agnostic half: the templates and the seeder. The
three installers (claude_code, codex, google) consume it in TASK-3214 and
TASK-3215.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` with
  `ToolkitTemplate`, `SeedResult`, `available_templates()`, `load_template()`
  and `seed_toolkit_sections()`.
- Add three packaged templates under
  `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/`: `sdd-coder.yaml`,
  `bounded-source.yaml`, `targeted-writer.yaml`.
- Register the template directory as package data in
  `packages/ai-parrot/pyproject.toml`.
- Write unit tests in `tests/mcp/test_toolkit_seed.py`.

**NOT in scope**: any change to `.mcp.json` or entry shapes (TASK-3212), the
approval write (TASK-3213), CLI flags (TASK-3214), codex/google (TASK-3215).
Do not touch `parrot/mcp/toolkit_config.py` — the seeder only *calls* it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | CREATE | Templates + append-only seeder |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` | CREATE | FEAT-549 roster, credential-free |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml` | CREATE | Bounded reader, `{{repo_root}}` |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/targeted-writer.yaml` | CREATE | `requires_llm: true` → seeded disabled |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `[tool.setuptools.package-data]` entry |
| `tests/mcp/test_toolkit_seed.py` | CREATE | Unit tests (sits next to `tests/mcp/test_toolkit_config.py`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from importlib.resources import files          # verified: parrot/flows/conventions.py:11
from pydantic import BaseModel, Field          # verified: parrot/mcp/toolkit_config.py:16
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: parrot/mcp/toolkit_config.py:105
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig:  # line 105
    # default path: root / ".parrot" / "mcp-toolkits.yaml"       # line 138
    # absent default path -> builtins only, no raise              # lines 147-150
    # malformed file / unknown top-level key -> ValueError        # lines 163-173

class MCPToolkitsConfig(BaseModel):            # line 79
    toolkits: dict[str, ToolkitSection]        # line 86

class ToolkitSection(BaseModel):               # line 19
    class_path: str = Field(..., alias="class")  # line 49
    enabled: bool = True                         # line 50
    kwargs: dict[str, Any]                       # line 51
    llm: str | None                              # line 54
    llm_kwargs: dict[str, Any]                   # line 55
    env: dict[str, str]                          # line 56

BUILTIN_TOOLKITS: dict[str, ToolkitSection]    # line 89 — scraping, browsing, memory ONLY

# packages/ai-parrot/src/parrot/flows/conventions.py — the packaged-data read pattern to copy
def _package_rule(name: str) -> str:                                                   # line 48
    return (files("parrot.flows") / "_rules_data" / f"{name}.md").read_text(encoding="utf-8")  # line 50
```

### Does NOT Exist
- ~~`parrot.mcp.toolkit_seed`~~ — this task creates it.
- ~~`parrot/mcp/_toolkit_templates/`~~ — this task creates it. The only existing
  templates are repo-root `examples/*.yaml`, which are NOT package data
  (`packages/ai-parrot/pyproject.toml:894-907` lists no `examples` entry) and
  are therefore unreadable from an installed wheel.
- ~~`sdd-coder` / `bounded-source` / `targeted-writer` in `BUILTIN_TOOLKITS`~~ —
  only `scraping`, `browsing`, `memory` are built in (`toolkit_config.py:89-102`).
- ~~`MCPToolkitsConfig.save()` / any writer in `toolkit_config.py`~~ — that
  module only reads; there is no existing YAML-writing helper to reuse.
- ~~`ToolkitSection.requires_llm`~~ — not a field of the config model; it is a
  template-only flag introduced by this task's `ToolkitTemplate`.

---

## Implementation Notes

### Key Constraints
- Stdlib + pydantic + yaml only; **no import from `parrot.knowledge.wiki`** —
  this module is consumed by three installers and must stay tool-agnostic.
- Append-only: an existing section with the same key is NEVER rewritten. It is
  operator data.
- Read templates through `importlib.resources.files("parrot.mcp")`, never
  `Path(__file__).parent`, so the code works from a wheel.
- Templates carry no credentials and no absolute path other than the rendered
  `{{repo_root}}`.
- Google-style docstrings, strict type hints, 120-column lines, `black` format.

### References in Codebase
- `parrot/flows/conventions.py:44-75` — packaged-data reading + the
  "package copy is the fallback" pattern.
- `examples/sdd-coder-mcp.yaml`, `examples/tool-optimizations-mcp.yaml` —
  the section bodies to base the templates on (strip operator specifics).
- `.parrot/mcp-toolkits.yaml` (this machine, git-ignored) — a real merged file;
  useful to eyeball the expected shape, NOT to copy verbatim.

---

## Implementation Blueprint

### Steps (in order)
1. Create the three template files first — *why*: the model fields
   (`requires_llm`, `summary`) are driven by what the templates need to declare,
   and the parser is trivial once their header format is fixed.
2. Write `toolkit_seed.py` with the two models, then `available_templates()` /
   `load_template()`, then `seed_toolkit_sections()` — *why*: the seeder's
   append logic is the only non-mechanical part; everything it needs must exist
   first.
3. Add the package-data line — *why*: without it the templates are absent from
   the wheel and `available_templates()` returns an empty tuple in any real
   install, which no unit test run from the repo would catch.
4. Write the tests, including one that asserts resolution via
   `importlib.resources` rather than a repo path — *why*: AC demands the
   wheel path be the tested path.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml` (CREATE)
```yaml
# parrot:summary: Bounded source reading — large files require an explicit line range.
# parrot:requires_llm: false
  bounded-source:
    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit
    kwargs:
      repo_root: {{repo_root}}
      # Both thresholds are configurable; these are the defaults.
      # max_lines: 350
      # large_file_bytes: 64000
```
**Why this shape**: the file holds the section body **already indented two
spaces**, so seeding is a literal append under `toolkits:` with no re-indenting
step. The `# parrot:` header lines are metadata for `load_template()` and must
be stripped before the body is written. `{{repo_root}}` is the only
substitution the seeder performs.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/targeted-writer.yaml` (CREATE)
```yaml
# parrot:summary: Patch generation for work whose design is already decided in a TASK file.
# parrot:requires_llm: true
  targeted-writer:
    class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit
    # Seeded disabled: this toolkit needs a model you choose. Set `llm` to a
    # provider:model you have credentials for, add `llm_kwargs.fallback_model:
    # null` (the writer refuses a client that still permits a fallback), then
    # set `enabled: true` and re-run `parrot claude install`.
    enabled: false
    # llm: <provider:model>
    # llm_kwargs:
    #   fallback_model: null
    #   max_retries: 1
    #   read_timeout: 120
    kwargs:
      repo_root: {{repo_root}}
```
**Why this shape**: `_install_mcp_json` skips disabled sections
(`installer.py:365-366`), so a `requires_llm` template seeded with
`enabled: false` can never produce an `.mcp.json` entry for a server that
cannot start — that is AC "a `requires_llm` template is seeded disabled". Do
NOT ship a concrete `llm:` value: the model is operator-specific.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` (CREATE)
```yaml
# parrot:summary: FEAT-549 sdd-coder orchestration kernel (heterogeneous model seats).
# parrot:requires_llm: false
  sdd-coder:
    class: parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit
    # The roster is pure config. Seats whose credentials or CLI are missing are
    # dropped by the probe on the first `coder_plan` call and reported there:
    #   nova          -> BEDROCK_MANTLE_API_KEY / AWS_NOVA_API_KEY
    #   google-compat -> GEMINI_API_KEY / GOOGLE_API_KEY
    #   codex         -> the `codex` CLI's own login
    #   haiku         -> native Claude Code sub-agent, no credentials
    kwargs:
      roster:
        # FILL IN: the seat list — copy the roster from
        # `examples/sdd-coder-mcp.yaml` verbatim, minus any operator-specific
        # comment; bounded by AC "templates contain no credentials and no
        # operator-specific absolute path other than the rendered {{repo_root}}"
```
**Why this shape**: `SddCoderToolkit.__init__` requires `roster`
(`sdd_coder/toolkit.py:42-49`), so the section cannot be empty; the seat list
lives in `examples/sdd-coder-mcp.yaml` and is credential-free already, which is
why it is a copy rather than a decision.

### `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (CREATE)
```python
"""Seed `.parrot/mcp-toolkits.yaml` from packaged toolkit templates (FEAT-556, spec §3 M1)."""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TEMPLATE_PACKAGE: str = "parrot.mcp"
TEMPLATE_DIR: str = "_toolkit_templates"
REPO_ROOT_PLACEHOLDER: str = "{{repo_root}}"
_META_PREFIX: str = "# parrot:"


class ToolkitTemplate(BaseModel):
    """One packaged `.parrot/mcp-toolkits.yaml` section, ready to render."""

    name: str
    body: str
    requires_llm: bool = False
    summary: str = ""


class SeedResult(BaseModel):
    """Outcome of one seeding run."""

    created_file: bool = False
    added: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)


def available_templates() -> tuple[str, ...]:
    """Return the packaged template names (file stems), sorted."""
    # FILL IN: traverse files(TEMPLATE_PACKAGE) / TEMPLATE_DIR and collect
    # `.yaml` stems — bounded by AC "templates resolve from the installed wheel"


def load_template(name: str) -> ToolkitTemplate:
    """Read one packaged template.

    Raises:
        KeyError: no template named `name` ships with this wheel.
    """
    # FILL IN: read the resource, split the `# parrot:` metadata header from the
    # body, parse `summary` / `requires_llm` — bounded by the header format
    # fixed in the template blocks of this task


def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:
    """Create/extend `<root>/.parrot/mcp-toolkits.yaml` with the named sections.

    Creates the file with a `toolkits:` root when absent; appends only sections
    whose key is not already present (an existing section is NEVER rewritten);
    renders `REPO_ROOT_PLACEHOLDER` as `root`. Re-loads the result with
    `load_toolkits_config(root)` and raises if what it just wrote does not parse.

    Returns:
        SeedResult naming what was created, added, skipped and unknown.

    Raises:
        ValueError: the existing file is malformed, or the rendered result fails
            to re-load.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config  # local: keeps import cost off module load

    path = root / ".parrot" / "mcp-toolkits.yaml"
    result = SeedResult(created_file=not path.exists())
    # FILL IN: resolve requested names against available_templates() into
    # result.unknown; determine already-present section keys via
    # load_toolkits_config(root).toolkits MINUS BUILTIN names that the file does
    # not actually declare — bounded by AC "a pre-existing operator section
    # survives byte-identical"
    # FILL IN: ensure a `toolkits:` root exists (create the file with it, or
    # append to a file that lacks it), then append each new rendered body,
    # guaranteeing exactly one trailing newline per section
    # FILL IN: re-load with load_toolkits_config(root) and raise ValueError
    # naming `path` when the seeded names are not all present
    logger.info("seeded %s: added=%s skipped=%s", path, result.added, result.skipped)
    return result
```
**Why this shape**: the signatures are fixed by spec §3 Module 1 and are
consumed verbatim by TASK-3214/TASK-3215 — do not rename them or change the
return types. The "already present" test must distinguish a section the FILE
declares from a built-in that `load_toolkits_config` merges in
(`toolkit_config.py:143`), otherwise seeding `scraping` would look like a
no-op forever; that is why the FILL IN says "MINUS BUILTIN names the file does
not declare". The post-write re-load is what makes a corrupt append loud
instead of silent.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^"parrot.flows" = \["_rules_data/\*.md"\]' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `"parrot.flows" = ["_rules_data/*.md"]` (verified: packages/ai-parrot/pyproject.toml:907)
# FEAT-556: `parrot <host> install --toolkits` seeds .parrot/mcp-toolkits.yaml
# from these templates, read via importlib.resources — they MUST be in the wheel.
"parrot.mcp" = ["_toolkit_templates/*.yaml"]
```
**Why**: the templates are read with `importlib.resources`, so they only exist
at runtime if setuptools ships them; this mirrors the `parrot.flows` rules-data
entry two lines above.

### FILL IN checklist
- [ ] `_toolkit_templates/sdd-coder.yaml` — the roster seat list, copied from `examples/sdd-coder-mcp.yaml`; bounded by the no-credentials AC
- [ ] `toolkit_seed.available_templates` — resource traversal; bounded by "resolves from the installed wheel"
- [ ] `toolkit_seed.load_template` — metadata/body split per the fixed `# parrot:` header format
- [ ] `toolkit_seed.seed_toolkit_sections` — present-section detection (file-declared vs merged builtins), append, post-write validation; bounded by the byte-identical AC

---

## Acceptance Criteria

- [ ] `available_templates() == ("bounded-source", "sdd-coder", "targeted-writer")`
- [ ] `seed_toolkit_sections(tmp_root, ["sdd-coder"])` creates
      `.parrot/mcp-toolkits.yaml` with a `toolkits:` root and a `sdd-coder:`
      section; `SeedResult.created_file is True`
- [ ] Seeding over a file that already declares a section leaves that section
      byte-identical and reports it in `SeedResult.skipped`
- [ ] No `{{repo_root}}` survives in a seeded file
- [ ] `targeted-writer` is seeded with `enabled: false`
- [ ] A seeded file round-trips through `load_toolkits_config(root)` with the
      seeded names present
- [ ] An unknown name lands in `SeedResult.unknown` and does not raise
- [ ] Templates resolve via `importlib.resources.files("parrot.mcp")` (test must
      not read from the repository tree)
- [ ] All tests pass: `pytest tests/mcp/test_toolkit_seed.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_seed.py`
- [ ] Imports work: `from parrot.mcp.toolkit_seed import seed_toolkit_sections`

---

## Test Specification

```python
# tests/mcp/test_toolkit_seed.py
import pytest
import yaml

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import (
    SeedResult,
    available_templates,
    load_template,
    seed_toolkit_sections,
)


def test_available_templates_lists_packaged_names():
    assert set(available_templates()) == {"sdd-coder", "bounded-source", "targeted-writer"}


def test_templates_resolve_from_package_not_repo():
    """load_template must read package data, not a repo-relative path."""
    # FILL IN: assert via importlib.resources (e.g. files("parrot.mcp") traversal)
    # that the template is readable without reference to the repo tree


def test_seed_creates_yaml_when_absent(tmp_path):
    result = seed_toolkit_sections(tmp_path, ["bounded-source"])
    assert result.created_file is True
    data = yaml.safe_load((tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text())
    assert "bounded-source" in data["toolkits"]


def test_seed_appends_without_touching_existing_sections(tmp_path):
    # FILL IN: pre-write a file with an operator section, seed another name,
    # assert the operator section's text is unchanged and listed in .skipped


def test_seed_renders_repo_root_placeholder(tmp_path):
    seed_toolkit_sections(tmp_path, ["bounded-source"])
    text = (tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text()
    assert "{{repo_root}}" not in text and str(tmp_path) in text


def test_requires_llm_section_seeded_disabled(tmp_path):
    seed_toolkit_sections(tmp_path, ["targeted-writer"])
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits["targeted-writer"].enabled is False


def test_unknown_name_reported_not_raised(tmp_path):
    result = seed_toolkit_sections(tmp_path, ["bounded-source", "nope"])
    assert result.unknown == ["nope"] and "bounded-source" in result.added
```

---

## Agent Instructions

1. **Read the spec** §3 Module 1 and §7 before writing code.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-confirm `load_toolkits_config`'s
   signature and the `BUILTIN_TOOLKITS` membership before relying on them.
4. **Update status** in `sdd/tasks/index/claude-install-mcp-autoenable.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:` marker.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3211-toolkit-seed-templates.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
