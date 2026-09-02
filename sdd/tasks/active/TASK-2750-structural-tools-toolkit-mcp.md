# TASK-2750: Structural tools, `CodeStructuralToolkit`, MCP registration, permissions, `wiki_query` opt-in

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2749
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. Two surfaces over one `StructuralService`: three
`AbstractTool`s for `wikitoolkit mcp` (resolved names `wiki_symbol_lookup`,
`wiki_code_outline`, `wiki_blast_radius`) and a `CodeStructuralToolkit`
(`tool_prefix="code"` → `code_symbol_lookup`, `code_outline`,
`code_blast_radius`). `wiki_query` gains `include_symbols` (default `False`,
resolved). Permission rules list the three MCP tool names.

---

## Scope

- Create `structural/tools.py`: input models `SymbolLookupInput`,
  `CodeOutlineInput`, `BlastRadiusInput` (spec §2, all with `namespace: str | None`),
  tools `WikiSymbolLookupTool`, `WikiCodeOutlineTool`, `WikiBlastRadiusTool`
  following `WikiQueryTool`'s shape (`name`, `description`, `args_schema`,
  `__init__(self, service_factory)`, `async _execute(...)`), `namespace`
  handled via `_scoped_store()`; read-repair only when the scoped store is
  the local one. Output = compact text rendering of the Pydantic result
  (`stub_line`-style lines + JSON tail under a token budget via
  `truncate_to_tokens`), plus `ToolResult.result` carrying the model dict.
  `create_structural_tools(store, root, config) -> list[AbstractTool]`.
- Create `structural/toolkit.py::CodeStructuralToolkit(AbstractToolkit)`:
  `tool_prefix = "code"`, constructor `(root: Path | None = None, store=None,
  config=None)` resolving via `find_project_root`/`load_effective_config`
  when not given; public async methods `symbol_lookup`, `outline`,
  `blast_radius` delegating to one `StructuralService`; docstrings become
  tool descriptions.
- `mcp_server.create_wiki_mcp_server()`: after `create_wiki_tools`, register
  `create_structural_tools(read_store, root, config)`; description mentions
  symbols.
- `tools.py`: `WikiQueryInput.include_symbols: bool = False`; `WikiQueryTool._execute`
  over-fetches (`limit*3`, via `search_fts(question, limit=…)`) and drops
  `category == "symbol"` unless `include_symbols`.
- `claude_code/assets.py::PERMISSION_RULES` += the three
  `mcp__wikitoolkit__wiki_*` names (single additive hunk — FEAT-495 shares
  this file).
- Tests: tool names/schemas, MCP registration (nine tools), toolkit prefix,
  `wiki_query` exclusion, permission rules, a read-only assertion (tree
  snapshot unchanged after each tool call — spec AC14).

**NOT in scope**: CLI, docs, `confirm` gating (no destructive tool here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | CREATE | Three tools + factory |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py` | CREATE | `CodeStructuralToolkit` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py` | MODIFY | Re-exports |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | Register structural tools (:90-190) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `include_symbols` (:96-101, :175-188) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `PERMISSION_RULES` (:47-52) |
| `tests/knowledge/wiki/structural/test_tools.py` | CREATE | Tools + toolkit tests |
| `tests/knowledge/wiki/test_mcp_server_structural.py` | CREATE | Nine tools registered; stdio round-trip |
| `tests/knowledge/wiki/test_claude_code.py` | MODIFY | Permission rules include the new names |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool, ToolResult                     # tools/abstract.py:281 / :250
from parrot.tools.toolkit import AbstractToolkit                               # tools/toolkit.py:206
from parrot.knowledge.wiki.tools import create_wiki_tools, WikiQueryTool, WikiQueryInput, _scoped_store, _unknown_namespace_error   # tools.py:541/155/96/23/79
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server            # mcp_server.py:90
from parrot.knowledge.wiki.context import pack_results, truncate_to_tokens, stub_line, DEFAULT_BUDGET_TOKENS   # context.py:203/272/154/108
from parrot.knowledge.wiki.project import load_effective_config, find_project_root, WikiProjectConfig   # project.py:813/625/~400
from parrot.knowledge.wiki.structural.service import StructuralService         # TASK-2749
from parrot.knowledge.wiki.claude_code.assets import PERMISSION_RULES, permission_rules   # assets.py:47 / :169
from parrot.mcp.local_server import StdioMCPServer                             # mcp/local_server.py:36
```

### Existing Signatures to Use
```python
# tools.py:155 — the tool shape to copy
class WikiQueryTool(AbstractTool):
    name = "wiki_query"; description = "…"; args_schema = WikiQueryInput
    def __init__(self, store: BaseWikiStore): super().__init__(name=self.name, description=self.description); self._store = store   # :171-173
    async def _execute(self, question: str, budget_tokens: int = DEFAULT_BUDGET_TOKENS, namespace: str | None = None) -> str:   # :175
        store = _scoped_store(self._store, namespace)  (KeyError → _unknown_namespace_error)   # :181-184
        results = await store.search_fts(question); packed = pack_results(results, budget_tokens=budget_tokens); return packed.text   # :185-188
class WikiQueryInput(BaseModel): question: str; budget_tokens: int = DEFAULT_BUDGET_TOKENS; namespace: str | None   # :96-99
def create_wiki_tools(store, root=None, config=None) -> list[AbstractTool]   # :541

# mcp_server.py:90 create_wiki_mcp_server(root) -> StdioMCPServer
#   config = load_effective_config(root).config ; store = create_wiki_store(...) ; read_store = FederatedWikiStore(...) or store
#   tools = create_wiki_tools(read_store, root=root, config=config) ; server = StdioMCPServer(LocalServerConfig(name="wikitoolkit", ...)) ; server.register_tools(tools)

# tools/toolkit.py:206 AbstractToolkit — tool_prefix :257 ; names = f"{tool_prefix}{prefix_separator}{method}" (:521-577) ; public `async def` methods become tools ; confirming_tools :275 (not needed)
# toolkit.py:54 LLMWikiToolkit(AbstractToolkit) with tool_prefix = "wiki" (:81) — constructor/resolution style to mirror
# assets.py:47 PERMISSION_RULES: tuple[str, ...] = ("Bash(wikitoolkit:*)", "Bash(parrot wiki:*)", "Bash(source .venv/bin/activate && wikitoolkit:*)", "Bash(source .venv/bin/activate && parrot wiki:*)")
# tests/knowledge/wiki/test_mcp_server_namespaces.py (packages/ai-parrot/tests/…) — precedent for asserting registered tool names on the server
```

### Does NOT Exist
- ~~`structural/tools.py`, `structural/toolkit.py`, `create_structural_tools`, `CodeStructuralToolkit`~~ — created here.
- ~~`WikiQueryInput.include_symbols`~~ — added here.
- ~~`search_fts(exclude_category=…)`~~ — do not add; filter in the tool.
- ~~tool names `symbol_lookup` / `code_outline` / `blast_radius` without `wiki_`~~ — resolved against; MCP names carry `wiki_`.
- ~~`code_code_outline`~~ — toolkit method is `outline` so the derived name is `code_outline`.
- ~~`routing_meta["requires_confirmation"]` on these tools~~ — all read-only; do not set.
- ~~`mcp__wikitoolkit__*` entries in `PERMISSION_RULES` today~~ — none exist; add exactly three.

---

## Implementation Notes

- Tool text output: header line per hit using `stub_line`-like formatting
  (`[sym:<rel>#<q>] — <kind> L<start>-<end>: <doc>`), then `files:` line for
  blast radius; total capped via `truncate_to_tokens(text, budget)`. Return
  the Pydantic dict as `ToolResult.result` so MCP clients can parse it.
- `service_factory`/lazy construction: build one `StructuralService` per
  (store, root, config) and share it between the three tools and the toolkit.
- Namespace: when `namespace` names a foreign store, skip read-repair
  (service flag `allow_repair=False`).
- `CodeStructuralToolkit` docstrings: first line becomes the LLM-facing
  description — write them for an agent reader.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/structural/test_tools.py tests/knowledge/wiki/test_mcp_server_structural.py tests/knowledge/wiki/test_claude_code.py tests/knowledge/wiki/test_toolkit.py -v` passes.
- [ ] `create_wiki_mcp_server(root)` registers nine tools; the three new names are exactly `wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius`; `args_schema` fields match spec §2.
- [ ] `CodeStructuralToolkit().get_tools()` names are `code_symbol_lookup`, `code_outline`, `code_blast_radius` and share one service instance.
- [ ] `wiki_query` hides `sym:` stubs by default and shows them with `include_symbols=True`; `limit`/budget still honoured.
- [ ] `PERMISSION_RULES` contains the three `mcp__wikitoolkit__wiki_*` entries; existing `test_claude_code.py` still passes.
- [ ] Read-only: a fixture-tree snapshot (paths + hashes, excluding `.parrot/`) is identical before/after each tool call.
- [ ] `ruff` / `mypy` clean; docstrings on all tools/methods.

---

## Test Specification

```python
def test_mcp_server_registers_structural_tools(built_project_root):
    server = create_wiki_mcp_server(built_project_root)
    names = {t.name for t in server.tools}   # verify the accessor name on StdioMCPServer/LocalMCPServerBase before use
    assert {"wiki_symbol_lookup", "wiki_code_outline", "wiki_blast_radius"} <= names and len(names) == 9

def test_toolkit_names():
    tk = CodeStructuralToolkit(root=ROOT)
    assert sorted(t.name for t in tk.get_tools_sync()) == ["code_blast_radius", "code_outline", "code_symbol_lookup"]
```

---

## Agent Instructions

1. Read spec §2 ("Service & tools", New Public Interfaces), §3 Module 8, §7
"Toolkit naming". 2. Confirm TASK-2749 completed. 3. Verify contract lines and
the `StdioMCPServer` tool accessor. 4. Index → `in-progress`. 5. Implement tools
→ toolkit → MCP → wiki_query → permissions. 6. Tests. 7. Move to `completed/`.
8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
