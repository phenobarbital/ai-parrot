# TASK-5317: Packaged `pageindex` toolkit template + example config

**Feature**: FEAT-842 — PageIndex Local MCP Toolkit
**Spec**: `sdd/specs/pageindex-local-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4**. The nine packaged templates under
`mcp/_toolkit_templates/` have no `pageindex.yaml`, so `parrot toolkits install pageindex`
has nothing to seed. This task adds the template (auto-discovered by
`available_templates()`), a standalone example config with `llm:` active, and the
template-metadata/seeding tests. It only adds files: the seeder, installer, runner and
host adapters stay unchanged (AC-12).

---

## Scope

- Create `mcp/_toolkit_templates/pageindex.yaml` with the exact content of spec §2 "Template (M4)".
- Create `examples/pageindex-mcp.yaml`: a full config (`toolkits:` root) with the same
  section and an active `llm:` line, servable with
  `parrot mcp-local pageindex --config examples/pageindex-mcp.yaml`.
- Create `tests/mcp/test_pageindex_template.py` with the metadata, seeding and example tests (AC-7).

**NOT in scope**: factory/stdio/two-writer/install tests (TASK-5318 appends them to the
same test file); any change to `toolkit_seed.py`, `toolkit_server.py`, `toolkit_install.py`,
`hosts.py`, `local_cli.py`; constructing `PageIndexToolkit` (it needs TASK-5314).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` | CREATE | packaged template |
| `examples/pageindex-mcp.yaml` | CREATE | standalone example with `llm:` active |
| `packages/ai-parrot/tests/mcp/test_pageindex_template.py` | CREATE | metadata + seeding + example tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `1db2685b95`. Paths relative to `packages/ai-parrot/src/parrot/`
> unless they start with `packages/` or `examples/`.

### Verified Imports
```python
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections, ToolkitTemplate  # mcp/toolkit_seed.py:53, :67, :335, :28
from parrot.mcp.toolkit_config import load_toolkits_config                                                       # mcp/toolkit_config.py:90
```

### Existing Signatures to Use
```python
# mcp/toolkit_seed.py
REPO_ROOT_PLACEHOLDER = "{{repo_root}}"                                  # :21
class ToolkitTemplate(BaseModel): name, body, requires_llm, summary, requires_dist, requires_pip, post_install, requires_env  # :28-38
class SeedResult(BaseModel): created_file, added, skipped, ...           # :41
def available_templates() -> tuple[str, ...]                             # :53 (sorted .yaml stems of _toolkit_templates/)
def load_template(name: str) -> ToolkitTemplate                          # :67; header parser :96-121:
#   "# parrot:" prefix lines until the first other line; summary:, requires_llm: (== "true"),
#   requires_dist: (comma split -> tuple), requires_pip: (repeatable, ONE requirement per line, no comma split)
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult   # :335; writes <root>/.parrot/mcp-toolkits.yaml, renders {{repo_root}}

# mcp/toolkit_config.py
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig   # :90
class ToolkitSection(BaseModel): class_path (alias "class"), enabled, kwargs, include, exclude, llm, llm_kwargs, env   # :20-59
```

Sibling template shape (`mcp/_toolkit_templates/bounded-source.yaml`, verbatim):
```yaml
# parrot:summary: Bounded source reading — large files require an explicit line range.
# parrot:requires_llm: false
  bounded-source:
    class: parrot.tools.optimizations.reader.BoundedSourceToolkit
    kwargs:
      repo_root: {{repo_root}}
```
Test patterns: `tests/mcp/test_lsp_template.py:28-61` (template + seed, `_EXAMPLE_PATH =
Path(__file__).resolve().parents[4] / "examples" / "lsp-mcp.yaml"` at :26);
`tests/mcp/test_toolkit_seed_install_metadata.py:100-113` (per-template metadata asserts).
`packages/ai-parrot/pyproject.toml:368-372` — `bookstore` extra = `bm25s`, `pymupdf`, `pymupdf4llm`.

### Does NOT Exist
- ~~`mcp/_toolkit_templates/pageindex.yaml`~~, ~~`examples/pageindex-mcp.yaml`~~, ~~`tests/mcp/test_pageindex_template.py`~~ — created here
- ~~an `enabled:` key in templates~~ — templates seed it absent (`_DRIFT_IGNORED_KEYS`)
- ~~`ToolkitSection.storage_dir`~~ / ~~`ToolkitSection.repo_root`~~ — paths live under `kwargs`
- ~~an agentic retrieval tool~~ — `exclude: []` is an empty slot, not a reference

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml", "action": "CREATE"},
    {"path": "examples/pageindex-mcp.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/mcp/test_pageindex_template.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#load_template",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the template verbatim — *why*: its content is fixed by spec §2 and asserted by AC-7.
2. Write the example — *why*: operators copy it to enable the LLM-dependent tools.
3. Write the tests — *why*: AC-7, and `test_every_shipped_template_still_loads` picks the template up automatically.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` (CREATE)
```yaml
# parrot:summary: PageIndex document trees — per-repository search, read and edit over stdio.
# parrot:requires_llm: false
# parrot:requires_dist: bm25s,pymupdf
# parrot:requires_pip: ai-parrot[bookstore]
  pageindex:
    class: parrot.knowledge.pageindex.toolkit.PageIndexToolkit
    kwargs:
      storage_dir: {{repo_root}}/.parrot/pageindex
      max_result_chars: 24000
    # Add a model to enable the LLM-dependent tools (import_pdf, insert_content,
    # import_file, import_folder, search_documents_scoped) and the LLM tree walk.
    # llm: anthropic:claude-haiku-5-5
    # llm_kwargs: {}
    # The internal agentic retrieval tool (pageindex-agentic-retrieval) is opt-in:
    # remove it from this list to expose it.
    exclude: []
    env: {}
```
**Why**: two-space body indent because the seeder splices it under `toolkits:`. The empty
`exclude: []` is falsy for the factory's `elif exclude:` branch, so it changes nothing
today; it is the agreed hand-off slot. No `enabled:` key.

### `examples/pageindex-mcp.yaml` (CREATE)
```yaml
# FEAT-842 — PageIndex as a local MCP toolkit, with an LLM configured.
#
# Full guidance: wiki/knowledge/pageindex-local-mcp.md.
# Without `llm:` the server is deterministic (BM25 search, markdown/ebook ingest,
# node edits, bounded retrieve); with it, the five LLM-dependent tools appear.
#
# Serve with:
#     parrot mcp-local pageindex --config examples/pageindex-mcp.yaml
toolkits:
  pageindex:
    class: parrot.knowledge.pageindex.toolkit.PageIndexToolkit
    kwargs:
      storage_dir: .parrot/pageindex
      max_result_chars: 24000
    llm: anthropic:claude-haiku-5-5
    llm_kwargs: {}
    exclude: []
    env: {}
```
**Why**: a standalone file cannot use `{{repo_root}}` (only the seeder renders it), so the
storage path is relative to the server's working directory. FILL IN: confirm a relative
`storage_dir` is resolved against the cwd by `JSONTreeStore` (`Path(storage_dir)`,
store.py:31-33) — if a relative path is wrong for `mcp-local`, use an absolute
placeholder comment instead and say so in the Completion Note.

### `packages/ai-parrot/tests/mcp/test_pageindex_template.py` (CREATE)
```python
"""Packaged `pageindex` toolkit template and example (FEAT-842 M4/M5)."""

from __future__ import annotations

from pathlib import Path

import yaml

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections

_EXAMPLE_PATH = Path(__file__).resolve().parents[4] / "examples" / "pageindex-mcp.yaml"
_CLASS = "parrot.knowledge.pageindex.toolkit.PageIndexToolkit"


def test_template_metadata() -> None:
    """AC-7: requires_llm False, requires_dist (bm25s, pymupdf), requires_pip (ai-parrot[bookstore],)."""
    assert "pageindex" in available_templates()
    tpl = load_template("pageindex")
    assert tpl.requires_llm is False
    assert tpl.requires_dist == ("bm25s", "pymupdf")
    assert tpl.requires_pip == ("ai-parrot[bookstore]",)
    assert "{{repo_root}}" in tpl.body
    assert f"class: {_CLASS}" in tpl.body


def test_template_seeds_repo_scoped_storage(tmp_path: Path) -> None:
    """AC-7: seeding renders storage_dir under <root>/.parrot/pageindex with max_result_chars 24000."""
    result = seed_toolkit_sections(tmp_path, ["pageindex"])
    assert result.added == ["pageindex"]
    # FILL IN: section = load_toolkits_config(tmp_path).toolkits["pageindex"];
    #   section.class_path == _CLASS; section.llm is None; section.exclude == [] (or falsy);
    #   section.kwargs["storage_dir"] == f"{tmp_path}/.parrot/pageindex"; section.kwargs["max_result_chars"] == 24000;
    #   "{{repo_root}}" not in the written .parrot/mcp-toolkits.yaml


def test_example_mirrors_template_with_llm() -> None:
    """The example is a standalone config with the same class and an active llm line."""
    assert _EXAMPLE_PATH.is_file()
    # FILL IN: yaml.safe_load(...)["toolkits"]["pageindex"] has class == _CLASS, a non-empty "llm",
    #   kwargs.max_result_chars == 24000; and load_toolkits_config(_EXAMPLE_PATH.parent, config_path=_EXAMPLE_PATH)
    #   parses it (section.llm is set)
```
**Why**: copies the `test_lsp_template.py` structure so the two templates are tested the same way.

### FILL IN checklist
- [ ] example `storage_dir` resolution check — bounded by store.py:31-33
- [ ] `test_template_seeds_repo_scoped_storage` asserts — bounded by AC-7
- [ ] `test_example_mirrors_template_with_llm` asserts — bounded by spec §2 (example mirrors the section with `llm:` active)

---

## Acceptance Criteria

- [ ] AC-7 `load_template("pageindex")` has `requires_llm False`, `requires_dist ("bm25s","pymupdf")`, `requires_pip ("ai-parrot[bookstore]",)`; `seed_toolkit_sections` writes a `pageindex:` section whose `storage_dir` is `<root>/.parrot/pageindex` and `max_result_chars` is 24000; `test_every_shipped_template_still_loads` passes.
- [ ] AC-12 (partial) no diff in `mcp/toolkit_server.py`, `toolkit_seed.py`, `toolkit_install.py`, `hosts.py`, `local_cli.py`.
- [ ] `ruff check` clean on the test file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_pageindex_template.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_lsp_template.py -q`

---

## Test Specification

See the CREATE block for `test_pageindex_template.py` above.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug pageindex-local-mcp-toolkit --feature-id FEAT-842`).
2. Mark `in-progress` in the per-spec index; commit only the index.
3. Write the three files; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit the three files; `parrot sdd task close TASK-5317 pageindex-local-mcp-toolkit verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
