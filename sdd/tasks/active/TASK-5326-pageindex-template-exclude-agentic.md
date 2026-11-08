# TASK-5326: Template hand-off — `exclude: [pageindex_agentic_retrieve]`

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5325
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 "Template hand-off", AC-13, AC-14. FEAT-842 (merged, PR #2029) left
`exclude: []` in the packaged `pageindex` template as the opt-in slot for the agentic tool.
This task lists `pageindex_agentic_retrieve` there and updates the FEAT-842 template test that
asserts the list is empty.

---

## Scope

- In `mcp/_toolkit_templates/pageindex.yaml` replace `    exclude: []` with
  `    exclude: [pageindex_agentic_retrieve]`, keeping the two comment lines above it
  (adjust their wording so they say: remove it from this list (and set `llm:`) to expose it).
- Mirror the same `exclude:` line in `examples/pageindex-mcp.yaml` (its test says the example mirrors the template).
- Update `tests/mcp/test_pageindex_template.py`: `test_template_seeds_repo_scoped_storage` asserts
  `section.exclude == ["pageindex_agentic_retrieve"]` (check the parsed type: list vs tuple);
  add `test_agentic_tool_excluded_by_default` (seeded section + fake llm → not served) and
  `test_agentic_tool_served_when_opted_in` (`_configure_section(tmp_path, llm="fake:model", exclude=[])` → served) — AC-13.

**NOT in scope**: any other file under `mcp/` (AC-14); wiki text (TASK-5327).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` | MODIFY | `exclude:` entry |
| `examples/pageindex-mcp.yaml` | MODIFY | mirror `exclude:` entry |
| `packages/ai-parrot/tests/mcp/test_pageindex_template.py` | MODIFY | updated + new assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in test_pageindex_template.py (:17-22)
from parrot.clients.base import AbstractClient
from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
```

### Existing Signatures to Use
```python
# tests/mcp/test_pageindex_template.py
def test_template_seeds_repo_scoped_storage(tmp_path)   # :39 — line :46 `assert not section.exclude`
def _configure_section(root: Path, **updates) -> None   # :194 — top-level keys merged into the section
def test_factory_serves_llm_tools_with_llm(tmp_path, monkeypatch)   # :232 — pattern: monkeypatch
#   "parrot.clients.factory.LLMFactory.create" -> MagicMock(spec=AbstractClient); server.tools is a mapping of names
# mcp/toolkit_server.py:353  exclude = overrides.get("exclude") or section.exclude
```
Template lines (`pageindex.yaml`): `:14-15` comments, `:16` `    exclude: []`. Example: `examples/pageindex-mcp.yaml:20` `    exclude: []`.

### Does NOT Exist
- ~~an `include:` list in the template~~ — do not add one.
- ~~a `requires_llm: true` change~~ — keep `# parrot:requires_llm: false` (`:2`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml", "action": "MODIFY"},
    {"path": "examples/pageindex-mcp.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_pageindex_template.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server"
  ]
}
```

---

## Implementation Notes

- Tool names in `server.tools` carry the `pageindex_` prefix (see `LLM_TOOLS` in the test file).
- `_configure_section(..., exclude=[])` sets the top-level key, which is what opts in.

---

## Implementation Blueprint

### Steps (in order)
1. Edit the template line and comments; mirror in the example.
2. Update/add tests; run the template test file.

### `pageindex.yaml` (MODIFY)
```yaml
# REPLACE `    exclude: []` (verified: pageindex.yaml:16) — occurrences: 1 (grep -cF '    exclude: []')
    # The internal agentic retrieval tool is opt-in: remove it from this list
    # (and set llm:) to expose pageindex_agentic_retrieve.
    exclude: [pageindex_agentic_retrieve]
```
(replace the existing two comment lines at :14-15 with the two above)

### `examples/pageindex-mcp.yaml` (MODIFY)
```yaml
# REPLACE `    exclude: []` (verified: examples/pageindex-mcp.yaml:20) — occurrences: 1
    exclude: [pageindex_agentic_retrieve]
```

### `test_pageindex_template.py` (MODIFY)
```python
# REPLACE `    assert not section.exclude` (verified: :46) — occurrences: 1
    assert list(section.exclude) == ["pageindex_agentic_retrieve"]

# APPEND after test_factory_serves_llm_tools_with_llm (:232-241)
def test_agentic_tool_excluded_by_default(tmp_path: Path, monkeypatch) -> None:
    """AC-13: the seeded template hides pageindex_agentic_retrieve even with an llm."""
    # FILL IN: fake LLMFactory.create as in :234-235; _configure_section(tmp_path, llm="fake:model");
    #          assert "pageindex_agentic_retrieve" not in server.tools


def test_agentic_tool_served_when_opted_in(tmp_path: Path, monkeypatch) -> None:
    """AC-13: removing it from exclude and setting llm serves it."""
    # FILL IN: _configure_section(tmp_path, llm="fake:model", exclude=[]); assert it is served
```

### FILL IN checklist
- [ ] two test bodies

---

## Acceptance Criteria

- [ ] AC-13; AC-14 (only the template line + comments change under `mcp/`).

## Validation Commands
- `pytest packages/ai-parrot/tests/mcp/test_pageindex_template.py -q`

---

## Test Specification

Spec AC-13.

---

## Agent Instructions

1. `ruff check --fix` the test file; run validation with `PYTHONPATH=packages/ai-parrot/src`.
2. Commit: `feat(pageindex-agentic-retrieval): TASK-5326 — exclude agentic tool by default`.

---

## Completion Note

*(Agent fills this in when done)*
