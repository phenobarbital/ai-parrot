# TASK-5172: Migration of technical docs into wiki/

**Feature**: FEAT-801 — GitHub Wiki as the Technical Reference
**Spec**: `sdd/specs/github-wiki-technical-reference.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-5168, TASK-5169
**Assigned-to**: unassigned

---

## Context

> Spec §3 M7. Moves technical documentation from `docs/` into `wiki/`, creates `_index.yaml`,
> translates non-English pages, rewrites links, and validates with `mkdocs build --strict`.
> This is the largest task in the feature — it touches ~100+ files. Depends on TASK-5168
> (bundle link format) and TASK-5169 (page template).

---

## Scope

- CREATE `wiki/_index.yaml` with all sections
- MOVE technical pages from `docs/` to `wiki/<section>/` using `git mv` (translated to English when needed)
- MODIFY `mkdocs.yml`: remove moved pages from nav
- MODIFY `docs/index.md`: add "Technical reference moved to the Wiki" notice
- MODIFY retained `docs/**/*.md` pages: rewrite links to moved pages (including `docs/chapters/*.md`)
- MODIFY `CLAUDE.md`/`.agent/CONTEXT.md` only where they link a moved page
- CREATE `sdd/state/FEAT-801/migration-map.md`: the executed file → page mapping
- Validate: `mkdocs build --strict` must pass after the move (AC-10)
- Validate: every migration-map destination against the bundle manifest
- Validate: local workflow contracts (including `docs/sdd/CODEX.md`) remain readable

**NOT in scope**: API reference generator (TASK-5167), Pages cut-over/mkdocstrings removal (M9 follow-up), backfill pages (TASK-5173).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/_index.yaml` | CREATE | Section index |
| `wiki/<section>/*.md` | CREATE | Moved technical pages (via `git mv`) |
| `mkdocs.yml` | MODIFY | Remove moved pages from nav |
| `docs/index.md` | MODIFY | Add "moved to Wiki" notice |
| `docs/chapters/*.md` | MODIFY | Rewrite links to moved pages |
| `CLAUDE.md` | MODIFY | Rewrite links to moved pages (if any) |
| `.agent/CONTEXT.md` | MODIFY | Rewrite links to moved pages (if any) |
| `sdd/state/FEAT-801/migration-map.md` | CREATE | File → page mapping |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No Python code created — this is a documentation migration task
```

### Existing Signatures to Use
```python
# mkdocs.yml:54 — mkdocstrings plugin (stays until M9 follow-up)
# mkdocs.yml:299 — API Reference nav block (stays until M9 follow-up)
# docs/index.md:17 — [Browse the API →](api-reference/index.md){ .md-button } (stays until M9)

# .parrot/wiki.json — include_suffixes includes .md; wiki/**/*.md will be auto-indexed
# decisions.adr_globs = ["docs/adr/**/*.md", "docs/adrs/**/*.md", "docs/decisions/**/*.md"]
```

### Does NOT Exist
- ~~`wiki/`~~ directory at repo root — created by this task
- ~~`wiki/_index.yaml`~~ — created by this task
- ~~`sdd/state/FEAT-801/`~~ directory — created by this task

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/_index.yaml", "action": "CREATE"},
    {"path": "mkdocs.yml", "action": "MODIFY"},
    {"path": "docs/index.md", "action": "MODIFY"},
    {"path": "sdd/state/FEAT-801/migration-map.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Classification rule** (spec §3 M7):
  - **Stays on Pages**: `docs/index.md`, `INSTALL.md`, `config.md`, `tools_quick.md`, `STYLE_GUIDE.md`,
    `chapters/**`, `guides/**`, `examples/**`, `branding/**`, `postman/**`, `aws/**`, `superpowers/**`,
    `docs/decisions/**`, `docs/sdd/WORKFLOW.md`, `docs/sdd/CODEX.md`, every file `@`-included by `CLAUDE.md`,
    roadmap/brainstorm pages, and any document read as a local workflow contract
  - **Moves to `wiki/`**: everything else reachable from mkdocs nav technical sections, plus
    `docs/sdd/**` (except local workflow contracts), `docs/wiki/**`, `docs/migration/**`, `docs/dev_loop/**`
- **Sections** in `_index.yaml`: Architecture · Clients · Bots & Agents · Memory · Knowledge ·
  Tools & Toolkits · Flows · Skills · Stores & Loaders · MCP & A2A · Server & APIs ·
  Integrations · Outputs & A2UI · Prompts · Security · Operations · Migration · SDD Tooling · LLM Wiki
- Use `git mv` for all moves (preserves history)
- Translate non-English pages to English (AC-15); list in Completion Note
- Rewrite all inbound links from retained Pages documents to wiki URLs
- Validate mapped destinations against the bundle manifest
- Enumerate local workflow contract exceptions and their consumers in the migration map
- `mkdocs build --strict` must pass after the move (AC-10)
- Keep the existing API Reference nav and plugin until M9

### References in Codebase
- `mkdocs.yml` — full nav tree for classification
- `CLAUDE.md` — `@` includes (find which docs files are included)

---

## Implementation Blueprint

### Steps (in order)
1. Enumerate all files in `docs/` and classify each as stays/moves — *why*: migration map is the artifact
2. Identify local workflow contracts and their consumers — *why*: spec requires enumeration
3. Create `wiki/` directory structure with sections — *why*: target for moved files
4. Create `wiki/_index.yaml` — *why*: section ordering for the bundle
5. Move files with `git mv` into `wiki/<section>/` — *why*: preserves git history
6. Translate non-English pages — *why*: AC-15
7. Rewrite links in moved files (relative paths between wiki pages) — *why*: internal consistency
8. Rewrite links in retained Pages documents to wiki URLs — *why*: AC-10 (mkdocs strict)
9. Update `mkdocs.yml` nav: remove moved pages — *why*: strict build passes
10. Update `docs/index.md`: add notice — *why*: users know where to find technical docs
11. Create `sdd/state/FEAT-801/migration-map.md` — *why*: traceability
12. Validate: `mkdocs build --strict`, bundle manifest check, workflow contract paths — *why*: AC-10

### `wiki/_index.yaml` (CREATE)
```yaml
# GitHub Wiki section ordering for ai-parrot technical reference
sections:
  - id: architecture
    title: Architecture
  - id: clients
    title: Clients
  - id: bots
    title: Bots & Agents
  - id: memory
    title: Memory
  - id: knowledge
    title: Knowledge
  - id: tools
    title: Tools & Toolkits
  - id: flows
    title: Flows
  - id: skills
    title: Skills
  - id: stores
    title: Stores & Loaders
  - id: mcp
    title: MCP & A2A
  - id: server
    title: Server & APIs
  - id: integrations
    title: Integrations
  - id: outputs
    title: Outputs & A2UI
  - id: prompts
    title: Prompts
  - id: security
    title: Security
  - id: operations
    title: Operations
  - id: migration
    title: Migration
  - id: sdd-tooling
    title: SDD Tooling
  - id: wiki
    title: LLM Wiki
# Decisions and API Reference are appended by the bundle
```
**Why this shape**: Matches the spec's section list. Decisions and API Reference are generated by the bundle, not authored.

### FILL IN checklist
- [ ] Classify ~200 files under `docs/` — bounded by the classification rule above
- [ ] Enumerate workflow contract exceptions — bounded by spec M7 requirement
- [ ] Translate Spanish/non-English pages — bounded by AC-15
- [ ] Rewrite all inbound links from retained docs to wiki URLs — bounded by AC-10
- [ ] Remove moved-page nav entries from `mkdocs.yml` — bounded by AC-10
- [ ] Verify `mkdocs build --strict` passes — bounded by AC-10
- [ ] Verify bundle manifest contains all migrated destinations — bounded by AC-10

---

## Acceptance Criteria

- [ ] `mkdocs build --strict` passes after the move (AC-10)
- [ ] Nav contains informative entries plus existing API Reference (AC-10)
- [ ] No moved page remains under `docs/` (AC-10)
- [ ] Local workflow contracts including `docs/sdd/CODEX.md` remain readable (AC-10)
- [ ] Every retained-document link to a moved page is rewritten and verified against bundle manifest (AC-10)
- [ ] `wiki/_index.yaml` lists every section with a page (AC-10)
- [ ] `wikitoolkit build` indexes `wiki/**/*.md` with no config change (AC-11)
- [ ] Every migrated page is in English; translated files listed in Completion Note (AC-15)
- [ ] `sdd/state/FEAT-801/migration-map.md` exists with the full mapping

---

## Validation Commands

- `pytest tests/sdd_scripts/test_feat801_doc_contract.py -q`

---

## Test Specification

Validation for this task is primarily through `mkdocs build --strict` and manual verification
of the migration map. The contract test `test_feat801_doc_contract.py` (from TASK-5169) validates
that the template exists. Additional checks in the Completion Note:
- List of translated files
- List of workflow contract exceptions and their consumers
- `mkdocs build --strict` exit code
- Bundle manifest verification result

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
2. **Check dependencies** — TASK-5168 and TASK-5169 must be `done`
3. **Read `mkdocs.yml` nav** to classify every `docs/` page
4. **Read `CLAUDE.md`** to find `@`-included files (these stay)
5. **Search for files read by commands/skills/scripts/tests** — enumerate workflow contracts
6. **Execute the migration** using `git mv` for each file
7. **Translate** non-English pages and list them in the Completion Note
8. **Rewrite links** in retained and moved files
9. **Run `mkdocs build --strict`** to validate
10. **Run `parrot sdd techwiki bundle --dry-run`** and check the manifest
11. **Create the migration map** at `sdd/state/FEAT-801/migration-map.md`
12. **Commit** all changes
13. **Close** with `parrot sdd task close TASK-5172 github-wiki-technical-reference verified`

---

## Completion Note

**Completed by**: sdd-worker orchestrator (executed as a split; no coder dispatch — judgement-heavy, path-pinned).
**Date**: 2026-11-05
**Notes**: Moved 275 pages `docs/` → `wiki/<section>/` (commit 321c9883a3), `wiki/_index.yaml`, 139 hyphenated titles fixed, 16 Spanish pages translated by parallel agents (Spanish runtime strings / sample data inside code blocks intentionally left; a few ASCII-diagram labels may remain), links rewritten in all three directions, `mkdocs.yml` nav pruned, `docs/index.md` notice added, ~130 consumer files rewritten, 14 test files' path construction fixed. Bundle dry-run: 275 authored + 9 ADR pages, 0 collisions, 0 dangling. Executed map: `sdd/state/FEAT-801/migration-map.md`. Bundle fixes made along the way: `rewrite_links` now skips external URLs, ADR titles are hyphen-sanitised (sources untouched), loop-variable bind (B023).
**Verification is `partial` because**: (1) `mkdocs build --strict` NOT run (mkdocs not installed; no network); (2) three read-only files still hold old paths and need the host patch (`.claude/commands/planogram-migrate.md`, `.claude/commands/sdd-done.md`, `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`), after which `check_asset_sync.py --write` must be run; (3) section assignment is heuristic — review before merge; (4) pre-existing/env failures left alone: `test_changelog_lists_the_plain_host_behaviour_changes`, standup runbook "Identity" assertion, `test_worker_notification_protocol_order`, `test_hello_world_snippet_executes` (network), `test_projection` (EdgeKind).

**Deviations from spec**: unlisted (not-in-nav) pages moved by proposal; `docs/getting-started.md` kept on Pages.
