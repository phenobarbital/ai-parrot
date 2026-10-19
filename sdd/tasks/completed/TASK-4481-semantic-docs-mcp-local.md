# TASK-4481: mcp-local exposure + semantic-layer docs (M11b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4479
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (MCP + docs) + AC13/AC16/AC21. **Drift found at task time:** `.parrot/mcp-toolkits.yaml` and `.mcp.json` are git-ignored, operator-local files (`.gitignore:411`, `:392`) and contain neither `database-query:` nor `parrot-database-query` anchors — they cannot be committed. The `semantic-layer:` section and `.mcp.json` entry are therefore DOCUMENTED (copy-paste blocks) and exercised by tests with a temporary config file.

---

## Scope

- Create `docs/tools/semantic-layer.md`: tools, policy file schema (incl. `allowed_functions` additive rule), `audit_required` resolution + Postgres sink (`semantic_audit_events.sql`, `postgres_audit_storage`), AGPL notice, mcp-local `static_subject` identity, the `.parrot/mcp-toolkits.yaml` section and `.mcp.json` entry to paste.
- Write `test_mcp_local.py`: `test_mcp_toolkits_yaml_section` (`load_toolkits_config` on a temp root) and `test_e2e_mcp_local_semantic_layer` (`parrot mcp-local semantic-layer --list` via click's CliRunner against a temp config; tool list matches exposure rules; no real LLM).

**NOT in scope**: editing the git-ignored local config files; HTTP handler (TASK-4480).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/tools/semantic-layer.md` | CREATE | user/operator documentation |
| `packages/ai-parrot-semantic/tests/test_mcp_local.py` | CREATE | mcp-local config + listing tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config   # verified: toolkit_config.py:20,80,90
from click.testing import CliRunner
# parrot/mcp/local_cli.py — `mcp_local` click command (lines 136-170): argument NAME + 4 options (read their names before use)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):   # line 20 — class_path (alias "class"), enabled, kwargs, include, exclude, llm, llm_kwargs, env (50-57)
class MCPToolkitsConfig(BaseModel):   # line 80 — toolkits: dict[str, ToolkitSection]
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig   # line 90 — reads <root>/.parrot/mcp-toolkits.yaml
# packages/ai-parrot/src/parrot/mcp/local_cli.py:164 — def mcp_local(name, config_path, include, exclude, list_toolkits)
```

### Does NOT Exist
- ~~A committed `.parrot/mcp-toolkits.yaml` / `.mcp.json` edit~~ — both git-ignored; document instead.
- ~~Server code changes for `mcp-local`~~ — a YAML `class:` section suffices (toolkit_config.py:50).
- ~~`docs/mcp-local-toolkits.md` needing changes~~ — link to it, do not edit it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/tools/semantic-layer.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_mcp_local.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#ToolkitSection"
  ]
}
```

---

## Implementation Notes

- Section to document (spec §3 M11): `semantic-layer: {class: parrot.semantic.toolkit.SemanticLayerToolkit, kwargs: {models_dir, dialect, static_subject: {user_id: operator, tenant_id: local, roles: [admin]}}, env: {}}`.
- `.mcp.json` entry mirrors the operator's existing `parrot-database-query`-style entries: command `parrot mcp-local semantic-layer`.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Write the docs — *why*: AC16/AC21.
2. Write the two tests against a temp root — *why*: AC13 without touching ignored files.

### `docs/tools/semantic-layer.md` (CREATE)
```markdown
# Semantic Layer (`ai-parrot-semantic`)

Governed metric queries for agents: sidemantic compiles, ai-parrot governs (PBAC, RLS push-down,
column lineage, masking, positive SQL guard, signed audit). FEAT-704.

## Install
## Tools (`sl_*`)
<!-- FILL IN: table of every tool from spec §2 New Public Interfaces; note run_sql (allow_raw_sql) and
     save_result_as_dataset (dataset_manager_factory) are absent unless enabled -->
## Models directory and `<model>.policy.yaml`
<!-- FILL IN: the spec §2 policy example; governed default; allowed_functions = DEFAULT ∪ additions, never removal -->
## Audit
<!-- FILL IN: SemanticAuditEntry fields; audit_required=None -> True iff audit_storage set; explicit False opt-out;
     Postgres sink: apply parrot/semantic/sql/semantic_audit_events.sql, pass postgres_audit_storage(dsn) -->
## HTTP API
## `parrot mcp-local semantic-layer`
<!-- FILL IN: the .parrot/mcp-toolkits.yaml section + .mcp.json entry to paste (both files are local/ignored);
     static_subject is a single operator identity, logged and flagged in every audit entry; link docs/mcp-local-toolkits.md -->
## License notice
sidemantic is AGPL-3.0 (network clause applies to hosted use). Sign-off: Jesus Lara, 2026-10-19.
```

### FILL IN checklist
- [ ] Docs sections — bounded by AC16/AC21 and spec §8 Q3-Q5.
- [ ] Test bodies (read local_cli option names first).

---

## Acceptance Criteria

- [ ] `docs/tools/semantic-layer.md` exists with tools, policy, audit, HTTP, mcp-local and license sections (AC16, AC21).
- [ ] `test_mcp_toolkits_yaml_section` and `test_e2e_mcp_local_semantic_layer` pass (AC13).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_mcp_local.py
from pathlib import Path
from parrot.mcp.toolkit_config import load_toolkits_config


def test_mcp_toolkits_yaml_section(tmp_path):
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot/mcp-toolkits.yaml").write_text(
        "toolkits:\n  semantic-layer:\n    class: parrot.semantic.toolkit.SemanticLayerToolkit\n"
        "    kwargs: {models_dir: /tmp/m, dialect: duckdb}\n")
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits["semantic-layer"].class_path == "parrot.semantic.toolkit.SemanticLayerToolkit"


def test_e2e_mcp_local_semantic_layer(tmp_path):
    # FILL IN: CliRunner().invoke(mcp_local, ["semantic-layer", "--list"/config option...]) with a temp config
    #          pointing at the fixture models dir + static_subject; assert sl_query_metrics listed, sl_run_sql not
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4481 — mcp-local exposure + semantic-layer docs (M11b)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4481 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4481
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 245.7s · Tokens: n/a
- Validation: merge-tier dde5085a:final:merge completed exit 0.
- Fix commits: 04590c8fed53bbec6ccd37759d5f1916aacdce05 — usage-rights paragraph updated to option A (restricted = masked or sensitive member); the decision was made after dispatch.
