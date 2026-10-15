# TASK-3268: Import-ceiling integration gate (FEAT-540 acceptance)

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3256, TASK-3257, TASK-3258, TASK-3259, TASK-3260, TASK-3261, TASK-3262, TASK-3263, TASK-3264, TASK-3265, TASK-3266, TASK-3267
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests" and §5 "Acceptance Criteria". Every earlier FEAT-540
task landed one seam and flipped at most its own ceiling case. This task is the
objective gate: it activates every remaining import-ceiling assertion (the
`xfail` marks left in `test_import_ceilings.py` by TASK-3256/3257), adds the
AST scan that proves goal G3, adds the three end-to-end regression tests
(build parity, plane backward-readability, agent path), and walks the full §5
checklist. **It fixes nothing by raising a ceiling**: if a ceiling fails, the
task reports the offending import chain and escalates.

---

## Scope

- Remove every `pytest.mark.xfail` from `packages/ai-parrot/tests/knowledge/test_import_ceilings.py`
  (created by TASK-3256) so all five ceilings + the forbidden-package list are hard assertions.
- Create `packages/ai-parrot/tests/knowledge/test_no_framework_imports_in_graph_tree.py`
  (`test_no_framework_imports_in_graph_tree`, spec §4).
- Create `packages/ai-parrot/tests/knowledge/wiki/test_feat540_integration.py` with
  `test_wikitoolkit_build_end_to_end`, `test_wiki_plane_backward_readable`, and a CLI-surface test.
- Create committed fixtures under `packages/ai-parrot/tests/knowledge/wiki/fixtures/pre_feat540/`
  (tiny repo, `wiki.db` built by pre-FEAT-540 code, `expected_stats.json`).
- Create `packages/ai-parrot-tools/tests/wiki/test_agent_path_unchanged.py` (`test_agent_path_unchanged`, spec §4).
- Run every §5 acceptance criterion and record results (log to `artifacts/logs/feat540-gate.md`).

**NOT in scope**:
- Changing production code to meet a ceiling. If one fails: `python -X importtime -c "import <mod>" 2>&1 | sort -t'|' -k2 -n | tail -40`,
  identify the first heavy gateway, write it in the Completion Note, and ESCALATE (do not edit ceilings, do not fix in this task).
- Module-level imports the spec's banned list does not cover and that are out of scope for FEAT-540
  (record only): `graphindex/pg_schema.py:20` navconfig + `:23` parrot.conf (the `[postgres]` plane, imports asyncpg anyway);
  `wiki/claude_code/cli.py:26` parrot.mcp; `wiki/jira_render.py:32`, `wiki/jira_sync.py:38` parrot.interfaces.jira;
  `wiki/vault_scan.py:33-35` parrot.interfaces.obsidian (FEAT-541 and later).
- Extras / dependency list changes (FEAT-541).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` | MODIFY | drop all xfail marks |
| `packages/ai-parrot/tests/knowledge/test_no_framework_imports_in_graph_tree.py` | CREATE | AST scan (G3) |
| `packages/ai-parrot/tests/knowledge/wiki/test_feat540_integration.py` | CREATE | build parity, plane backward-readable, CLI surface |
| `packages/ai-parrot/tests/knowledge/wiki/fixtures/pre_feat540/repo/` | CREATE | tiny source repo (3 files) |
| `packages/ai-parrot/tests/knowledge/wiki/fixtures/pre_feat540/wiki.db` | CREATE | plane built by pre-FEAT-540 code (binary, not git-ignored — verified) |
| `packages/ai-parrot/tests/knowledge/wiki/fixtures/pre_feat540/expected_stats.json` | CREATE | pre-FEAT-540 `stats()` of that build |
| `packages/ai-parrot-tools/tests/wiki/test_agent_path_unchanged.py` | CREATE | LLMWikiToolkit + GraphIndexToolkit smoke |
| `artifacts/logs/feat540-gate.md` | CREATE | AC evidence log |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `63cc2198e` (2026-09-15). Files created by earlier FEAT-540 tasks
> (`test_import_ceilings.py`, `parrot_tools/wiki/*`, `graphindex/protocols.py`,
> `parrot/embeddings/graphindex.py`, `wiki/operations.py`) do not exist yet at authoring time —
> verify their names at execution time.

### Verified Imports
```python
from click.testing import CliRunner                                   # verified: tests/knowledge/wiki/test_cli.py:18
from parrot.knowledge.wiki.cli import wiki                            # verified: cli.py:1328 (@click.group(name="wiki")), test_cli.py:20
from parrot.knowledge.wiki.store import create_wiki_store             # verified: mcp_server.py:27
from parrot.knowledge.wiki.project import load_effective_config       # verified: mcp_server.py:21-26
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit, HashingGraphEmbedder  # verified: factory.py:197, :116
from parrot_tools.wiki import LLMWikiToolkit                          # created by TASK-3263 — verify
from parrot.knowledge.wiki.models import WikiConfig                   # verified: wiki/toolkit.py:27
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@click.group(name="wiki")                                              # line 1328
def wiki(ctx: click.Context, verbose: bool) -> None: ...               # line 1337
def main() -> None: ...                                                # line 4952  (entry point: pyproject `wikitoolkit = "parrot.knowledge.wiki.cli:main"`, line 180)
#   build options include --path, --force, --no-git, --quiet, --no-graph (line 1381)
#   Registered top-level commands today (verified via sorted(wiki.commands)):
#   audit, build, claude, claude-hook, codex, communities, export, gemini, google, ground, ingest,
#   ingest-jira, ledger, link, mcp, memories, note, ns, page, query, related, remember, status,
#   symbols, sync, upsert;  symbols: blast, lookup, outline;  ns: add, list, remove

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):                                    # line 379
    def graph_path(self, root: Path) -> Path: ...                      # line 503
    def storage_path(self, root: Path) -> Path: ...                    # line 519
    def db_path(self, root: Path) -> Path: ...                         # line 524

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py  (SQLiteWikiStore)
    async def stats(self) -> dict[str, Any]: ...                       # line 2100
#   keys: pages, edges, sources, embeddings, symbols, total_tokens, categories

# existing build-fixture pattern — packages/ai-parrot/tests/knowledge/wiki/test_cli.py:33-52
runner.invoke(wiki, ["build", "--path", str(tmp_path), "--no-graph", "--quiet"])

# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
async def build_graph_memory_toolkit(db_dir=None, tenant_id="default", agent_id="agent", run_id=None,
    embedder=None, client=None, dimension=DEFAULT_DIMENSION, backend="sqlite", dsn=None,
    schema="graphindex") -> "GraphIndexToolkit": ...                   # line 197

# LLMWikiToolkit (moves to parrot_tools/wiki/toolkit.py in TASK-3263)
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any, okf_toolkit: Any,
                 config: WikiConfig, agent_id: str = "agent", store=None, **kwargs) -> None  # wiki/toolkit.py:70
    async def query(...)                                               # wiki/toolkit.py:356
# AbstractToolkit.get_tools(...)                                       # parrot/tools/toolkit.py:486

# pytest config: asyncio_mode = "auto" (packages/ai-parrot/pyproject.toml:972, pytest.ini:3)
```

### Measured baselines (dev @ 63cc2198e, this venv) — context for the ceilings
```text
parrot 94 | parrot.auth.exceptions 1178 | parrot.knowledge.ontology.schema 1600 | parrot.stores.models 826
parrot.knowledge.graphindex 1952 | parrot.knowledge.graphindex.builder 2507 | parrot.knowledge.wiki.cli 1998
Ceilings (spec §5): auth.exceptions ≤150, ontology.schema ≤240, graphindex ≤800, graphindex.builder ≤1200, wiki.cli ≤850
Forbidden after each: navconfig, parrot.conf, navigator_eventbus, asyncdb, pandas, faiss, pyarrow, redis, asyncpg
```

### Does NOT Exist
- ~~A pre-FEAT-540 `wiki.db` fixture in the repo~~ — created here (`tests/knowledge/wiki/fixtures/` holds only `jira/` today).
- ~~`artifacts/logs/feat540-gate.md`~~ — created here.
- ~~`wikitoolkit link --json` / `stats` command~~ — read counts via `SQLiteWikiStore.stats()`, not a CLI flag.
- ~~A `status` flag that prints page/edge counts in machine form~~ — do not parse human CLI output for counts.
- ~~Network or real LLM access in tests~~ — use `HashingGraphEmbedder` and a stub `LLMCaller`.

---

## Implementation Notes

### Key Constraints
- **Module counts are not measurable in-process** (spec §7): every ceiling assertion forks a subprocess
  (the harness from TASK-3256 already does — do not "optimise" it into one process).
- The AST scan checks **module-level** statements only, descending into `try`/`except`/`else`/`finally` and
  non-`TYPE_CHECKING` `if` bodies; `if TYPE_CHECKING:` blocks and function/class-body imports are allowed
  (lazy seams). String-based PEP 562 maps (`importlib.import_module("...")`) are allowed.
- Banned prefixes: `parrot.tools`, `parrot.clients`, `parrot.loaders`, `parrot.stores`, `parrot.embeddings`,
  `parrot_tools` (design D12). Match on the dotted module (`ImportFrom.module`, `Import.names[*].name`);
  resolve relative imports (`level > 0`) against the file's package before matching.
- The pre-FEAT-540 plane must come from **pre-feature code**, not from the branch under test:
  baseline commit `63cc2198e` (last `dev` commit before any FEAT-540 implementation — re-verify with
  `git log --oneline -- sdd/tasks/index/graphindex-core-seams.json`). Do NOT `git checkout` in the worktree and
  do NOT create an ad-hoc `git worktree add` (worktree rules §2); use
  `git archive 63cc2198e packages/ai-parrot/src | tar -x -C <scratch>` and run with `PYTHONPATH=<scratch>/packages/ai-parrot/src`.
  The Cython `parrot/utils/types.cpython-3*.so` exists only in the main checkout — copy it into the scratch tree if the import needs it.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest ...`; never `uv sync` inside a worktree.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm all 12 dependency tasks are in `sdd/tasks/completed/` — *why*: the gate is meaningless on a partial feature.
2. Generate the pre-FEAT-540 fixtures (repo, `wiki.db`, `expected_stats.json`) from baseline code in a scratch dir, copy them into `fixtures/pre_feat540/` — *why*: backward-readability and build parity need an oracle the branch cannot influence.
3. Remove xfail marks in `test_import_ceilings.py`; run it — *why*: G1/G2/G2b hard gate. On failure: importtime trace → Completion Note → ESCALATE.
4. Write and run the AST scan — *why*: G3.
5. Write and run `test_feat540_integration.py` and `test_agent_path_unchanged.py` — *why*: G4 + "no behavioural change".
6. Walk every §5 checkbox below, paste command + result lines into `artifacts/logs/feat540-gate.md`.

### `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` (MODIFY)
```python
# FILL IN: anchor — created by TASK-3256 and edited by TASK-3257; locate every
# `pytest.mark.xfail(` / `pytest.param(..., marks=pytest.mark.xfail(...))` occurrence
# (grep -c 'xfail' packages/ai-parrot/tests/knowledge/test_import_ceilings.py) and remove the marks
# so the five cases (auth.exceptions 150, ontology.schema 240, graphindex 800,
# graphindex.builder 1200, wiki.cli 850) all run as plain parametrized cases —
# bounded by spec §5: numbers and FORBIDDEN list unchanged.
```
**Why**: the ceilings are the objective gate the spec defines; strict assertions only now that every seam has landed.

### `packages/ai-parrot/tests/knowledge/test_no_framework_imports_in_graph_tree.py` (CREATE)
```python
"""FEAT-540 G3 — no module-level framework imports in the wiki/graphindex tree."""
from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

BANNED_PREFIXES: tuple[str, ...] = (
    "parrot.tools",
    "parrot.clients",
    "parrot.loaders",
    "parrot.stores",
    "parrot.embeddings",
    "parrot_tools",
)
SRC_ROOT = Path(__file__).resolve().parents[2] / "src"          # FILL IN: verify parents[N] → packages/ai-parrot/src
GRAPH_TREE = [SRC_ROOT / "parrot" / "knowledge" / "wiki", SRC_ROOT / "parrot" / "knowledge" / "graphindex"]


def _is_type_checking(test: ast.expr) -> bool:
    """True for ``TYPE_CHECKING`` / ``typing.TYPE_CHECKING`` guards."""
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _module_level_imports(body: list[ast.stmt]) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield imports executed at import time (descends try/if, skips TYPE_CHECKING and defs)."""
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.If):
            if not _is_type_checking(node.test):
                yield from _module_level_imports(node.body)
            yield from _module_level_imports(node.orelse)
        elif isinstance(node, ast.Try):
            # FILL IN: descend body, orelse, finalbody and every handler body — bounded by
            # "module-level incl. try bodies" (design D12); also ast.TryStar on 3.11+
            yield from _module_level_imports(node.body)


def _qualified(node: ast.Import | ast.ImportFrom, path: Path) -> list[str]:
    """Dotted module names an import statement loads."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    # FILL IN: resolve relative ImportFrom (node.level > 0) against the package of `path`
    # relative to SRC_ROOT — bounded by: `from ..stores import x` inside parrot/knowledge must match "parrot.stores"
    return [node.module or ""]


def _violations() -> list[str]:
    found: list[str] = []
    for tree_root in GRAPH_TREE:
        for path in sorted(tree_root.rglob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in _module_level_imports(module.body):
                for name in _qualified(node, path):
                    if name.startswith(BANNED_PREFIXES):
                        found.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}: {ast.unparse(node)}")
    return found


def test_no_framework_imports_in_graph_tree() -> None:
    """Spec §5: no parrot.tools/clients/loaders/stores/embeddings (or parrot_tools) at module level."""
    assert GRAPH_TREE[0].is_dir() and GRAPH_TREE[1].is_dir()
    assert _violations() == []


def test_scanner_detects_a_violation(tmp_path: Path) -> None:
    """Guard against a scanner that silently finds nothing."""
    # FILL IN: parse a synthetic module string containing `try:\n    from parrot.stores.models import Document\nexcept ImportError:\n    pass`
    # and `if TYPE_CHECKING:\n    from parrot.tools.abstract import AbstractTool`; assert exactly the try-import is flagged.
    pytest.skip("FILL IN")
```
**Why**: a scanner-self-test prevents the gate from passing because of a path or recursion bug (the classic "measured nothing" failure spec §7 warns about for ceilings).

### `packages/ai-parrot/tests/knowledge/wiki/test_feat540_integration.py` (CREATE)
```python
"""FEAT-540 end-to-end regressions: build parity, plane backward-readability, CLI surface."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki

FIXTURES = Path(__file__).parent / "fixtures" / "pre_feat540"

EXPECTED_COMMANDS = {
    "build", "query", "page", "related", "remember", "note", "link",
    "memories", "audit", "status", "export", "symbols", "ns", "mcp",
}


def test_wikitoolkit_cli_surface_unchanged() -> None:
    """Spec §5: CLI command surface unchanged."""
    assert EXPECTED_COMMANDS <= set(wiki.commands)
    assert set(wiki.commands["symbols"].commands) >= {"lookup", "outline", "blast"}
    assert set(wiki.commands["ns"].commands) >= {"list", "add", "remove"}


async def test_wikitoolkit_build_end_to_end(tmp_path: Path) -> None:
    """``wikitoolkit build`` over the fixture repo yields the pre-FEAT-540 page/edge counts."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "repo", repo)
    result = CliRunner().invoke(wiki, ["build", "--path", str(repo), "--no-git", "--quiet"])
    assert result.exit_code == 0, result.output
    expected = json.loads((FIXTURES / "expected_stats.json").read_text())
    # FILL IN: open the plane (load_effective_config(repo).config → create_wiki_store(config.storage_path(repo),
    # wiki_name=..., backend=config.backend)), await stats(), compare pages/edges/symbols/categories to
    # `expected` — bounded by: build flags identical to those used for the baseline (record them in the JSON);
    # exclude volatile keys (total_tokens only if tokenizer-dependent — justify in Completion Note).


async def test_wiki_plane_backward_readable(tmp_path: Path) -> None:
    """A wiki.db built by pre-FEAT-540 code opens and queries unchanged."""
    # FILL IN: copy FIXTURES/"wiki.db" to the storage path a WikiProjectConfig expects (db_path), open with
    # create_wiki_store, assert stats() == expected (same keys as above) and that search_fts("<term from repo>")
    # returns ≥1 hit and get_page(<an id from that hit>) is not None — bounded by: no schema migration in scope.
    pytest.skip("FILL IN")
```
**Why**: parity against a pre-feature oracle is the only proof that relocations + seams did not change what `build` writes.

### `packages/ai-parrot-tools/tests/wiki/test_agent_path_unchanged.py` (CREATE)
```python
"""FEAT-540 G4 — the agent path still gets real providers, injected rather than imported."""
from __future__ import annotations

from pathlib import Path

from parrot.knowledge.graphindex.factory import HashingGraphEmbedder, build_graph_memory_toolkit
from parrot.knowledge.wiki.models import WikiConfig
from parrot_tools.wiki import LLMWikiToolkit


class _StubLLM:
    """Minimal LLMCaller double (no network)."""

    async def ask(self, *args, **kwargs):
        return "stub"

    async def ask_structured(self, *args, **kwargs):
        return None

    async def ask_json(self, *args, **kwargs):
        return {}


async def test_agent_path_unchanged(tmp_path: Path) -> None:
    """LLMWikiToolkit + GraphIndexToolkit wire together and answer a query offline."""
    graph_toolkit = await build_graph_memory_toolkit(tmp_path / "graph", tenant_id="t", embedder=HashingGraphEmbedder())
    toolkit = LLMWikiToolkit(None, graph_toolkit, None, WikiConfig(wiki_name="t", storage_dir=tmp_path), agent_id="gate")
    # FILL IN: assert toolkit.get_tools() exposes the pre-FEAT-540 tool names (compare with the golden
    # file / a literal set), seed one page (toolkit remember/create_page) and assert toolkit.query(...) returns it;
    # also assert isinstance(HashingGraphEmbedder(), parrot.knowledge.graphindex.protocols.Embedder) and
    # _StubLLM() satisfies LLMCaller — bounded by spec G4 (real embedder + adapter injected, no network).
```
**Why**: spec §4 `test_agent_path_unchanged`; lives in ai-parrot-tools because the toolkit now does.

### FILL IN checklist
- [ ] `test_import_ceilings.py` — remove all xfail marks; ceilings/forbidden list untouched.
- [ ] AST scan — `SRC_ROOT` parents index; try/handler/finally/TryStar descent; relative-import resolution; self-test body.
- [ ] Fixtures — baseline commit verified; build flags recorded in `expected_stats.json`; `.so` copied if needed.
- [ ] `test_wikitoolkit_build_end_to_end` — store opening + compared keys (volatile keys justified).
- [ ] `test_wiki_plane_backward_readable` — storage placement + query assertions.
- [ ] `test_agent_path_unchanged` — tool-name set, seeded query, protocol isinstance checks.
- [ ] `artifacts/logs/feat540-gate.md` — every §5 criterion with command + outcome.

---

## Addendum — repo-root `tests/` tree (review, 2026-09-15)

CI also runs the repo-root `tests/` tree (root `pyproject.toml` `testpaths=["tests"]`;
ci.yml:138, :200), which holds most wiki/structural/ledger/MCP tests
(`tests/knowledge/wiki/**`, `tests/test_fireflies_wiki_agent.py`,
`tests/integration/test_fireflies_meeting_registry.py`). The gate is not green
unless `pytest tests/knowledge/wiki/ -v` passes too (service-backed integration tests
may skip). Run it alongside the package suites and report skips separately from passes.

---

## Acceptance Criteria

Spec §5, verbatim — every box must be ticked with evidence in `artifacts/logs/feat540-gate.md`:

- [ ] `import parrot.knowledge.wiki.cli` loads **≤ 850** modules in a clean subprocess (baseline on `dev` @ `24ff50f03`: 1995; measured floor 698)
- [ ] `import parrot.knowledge.ontology.schema` loads **≤ 240** modules (baseline: 1607; measured floor 124)
- [ ] `from parrot.auth.exceptions import AuthorizationRequired` loads **≤ 150** modules (baseline: 1186)
- [ ] `import parrot.knowledge.graphindex` loads **≤ 800** modules (baseline: 1959)
- [ ] `import parrot.knowledge.graphindex.builder` loads **≤ 1200** modules (baseline: 2511)
- [ ] None of `navconfig`, `parrot.conf`, `navigator_eventbus`, `asyncdb`, `pandas`, `faiss`, `pyarrow`, `redis`, `asyncpg` appears in `sys.modules` after any of the four imports above
- [ ] No module under `parrot/knowledge/wiki/` or `parrot/knowledge/graphindex/` imports `parrot.tools.*`, `parrot.clients.*`, `parrot.loaders.*`, `parrot.stores.*` or `parrot.embeddings.*` at module level (AST-scan test)
- [ ] `from parrot_tools.wiki import LLMWikiToolkit, CodeStructuralToolkit` resolves; the moved tools expose byte-identical names and input schemas
- [ ] `wikitoolkit` CLI surface unchanged: `build`, `query`, `page`, `related`, `remember`, `note`, `link`, `memories`, `audit`, `status`, `export`, `symbols {lookup,outline,blast}`, `ns {list,add,remove}`, `mcp`
- [ ] The wiki MCP server starts and serves the same tool names with `parrot.mcp` unimportable, and still returns `StdioMCPServer` when it is
- [ ] `resolve_setting()` is the only configuration reader in the graph tree — `_env_setting`, `_env_credential` and the inline navconfig block are gone
      (`grep -rn "_env_setting\|_env_credential\|from navconfig import config" packages/ai-parrot/src/parrot/knowledge/wiki packages/ai-parrot/src/parrot/knowledge/graphindex` → only `resolve_setting`'s own lazy import and the out-of-scope `pg_schema.py:20`)
- [ ] A `wiki.db` plane built before this change opens and queries unchanged
- [ ] `pytest packages/ai-parrot/tests/knowledge/ -v` passes
- [ ] `pytest packages/ai-parrot-tools/tests/ -v` passes
- [ ] `ruff check .` clean on changed files
- [ ] Google-style docstrings + type hints on every new/changed public symbol
- [ ] No breaking change to any documented public import path
- [ ] `pytest tests/knowledge/wiki/ -v` (repo-root tree) passes; skips listed in the Completion Note

Task-local:
- [ ] `test_scanner_detects_a_violation` passes (scanner is not vacuous).
- [ ] Out-of-scope module-level imports (pg_schema, claude_code/cli, jira_*, vault_scan) listed in the Completion Note for FEAT-541.

---

## Test Specification

The four new test files in the blueprint plus the de-xfailed `test_import_ceilings.py`. Full runs:
```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot/tests/knowledge/ -v
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot-tools/tests/ -v
```
If a suite fails for reasons unrelated to FEAT-540, prove it against the baseline commit (same command on
the `git archive` scratch tree) and record it — do not mark the gate green on an unexplained failure.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — all of TASK-3256..TASK-3267 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep every anchor; confirm names created by earlier tasks
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`
6. **Verify** all acceptance criteria (worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`; never `uv sync` in a worktree)
7. **Move this file** to `sdd/tasks/completed/TASK-3268-import-ceiling-integration-gate.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: Per-ceiling measured counts; any escalations (import chain for a failed ceiling); out-of-scope
module-level imports recorded for FEAT-541.

**Deviations from spec**: none | describe if any
