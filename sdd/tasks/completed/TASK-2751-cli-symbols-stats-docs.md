# TASK-2751: `wikitoolkit symbols` CLI group, `stats` symbol counts, docs and CLAUDE.md section

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2750
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9. Human/script surface over the same `StructuralService`,
operational visibility (`stats`), and documentation of the extra, the
migration, and the three tools.

---

## Scope

- `cli.py`: new `@wiki.group(name="symbols")` with commands `lookup <query>
  [--kind] [--language] [--path] [--limit] [--json]`, `outline <target>
  [--depth] [--source]`, `blast <symbol> [--rel …] [--depth] [--no-inferred]
  [--no-tests] [--json]`. Open store/config exactly as `create_wiki_mcp_server`
  does (reuse a shared helper if one exists in `cli.py`; otherwise factor
  `_open_read_store(root)` used by both). Human output = the tools' text
  rendering; `--json` = the Pydantic dict.
- `stats` command: add `symbols: N` and a `structural:` block with the mode
  per language (`all_scanners()[name].mode` after a probe, or the last mode
  recorded during the build — pick what the existing `languages` stats block
  does, see `test_polyglot_integration.py::test_stats_languages_block`).
- Docs: `docs/llm-wiki.md` (install `ai-parrot[wiki-structural]`, what `sym:`
  pages are, migration note: first `build` after upgrade populates symbols,
  old pages untouched, three tools + CLI examples); `docs/wiki-claude-code.md`
  (the three MCP tools, when to prefer `wiki_symbol_lookup` over `wiki_query`).
- `claude_code/assets.py::CLAUDE_MD_SECTION`: one short paragraph on symbol
  lookup / blast radius (installer tests must still pass — the section is
  marker-delimited).
- Tests: `test_cli.py` additions using `CliRunner` (`lookup --json`, `outline`,
  `blast`), `stats` shows `symbols` and `structural`.

**NOT in scope**: dev_loop, `ast_grep`/`ast_edit`, Codex/Gemini installers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `symbols` group; `stats` additions |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `CLAUDE_MD_SECTION` paragraph (:186-260) |
| `docs/llm-wiki.md` | MODIFY | Extra, migration, tools, CLI |
| `docs/wiki-claude-code.md` | MODIFY | MCP tools guidance |
| `tests/knowledge/wiki/test_cli_symbols.py` | CREATE | CLI tests |
| `tests/knowledge/wiki/test_cli.py` | MODIFY | `stats` assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki                                       # cli.py:1071 — @click.group(name="wiki"); entry point `wikitoolkit`
from parrot.knowledge.wiki.structural.service import StructuralService            # TASK-2749
from parrot.knowledge.wiki.structural.tools import create_structural_tools        # TASK-2750
from parrot.knowledge.wiki.project import load_effective_config, find_project_root   # project.py:813/625
from parrot.knowledge.wiki.languages import all_scanners                          # languages/__init__.py:58
from parrot.knowledge.wiki.claude_code.assets import CLAUDE_MD_SECTION, CLAUDE_MD_BEGIN, CLAUDE_MD_END   # assets.py:186/23/24
```

### Existing Signatures to Use
```python
# cli.py
@click.group(name="wiki")            # :1071 ; sub-groups precedent: @wiki.group(name="ns") :1918, @wiki.group(name="sync") :3001
def build(...)                       # :1144 ; def upsert(...) :1389 ; `stats` command — locate with grep -n 'name="stats"' before editing
# mcp_server.py:90-140 — store/config opening sequence (load_effective_config(root).config → storage_path → create_wiki_store(... backend/arango params) → FederatedWikiStore)
# assets.py: CLAUDE_MD_BEGIN/END markers :23-24 ; CLAUDE_MD_SECTION f-string :186 ; installer tests: tests/knowledge/wiki/test_claude_code.py
# tests/knowledge/wiki/test_cli.py — CliRunner usage precedent ; tests/knowledge/wiki/languages/test_polyglot_integration.py:94 test_stats_languages_block
# docs: docs/llm-wiki.md, docs/wiki-claude-code.md exist (verified `ls docs`)
```

### Does NOT Exist
- ~~`wikitoolkit symbols` group~~ — created here.
- ~~`docs/wiki/` directory~~ — the docs are flat files `docs/llm-wiki.md` and `docs/wiki-claude-code.md`.
- ~~a `structural:` block in `stats` today~~ — only `languages` exists; add beside it.
- ~~any `ast_edit` CLI~~ — out of scope.

---

## Implementation Notes

- Commands are thin: parse args → `StructuralService` call via `_run_sync`
  (see `mcp_server._run_sync` :67 for the loop helper; cli likely has its own
  `asyncio.run` wrapper — reuse it) → print.
- `--json` output must be `json.dumps(model.model_dump(), indent=2)`.
- Keep `stats` backwards compatible (existing keys unchanged).
- Docs: state plainly that nothing changes for installs without the extra
  except Python `sym:` pages and `content_hash`.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/test_cli_symbols.py tests/knowledge/wiki/test_cli.py tests/knowledge/wiki/test_claude_code.py -v` passes.
- [ ] `wikitoolkit symbols lookup helper --json` prints a `SymbolLookupOutput` dict; `outline` and `blast` work on a built fixture plane.
- [ ] `wikitoolkit stats` shows `symbols` and per-language `structural` mode.
- [ ] Docs updated in both files; `CLAUDE_MD_SECTION` mentions symbol lookup; installer round-trip tests still pass.
- [ ] `ruff` clean.

---

## Test Specification

```python
def test_symbols_lookup_json(built_project_root):
    r = CliRunner().invoke(wiki, ["symbols", "lookup", "helper", "--json"], env={"PARROT_WIKI_ROOT": str(built_project_root)})  # verify how existing cli tests pass the root (cwd vs option) and mirror it
    assert r.exit_code == 0 and json.loads(r.output)["hits"][0]["qualname"] == "helper"
```

---

## Agent Instructions

1. Read spec §3 Module 9 and AC19. 2. Confirm TASK-2750 completed. 3. Locate
the `stats` command and the root-resolution pattern in `test_cli.py`.
4. Index → `in-progress`. 5. Implement. 6. Tests. 7. Move to `completed/`.
8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-02
**Notes**: Added `@wiki.group(name="symbols")` with `lookup`/`outline`/
`blast` subcommands. Each subcommand resolves the project + opens the
built store (`_resolve_project` + `_require_built`, same as every other
read command), builds the three structural tools via
`create_structural_tools`, and calls the matching tool's `_execute()`
directly — so CLI text output is byte-identical to the MCP tools' own
rendering (`_echo_structural_result` just pops the tool's `"text"` key
for the human path, or dumps the rest as JSON for `--json`), fulfilling
"Human output = the tools' text rendering; --json = the Pydantic dict"
exactly. `status` (the actual command backing every "stats" reference in
this task and its own spec module — there is no separate `stats`
command; confirmed via `test_polyglot_integration.py::
test_stats_languages_block`'s docstring) gained an additive
`"structural"` payload key (same `{name: mode}` mapping as the existing
`"languages"` key, kept unchanged for backward compatibility) and now
prints `symbols`/`Structural` in its human-readable output;
`stats.symbols` itself already existed since TASK-2747's `store.stats()`
addition. `CLAUDE_MD_SECTION` gained one paragraph on symbol lookup/
outline/blast radius. `docs/wiki-claude-code.md` gained three CLI
reference rows plus a "Symbols — the structural plane" section (install
note, three tools, migration note); `docs/llm-wiki.md` (a different,
older PageIndex/GraphIndex/Ontology example doc, not actually about the
`wikitoolkit` CLI) got a short bridging paragraph + cross-reference,
since a full rewrite of that doc is out of this task's scope. 18 new/
updated tests across `test_cli_symbols.py` (new) and `test_cli.py`/
`test_claude_code.py` (additive assertions); full targeted suite +
installer round-trip pass. `ruff` clean on every file I touched (verified
`cli.py`'s 3 pre-existing findings — F821 `Optional`, SIM102, ISC004 —
are untouched by my diff via `git stash` comparison). `mypy` on `cli.py`:
identical pre-existing error SET before/after my change (verified by
diffing `stash`-vs-working-tree mypy output — the errors merely shift
line numbers by the +135 lines I inserted; zero new errors).

**Deviations from spec**: none beyond the two clarifications noted above
(the `stats`→`status` naming, and the `docs/llm-wiki.md` scope), both
already resolved via the codebase evidence cited.
