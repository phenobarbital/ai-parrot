# TASK-2645: `.parrot/mcp-toolkits.yaml` config models, loader, built-in defaults

**Feature**: FEAT-485 — Expose Toolkits as Local MCP
**Spec**: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The per-toolkit MCP runner and both installers read one
project config: `.parrot/mcp-toolkits.yaml`. Three built-in sections
(`scraping`, `browsing`, `memory`) must work with **no file at all**; the
file overrides built-ins and adds arbitrary toolkits (the extensibility
door).

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` with:
  - `ToolkitSection(BaseModel)`: `class_path` (alias `"class"`, required in
    file sections), `enabled: bool = True`, `kwargs: dict = {}`,
    `include: Optional[list[str]] = None`, `exclude: Optional[list[str]] = None`,
    `llm: Optional[str] = None`, `env: dict[str, str] = {}`.
  - `MCPToolkitsConfig(BaseModel)`: `toolkits: dict[str, ToolkitSection]`.
  - `BUILTIN_TOOLKITS: dict[str, ToolkitSection]` — defaults:
    - `scraping` → `parrot_tools.scraping.toolkit.WebScrapingToolkit`,
      kwargs `{headless: true, plans_dir: ".parrot/scraping_plans"}`
    - `browsing` → `parrot_tools.browsing.toolkit.WebBrowsingToolkit`,
      kwargs `{catalog_dir: ".parrot/browsing_catalog", headless: true}`
    - `memory` → `parrot.tools.working_memory.tool.WorkingMemoryToolkit`,
      kwargs `{}`
  - `load_toolkits_config(root: Path) -> MCPToolkitsConfig`: read
    `<root>/.parrot/mcp-toolkits.yaml` if present, deep-merge sections over
    `BUILTIN_TOOLKITS` (file wins per-key: a file section's `kwargs`
    replaces the builtin `kwargs` dict wholesale — document this), validate
    via Pydantic, raise errors that NAME the file path and the offending
    section/key.
- Unit tests.

**NOT in scope**: importing/instantiating toolkit classes (TASK-2646);
CLI (TASK-2647); installer entry generation (TASK-2648/2649).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` | CREATE | models + defaults + loader |
| `tests/mcp/test_toolkit_config.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import yaml                      # PyYAML — existing dependency across the repo
from pydantic import BaseModel, Field
# Dotted default paths that MUST be used verbatim in BUILTIN_TOOLKITS:
#   parrot_tools.scraping.toolkit.WebScrapingToolkit   (scraping/toolkit.py:274)
#   parrot_tools.browsing.toolkit.WebBrowsingToolkit   (browsing/toolkit.py:64)
#   parrot.tools.working_memory.tool.WorkingMemoryToolkit  (tool.py:44)
```

### Existing Signatures to Use
```python
# The loader must NOT import the toolkit classes — it only carries dotted
# strings. Class resolution happens in toolkit_server (TASK-2646).

# Filename constraint — parrot.mcp is a PEP 420 namespace merged with
# ai-parrot-server. Server-owned filenames that must NOT be created in core:
#   cli.py, server.py, config.py, wrapper.py, parrot_server.py,
#   simple_server.py, chrome.py, oauth_server.py
# → this module is toolkit_config.py precisely to avoid config.py.
```

### Does NOT Exist
- ~~`.parrot/mcp-toolkits.yaml`~~ — no example exists yet anywhere; this
  task defines the format (docs ship in TASK-2650).
- ~~`parrot/mcp/config.py` in core~~ — FORBIDDEN filename (server collision).
- ~~`parrot.tools.working_memory.WorkingMemoryToolkit`~~ (package-level) —
  verify before relying on package re-export; the verified path is
  `parrot.tools.working_memory.tool.WorkingMemoryToolkit`.
- ~~an existing YAML-with-kwargs format~~ — the server's `parrot mcp serve`
  YAML supports only `{class: module}` pairs (ai-parrot-server
  `parrot/mcp/cli.py:122-126`); do not imitate it.

---

## Implementation Notes

### Key Constraints
- Pydantic models, Google-style docstrings, strict type hints.
- `include`+`exclude` may coexist in the model; precedence (include wins)
  is enforced by the consumer (TASK-2646) but MUST be documented in the
  `ToolkitSection` docstring.
- Use `Field(alias="class")` and `model_config = ConfigDict(populate_by_name=True)`
  so Python callers can also pass `class_path=`.
- Missing file → return builtins only. Empty/None YAML document → same.
- Unknown top-level keys or non-mapping `toolkits:` → `ValueError` naming
  the file.

---

## Acceptance Criteria

- [ ] `load_toolkits_config(root)` with no file returns exactly the 3 builtins
- [ ] File section for a builtin name overrides it (kwargs replaced wholesale)
- [ ] New file sections are appended with their dotted `class` path
- [ ] Malformed YAML → error naming the path and problem
- [ ] `enabled: false` sections are retained in the model (consumers filter)
- [ ] Tests pass: `pytest tests/mcp/test_toolkit_config.py -v`
- [ ] `ruff check` clean; module imports without ai-parrot-server installed

---

## Test Specification

```python
# tests/mcp/test_toolkit_config.py
from pathlib import Path
import pytest
from parrot.mcp.toolkit_config import (
    BUILTIN_TOOLKITS, MCPToolkitsConfig, ToolkitSection, load_toolkits_config,
)


def test_no_file_returns_builtins(tmp_path):
    cfg = load_toolkits_config(tmp_path)
    assert set(cfg.toolkits) == {"scraping", "browsing", "memory"}


def test_file_overrides_builtin(tmp_path):
    p = tmp_path / ".parrot"; p.mkdir()
    (p / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  memory:\n    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit\n    kwargs: {max_rows: 25}\n"
    )
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits["memory"].kwargs == {"max_rows": 25}


def test_new_section_added(tmp_path):
    ...  # custom section with dotted class path appears alongside builtins


def test_bad_yaml_named_error(tmp_path):
    ...  # error message contains the file path
```

---

## Agent Instructions

1. **Read the spec** for full context (§2 Data Models is the source of truth)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/expose-toolkits-as-local-mcp.json` → `"in-progress"`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index** → `"done"`, **fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
