# TASK-2752: End-to-end integration suite, no-extra no-op proof, CI wiring

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2742, TASK-2743, TASK-2744, TASK-2745, TASK-2746, TASK-2751
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and acceptance criteria AC1, AC2, AC12, AC13,
AC14, AC17. Closes the feature with the cross-module proofs no single task
can give: a polyglot build with and without ast-grep, the nine-tool MCP
server, `upsert --changed` symbol refresh, lookup → blast → edit → repair,
and a wheel build that ships the rule files.

---

## Scope

- `tests/knowledge/wiki/test_structural_e2e.py`:
  - `test_polyglot_build_produces_symbols` — extend the `polyglot_repo`
    fixture (add a `.pm` and a `.svelte` if missing): `scan_repository` +
    `_ingest_files` → `sym:` pages for every language (Python always; others
    when ast-grep is installed), `defines`/`contains`/`calls` edges,
    `content_hash` on every `file:` page; **and** `## API outline` bodies
    identical between a run with the seam and a run with `force_no_astgrep`.
  - `test_no_extra_installed_is_noop` — with `astgrep.is_available`
    monkeypatched `False`: pages/edges equal a pre-feature baseline dump
    (generate the baseline by running the same fixture through the walkers
    only and stripping `sym:` pages, `defines/contains(sym)` edges,
    `content_hash`) — proves AC2.
  - `test_mcp_server_registers_nine_tools_and_round_trips` — stdio adapter
    call of `wiki_symbol_lookup`.
  - `test_upsert_changed_refreshes_symbols` — commit a rename in a tmp git
    repo, run the `upsert --changed` command via `CliRunner`, assert old `sym:`
    gone, new present, `broken_edges()` lists the dangling `calls` edge until
    the dependent file is upserted.
  - `test_end_to_end_lookup_blast_repair` — lookup → blast_radius(files) →
    edit on disk → lookup shows fresh + `repaired_files`.
  - `test_tool_calls_are_read_only` — tree snapshot invariant across all
    three tools and the CLI (AC14).
- Wheel/package-data check: a test (or `scripts/` check invoked from CI) that
  builds `packages/ai-parrot` with `uv build` into the scratch dir and asserts
  `parrot/knowledge/wiki/languages/rules/*.yaml` are inside the wheel (AC17).
- CI: add `wiki-structural` to the job that already installs `wiki-languages`
  (find it under `.github/workflows/`), keeping the default job without it so
  both modes run (spec §4 CI note). Note: pushing branches that touch
  `.github/workflows/*` requires SSH (repo memory) — the sdd-worker should
  commit but leave the push to the human if `gh` token lacks `workflow` scope.
- Update `docs/llm-wiki.md` only if a behaviour discovered here contradicts
  TASK-2751's text.

**NOT in scope**: new features, walker changes, dev_loop.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/test_structural_e2e.py` | CREATE | E2E suite |
| `tests/knowledge/wiki/languages/conftest.py` | MODIFY | Extend `polyglot_repo` with `.pm` / `.svelte` if absent |
| `tests/knowledge/wiki/test_wheel_package_data.py` | CREATE | Rule files ship in the wheel (marked `slow`) |
| `.github/workflows/<tests workflow>.yml` | MODIFY | Install `wiki-structural` in the extras job |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.repo_scan import scan_repository, file_concept_id          # repo_scan.py:776/249
from parrot.knowledge.wiki.cli import wiki, _ingest_files                              # cli.py:1071/622
from parrot.knowledge.wiki.store import create_wiki_store, BaseWikiStore              # store.py (factory used in tests: test_store.py:385)
from parrot.knowledge.wiki.sources import SourceCollectionManager                     # sources.py:107
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server                   # mcp_server.py:90
from parrot.knowledge.wiki.structural.service import StructuralService                # TASK-2749
from parrot.knowledge.wiki.languages import astgrep                                   # TASK-2739
from click.testing import CliRunner
```

### Existing Signatures to Use
```python
# tests/knowledge/wiki/languages/conftest.py:69 polyglot_repo(tmp_path) -> Path — one file per supported language + HTML ; :47 svelte_repo ; :11 force_heuristic ; force_no_astgrep (TASK-2739)
# tests/knowledge/wiki/languages/test_polyglot_integration.py:24 test_scan_repository_polyglot_fixture — baseline expectations for file pages/edges
# tests/knowledge/wiki/test_integration.py — existing build-then-query integration precedent (49 KB; read the fixture setup, reuse it)
# cli.py `upsert` :1389 with `--changed` :1384 → _changed_files_from_git(root) :1335 (uses `git diff-tree -z --root -m --first-parent HEAD`)
# packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py — asserting registered tool names on a StdioMCPServer
# pyproject package-data: packages/ai-parrot/pyproject.toml:759 [tool.setuptools.package-data]
```

### Does NOT Exist
- ~~`tests/integration/` for the wiki~~ — wiki tests live under `tests/knowledge/wiki/`; keep the new suite there.
- ~~a pre-feature baseline dump file~~ — compute it in-test from the walker-only run (no committed golden file needed).
- ~~`ast_grep`/`ast_edit`/dev_loop assertions~~ — out of scope.

---

## Implementation Notes

- Run every e2e test twice via `pytest.mark.parametrize("seam", ["on", "off"])`
  where `"off"` monkeypatches `astgrep.is_available → False`; skip
  ast-grep-specific assertions when the package is not importable.
- For `test_upsert_changed_refreshes_symbols` initialise a real git repo in
  `tmp_path` (`git init`, config user, commit) — `_changed_files_from_git`
  needs `HEAD`.
- Tree snapshot helper: `{p.relative_to(root): sha1(bytes)}` for all files
  excluding `.parrot/` and `.git/`.
- Wheel test: `uv build --wheel --out-dir <scratch> packages/ai-parrot` then
  `zipfile` listing; mark `@pytest.mark.slow` and skip when `uv` is absent.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/test_structural_e2e.py -v` passes with ast-grep installed and with it absent (both parametrisations).
- [ ] AC1/AC2 proven: identical `## API outline` bodies in both modes; walker-only run equals the pre-feature baseline except Python `sym:` pages and `content_hash`.
- [ ] Nine tools registered; `wiki_symbol_lookup` round-trips over stdio.
- [ ] `upsert --changed` after a rename: old `sym:` absent, new present, dangling `calls` edge reported by `broken_edges()`, cleared after upserting the dependent file.
- [ ] Lookup → blast → edit → lookup shows `repaired_files` and fresh hits.
- [ ] Tree snapshot identical across all tool/CLI calls.
- [ ] Wheel contains `parrot/knowledge/wiki/languages/rules/{typescript,php,rust,perl,python}.yaml`.
- [ ] CI workflow installs `wiki-structural` in the extras job; default job unchanged.
- [ ] Full `pytest tests/knowledge/wiki -v` green; `ruff` clean.

---

## Test Specification

```python
@pytest.mark.parametrize("seam", ["on", "off"])
async def test_polyglot_build_produces_symbols(polyglot_repo, seam, monkeypatch):
    if seam == "off":
        monkeypatch.setattr(astgrep, "is_available", lambda: False)
    store = create_wiki_store(polyglot_repo / ".parrot" / "wiki", wiki_name="t", backend="sqlite")
    sources = SourceCollectionManager(polyglot_repo / ".parrot" / "wiki")   # verify constructor signature in sources.py:107-130
    scan = scan_repository(polyglot_repo, use_git=False)
    await _ingest_files(store, sources, polyglot_repo, scan)
    pages = await store.dump_pages()
    assert any(p["concept_id"].startswith("sym:") and p["concept_id"].endswith(".py#helper") for p in pages)
    assert all(p.get("content_hash") for p in pages if p["concept_id"].startswith("file:"))
```

---

## Agent Instructions

1. Read spec §4 Integration Tests and §5 AC1/2/12/13/14/17. 2. Confirm all
`Depends-on` tasks completed. 3. Verify contract lines (especially
`SourceCollectionManager` constructor and the tests workflow file name).
4. Index → `in-progress`. 5. Implement. 6. Run the full wiki suite in both
modes. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
