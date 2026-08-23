# TASK-2368: Documentation + end-to-end integration tests (vault namespace, MCP, precedence)

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2363, TASK-2364, TASK-2365, TASK-2366, TASK-2367
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 and the integration rows of §4 that span several modules. Closes the feature:
operator docs for `--ns` / `ns` commands / `ns::` ids / namespace kinds (incl. `vault`, Delta 2),
the Claude Code integration note, the one-line CLAUDE.md update, the v2 follow-up list, and the
end-to-end tests that exercise the whole chain (vault → build → `ns add --vault` → broadcast query;
precedence with namespaces configured; MCP tool output).

---

## Scope

- `documentation/parrot-wiki-cli.md`: new section **"Namespaces"** immediately after "Querying an
  external / pre-built store" (lines 424-451): concepts (local vs foreign, `ns::id`, local
  unprefixed), the four kinds with JSON examples for `.parrot/wiki.json` and `~/.parrot/wikis.json`
  (repo wins; `PARROT_HOME`), every `ns` command (`list` / `add` with `--project` / `--store` /
  `--database` / `--vault` / `--global` / `--description` / `--weight`; `remove`), `--ns` on
  `query/page/related/status` and on `remember/note/link` (U2), precedence table amended
  (`--store` never federates), skip/unbuilt behaviour and hints, the vault kind (plane inside the
  vault, `.parrot/` cost, `build --path <vault>`), and a **"Not in v1 (follow-ups)"** list: intent
  router, RRF, cross-namespace edges, multi-target writes, Obsidian write-back.
- `docs/wiki-claude-code.md`: note that query stubs may carry `ns::` ids and that the MCP tools
  accept `namespace`.
- `CLAUDE.md` (wiki section): one line — ids returned by `wikitoolkit query` may be qualified
  `ns::id`; pass them verbatim to `page` / `related`.
- Integration tests (`tests/knowledge/wiki/test_namespaces_e2e.py`): `test_vault_namespace_end_to_end`,
  `test_explicit_path_beats_env_with_namespaces`, `test_query_json_rows_carry_namespace`, plus any
  §4 integration row not yet covered by TASK-2363/2364/2365 (check their Completion Notes).
- Run the full wiki suite and record results in the Completion Note.

**NOT in scope**: code changes beyond what tests reveal (file a follow-up task if a bug is found
rather than fixing silently outside scope — unless trivial and noted).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `documentation/parrot-wiki-cli.md` | MODIFY | "Namespaces" section |
| `docs/wiki-claude-code.md` | MODIFY | `ns::` / `namespace` note |
| `CLAUDE.md` | MODIFY | one line in the wiki section |
| `tests/knowledge/wiki/test_namespaces_e2e.py` | CREATE | end-to-end tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki                                   # cli.py:696
from parrot.knowledge.wiki.project import load_project_config, save_project_config, WikiNamespaceConfig   # project.py:323,350 + TASK-2359
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server          # mcp_server.py:66
from parrot.knowledge.wiki.federation import FederatedWikiStore              # TASK-2362
```

### Existing Signatures to Use
```python
# documentation/parrot-wiki-cli.md
## Querying an external / pre-built store          # 424 — insert the new section after 451
# precedence block 446-451:
#   --store flag  >  WIKI_STORE env  >  project .parrot/wiki.json plane
#   --backend flag >  WIKI_STORE_BACKEND env  >  sqlite
# tests/knowledge/wiki/test_cli.py
PY_STORE / PY_UTIL sample modules (38-39); fixture repo(tmp_path) builds and `build`s a temp repo (42-53); runner() → CliRunner (55)
test_explicit_path_beats_wiki_store_env (212-214) — pattern to replicate with namespaces configured
# vault fixture shape (spec §4): <tmp>/vault/.obsidian/ + A.md ("[[B]]") + B.md ("#tag")
# cli.py build: vault auto-detect 810-815 → scan_vault; notes category="document" (vault_scan.py:159)
# TASK-2363/2364 add: --ns option; `ns add NAME --vault V` (inline .obsidian probe) ; TASK-2365: tool `namespace` argument
```

### Does NOT Exist
- ~~`ns add --path`~~ for the `path` kind — TASK-2364 renamed it `--project` (repo-root `--path` collision); document `--project`.
- ~~`WIKI_NS`~~ env var — non-goal; do not document one.
- ~~`build --register`~~ — does not exist (U1).
- ~~`docs/wiki-namespaces.md`~~ — do not create a separate doc; the CLI guide is the canonical place.

---

## Implementation Notes

### Pattern to Follow
Mirror the tone and table style of `documentation/parrot-wiki-cli.md:424-451` (short prose, a
bash block, a precedence block). Example JSON to include:
```json
{ "namespaces": {
    "asyncdb":  { "path": "../asyncdb", "description": "asyncdb driver layer" },
    "notes":    { "vault": "~/Obsidian/Work" },
    "legal":    { "database": "wiki_legal", "credentials_env": "ARANGODB", "weight": 0.8 } } }
```

### Key Constraints
- Tests must use `PARROT_HOME` (monkeypatch) so they never touch the real `~/.parrot`.
- The e2e vault test must assert `notes::file:A.md` with `category == "document"` and that a
  second `build --path <vault>` does not ingest `<vault>/.parrot/wiki/log.md` (TASK-2366).

### References in Codebase
- `documentation/parrot-wiki-cli.md:640-671` — example commands + troubleshooting table to extend
  with `Unknown namespace` / `namespace 'x' skipped: unbuilt` rows.

---

## Acceptance Criteria

- [ ] "Namespaces" section documents every `ns` command, `--ns`, kinds (incl. `vault`), precedence, skips, follow-ups
- [ ] `docs/wiki-claude-code.md` and `CLAUDE.md` notes added
- [ ] `test_vault_namespace_end_to_end` passes: vault → `build --path` → `ns add notes --vault` → `query` returns `notes::file:A.md` (`category=document`); rebuild ingests no `.parrot` file
- [ ] Precedence test with namespaces configured passes; JSON rows carry `namespace`
- [ ] `pytest tests/knowledge/wiki packages/ai-parrot/tests/knowledge/wiki -v` fully green; results pasted in the Completion Note
- [ ] Spec §5 checklist reviewed line by line; any unmet criterion reported (not silently skipped)

---

## Test Specification

```python
# tests/knowledge/wiki/test_namespaces_e2e.py
import json, pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki

@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"; (v / ".obsidian").mkdir(parents=True)
    (v / "A.md").write_text("# A\nSee [[B]] about zebras.\n"); (v / "B.md").write_text("# B\n#tag zebra habitat\n")
    return v

def test_vault_namespace_end_to_end(runner, repo, vault, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    assert runner.invoke(wiki, ["build", "--path", str(vault), "--quiet"]).exit_code == 0
    assert runner.invoke(wiki, ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)]).exit_code == 0
    rows = json.loads(runner.invoke(wiki, ["query", "zebra", "--path", str(repo), "--json"]).output)
    hit = next(r for r in rows if r["concept_id"] == "notes::file:A.md")
    assert hit["category"] == "document" and hit["namespace"] == "notes"
    assert runner.invoke(wiki, ["build", "--path", str(vault), "--quiet"]).exit_code == 0
    ids = {r["concept_id"] for r in json.loads(runner.invoke(wiki, ["query", "log", "--path", str(vault), "--json"]).output)}
    assert not any(".parrot" in i for i in ids)

def test_explicit_path_beats_env_with_namespaces(runner, repo, tmp_path, monkeypatch): ...
def test_query_json_rows_carry_namespace(runner, repo, tmp_path): ...
```

---

## Agent Instructions

1. Read spec §3 Module 7, §4 integration rows, §5; read the Completion Notes of TASK-2363..2367.
2. Write docs + tests; run the full wiki suites.
3. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note with the test summary.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
