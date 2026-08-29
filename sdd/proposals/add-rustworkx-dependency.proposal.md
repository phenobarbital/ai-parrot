---
id: FEAT-471
title: Make rustworkx a real (non-extra) dependency so wikitoolkit works on a bare install
slug: add-rustworkx-dependency
type: feature
mode: investigation
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-08-28
  summary_oneline: wikitoolkit needs rustworkx but it is not installed by `uv pip install ai-parrot` and `uv sync` removes it
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-471/
created: 2026-08-28
updated: 2026-08-28
---

# FEAT-471 — Make rustworkx a real (non-extra) dependency so wikitoolkit works on a bare install

> **Mode**: investigation
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-471/`](../state/FEAT-471/)

---

## 0. Origin

> add-rustworkx-dependency -- para funcionar con wikitoolkit * se necesita rustworkx pero esta como dependencia transitiva en algun lado, hacer un "uv pip install ai-parrot" no instala rustworkx, al parecer hacer un "uv sync" también lo desinstala, hay que reparar esa dependencia

**Initial signals** (extracted, not interpreted):
- Verbs: "no instala", "lo desinstala", "reparar" → dependency-metadata bug
- Named entities: `wikitoolkit`, `rustworkx`, `uv pip install ai-parrot`, `uv sync`
- Components / labels: packaging / `pyproject.toml` / uv workspace
- Acceptance criteria provided: no (implicit: `wikitoolkit *` works after `uv pip install ai-parrot` and survives `uv sync`)

---

## 1. Synthesis Summary

`rustworkx` is **not** a transitive dependency — it is declared exactly once, in ai-parrot's optional `graphindex` extra (`packages/ai-parrot/pyproject.toml:213`, re-exported by the `wiki` extra), and nothing else in `uv.lock` depends on it. A plain `uv pip install ai-parrot` therefore never installs it, and a bare `uv sync` (which builds an *exact* environment and the workspace root declares no default extras) prunes it. Meanwhile the `wikitoolkit` console script is shipped by core (`project.scripts`, line 147) and hard-imports `rustworkx` on **every** subcommand through `wiki/cli.py → wiki/documents.py → graphindex/__init__.py → graphindex/signals.py:30`. The satellite `ai-parrot-tools` has the same undeclared, unguarded import in `parrot_tools/graphindex/toolkit.py:52`. The recommended fix is to promote `rustworkx>=0.15` into core `dependencies` (and declare it in `ai-parrot-tools`), then regenerate `uv.lock`; a second, smaller decision is whether developer `uv sync` should include the `wiki` extra by default.

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/pyproject.toml` | `graphindex` extra | 210-220 | Only declaration of rustworkx — extra, not core | F001, F002 |
| 2 | `packages/ai-parrot/pyproject.toml` | `dependencies` | 36-80 | Core list where rustworkx must be added | F004 |
| 3 | `packages/ai-parrot/pyproject.toml` | `wikitoolkit` script | 147 | Core-shipped console script that needs rustworkx | F001, F005 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` | `import rustworkx` | 30 | First unguarded import on the wikitoolkit path | F003, F005 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` | package init | 31 | Eagerly imports `signals`, so any `graphindex.*` import pulls rustworkx | F005 |
| 6 | `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` | `PLAIN_TEXT_EXTENSIONS` import | 31 | Link from the wiki CLI into the graphindex package | F005 |
| 7 | `pyproject.toml` (workspace root) | `optional-dependencies` / `[tool.uv]` | 27-70 | No default extras/groups → `uv sync` prunes rustworkx | F004 |
| 8 | `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | `import rustworkx` | 52 | Satellite unguarded import, undeclared in its pyproject | F003, F007 |

### 2.2 Constraints Discovered

- **Cheap to promote.** rustworkx 0.18.1 requires only `numpy` and ships abi3 manylinux wheels (~2.4 MB); no C toolchain needed. *Implication*: adding it to core costs little. *Evidence*: F002
- **Siblings on the same path.** `aiosqlite`, `orjson`, `pathspec` are also extra-only (`graphindex`) and `sqlite_reader.py` imports `aiosqlite`/`orjson` unguarded. *Implication*: promoting rustworkx alone may just move the ImportError one line down unless those are verified present on a bare install. *Evidence*: F001, F003
- **Extras are the intended lean-install boundary.** Prior fix `e7f1dfccf` added networkx/pymupdf to the *extras*, not core; `wiki-languages` docs explicitly promise "core install gains zero new dependencies". *Implication*: keep tree-sitter / leiden / pymupdf in extras; only what the core-shipped CLI needs at import time should move. *Evidence*: F006, F004
- **Unguarded imports in 9 sites.** All rustworkx imports are module-level (except `export_html.py:42`). *Implication*: a guard-based alternative would need a single choke point (`graphindex/__init__.py`) rather than 9 edits. *Evidence*: F003

### 2.3 Recent History (Relevant)

| Commit | Message | Touched |
|--------|---------|---------|
| `b07e7fbea` | chore: bump flowtask>=5.12.14, remove gemma4 extra, clean resolver overrides | `packages/ai-parrot/pyproject.toml` |
| `e7f1dfccf` | fix(deps): add networkx and pymupdf to wiki/graphindex extras | `packages/ai-parrot/pyproject.toml` |

No commit has ever promoted rustworkx to core; the gap has existed since the `graphindex` extra was introduced (FEAT-187 comment). *Evidence*: F006

---

## 3. Hypothesis

### Hypothesis 1 — rustworkx is extra-only while the core-shipped `wikitoolkit` script hard-requires it · Confidence: **high**

**Supporting evidence**: F001, F002, F004, F005
**Contradicting evidence**: —
**Reasoning**: Direct read of `pyproject.toml` + `uv.lock` shows the single extra-scoped declaration; `uv pip show rustworkx` reports no dependents; a runtime probe (`sys.modules['rustworkx'] = None; import parrot.knowledge.wiki.cli`) reproduces `ModuleNotFoundError` through the exact chain `cli.py:49 → documents.py:31 → graphindex/__init__.py:31 → signals.py:30`. `uv sync` removes it because uv syncs exactly and the root declares no default extras.

**Suggested next probe** (bare-install verification before/after the fix):
```bash
source .venv/bin/activate
uv sync                      # no extras
wikitoolkit status           # currently: ModuleNotFoundError: rustworkx
```

### Proposed change (for the spec)

1. `packages/ai-parrot/pyproject.toml`: add `"rustworkx>=0.15"` to core `dependencies` (with a comment explaining why: `wikitoolkit` ships in core). Leave it in `graphindex` too (harmless) or remove it there — spec decides.
2. Verify on a bare `uv sync` whether `aiosqlite`/`orjson`/`pathspec` are present transitively; promote any that are not and are imported at module level on the wikitoolkit path (C6).
3. `packages/ai-parrot-tools/pyproject.toml`: declare `rustworkx>=0.15` (it is imported unguarded in `parrot_tools/graphindex/toolkit.py:52`).
4. `uv lock` + commit the refreshed `uv.lock`.
5. Add a regression test / CI step that imports `parrot.knowledge.wiki.cli` in a bare-core environment (no extras).

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | rustworkx is declared only under the `graphindex` extra of ai-parrot | F001, F002 | high | single grep hit + lock marker `extra == 'graphindex'` |
| C2 | Nothing in the lock depends on rustworkx outside that extra (it is NOT transitive) | F002 | high | lock dependents + `uv pip show` Required-by: empty |
| C3 | `uv sync` without `--extra wiki` removes rustworkx because the root declares no default extras | F004 | high | uv sync is exact; no `default-groups` / default extra at root |
| C4 | Every wikitoolkit subcommand fails without rustworkx, not only `build` | F005 | high | runtime probe fails at CLI module import |
| C5 | ai-parrot-tools has an undeclared rustworkx dependency | F007 | high | unguarded import, no pyproject entry |
| C6 | Promoting rustworkx alone is sufficient for `wikitoolkit query/page/related` on a bare install | F003, F005 | medium | aiosqlite/orjson/pathspec are also extra-only; not yet probed whether core pulls them transitively |

Distribution: **5** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- *(none — autonomous run; no Q&A gate executed)*

### Unresolved (defer to spec / implementation)

- [ ] **U1: Core dependency vs. guarded import?** Should `rustworkx` become a core dependency of ai-parrot (wikitoolkit works on bare install — **recommended**), or should `graphindex/__init__.py` guard the import and `wikitoolkit` print "install `ai-parrot[wiki]`" (keeps core lean)? — *Owner*: tbd
  *Blocks claims*: C6
  *Plausible answers*: a) core dependency (recommended: CLI ships in core, wheel is numpy-only) · b) guarded import + helpful error, keep extra · c) both

- [ ] **U2: Should developer `uv sync` include the `wiki` extra by default?** E.g. add `ai-parrot[wiki]` to the root `dev` dependency group so tree-sitter/leiden survive a sync. — *Owner*: tbd
  *Blocks claims*: C3 (mitigation only)
  *Plausible answers*: a) yes — add to `dev` group · b) no — document `uv sync --extra wiki` in CLAUDE.md / runbook

> Side note (not part of this proposal): this session's `wikitoolkit` MCP server failed to spawn because `${CLAUDE_PROJECT_DIR}` in `.mcp.json` was not expanded, even though `.venv/bin/wikitoolkit` exists. Unrelated to rustworkx, but worth a separate ticket.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-471`** — *Rationale*: localization is high-confidence and fully reproduced; the change is a small, bounded dependency-metadata fix (two `pyproject.toml` edits + lock refresh + a bare-install regression test). No architectural fork to explore — U1/U2 are one-line decisions the spec can settle.

### Alternatives

- **`/sdd-task FEAT-471`** — if U1=a and U2 is deferred, this is a one-or-two-task fix suitable for direct decomposition.
- **`/sdd-brainstorm FEAT-471`** — only if the team wants to revisit the whole core-vs-extras boundary for `graphindex` (lazy `__init__`, guarded imports across 9 sites).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-471/state.json` |
| Source (raw) | `sdd/state/FEAT-471/source.md` |
| Research plan | `sdd/state/FEAT-471/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-471/findings/F001-*.md` … `F007-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-471/synthesis.json` |

**Budget consumed**:
- Files read: 6 / 40
- Grep calls: 9 / 25
- Git calls: 1 / 10
- Wall time: ~240s / 300s
- Truncated: **no**
- Wiki: unavailable this session (MCP spawn failure) — fell back to grep/read.

**Mode determination**: `auto` → resolved to `investigation` (defect verbs: "no instala", "desinstala", "reparar").

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (via Claude Code, autonomous run) |
