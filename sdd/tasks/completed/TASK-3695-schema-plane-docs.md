# TASK-3695: Operator guide `docs/wiki/schema-plane.md` + CLAUDE.md knowledge-graph paragraph

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3687, TASK-3689
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 / AC15. One operator guide (declare a source, sync, ingest-ddl, diff, lookup, annotate; id grammar; merge rule; security invariants; freshness) and one paragraph in CLAUDE.md's Codebase Knowledge Graph section pointing agents at `wiki_schema_*`.

---

## Scope

- Create `docs/wiki/schema-plane.md`.
- Modify `CLAUDE.md`: add a **Schema plane (FEAT-600).** paragraph right after the **Symbol lookup and blast radius (FEAT-498).** paragraph (CLAUDE.md:404).
- Create `test_docs_present.py` asserting the doc exists and names the six verbs and four tools.

**NOT in scope**: Code changes; `.agent/` twin regeneration (note it in the completion note if AGENTS.md regen is required by FEAT-553 conventions).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/wiki/schema-plane.md` | CREATE | operator guide |
| `CLAUDE.md` | MODIFY | one paragraph |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_docs_present.py` | CREATE | doc presence test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
# none — documentation task
```

### Existing Signatures to Use
```python
# CLAUDE.md:404 — paragraph starting `**Symbol lookup and blast radius (FEAT-498).**` (occurrences: 1) ← insert the new paragraph AFTER it
# docs/wiki/ currently holds cheatsheet.md only
```

### Does NOT Exist
- ~~`docs/wiki/schema-plane.md`~~ — new
- ~~a `wikitoolkit schema` section in `docs/wiki/cheatsheet.md`~~ — optional; not required by AC15

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/wiki/schema-plane.md",
      "action": "CREATE"
    },
    {
      "path": "CLAUDE.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_docs_present.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
`docs/wiki/cheatsheet.md` tone; the CLAUDE.md FEAT-498 paragraph for length and voice.

### Key Constraints
- English; id grammar written exactly as `table:<origin>/<schema>.<table>`; state the merge rule (live wins, DDL fills gaps, diff reports) and G7 (env NAMES only, samples off by default).
- CLAUDE.md paragraph ≤ 8 lines.

### References in Codebase
- sdd/specs/sql-schema-plane.spec.md §2, §5 AC15
- sdd/proposals/schema-plane.brainstorm.md — Feature Description

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Write the guide with sections: Why, Ids, Declare a source, Sync, Offline DDL ingest, Lookup & join paths (MCP + CLI), Annotate, Drift (`diff`), Freshness & repair, Security, Runtime (`DatabaseAgent(schema_plane=…)`).
2. Insert the CLAUDE.md paragraph.
3. Add the presence test.

### `CLAUDE.md` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '**Symbol lookup and blast radius (FEAT-498).**' CLAUDE.md) → CLAUDE.md:404
# AFTER — insert a blank line then this paragraph below the FEAT-498 paragraph:
**Schema plane (FEAT-600).** SQL data models live in a separate overlay plane
(`.parrot/schema/schema.db`) as `source:` / `schema:` / `table:<origin>/<schema>.<table>`
pages. Before writing SQL, a repository, or a `DatabaseToolkit` subclass, read the
table with `wiki_schema_lookup("<origin>:<schema>.<table>")` (DDL, columns, FKs,
annotations, staleness), find join paths with `wiki_schema_neighbors`, and search
names/comments with `wiki_schema_search`. Never introspect `information_schema`
yourself when a page exists. Operator guide: `docs/wiki/schema-plane.md`.
```
**Why**: Agents must be told the plane exists or they keep re-discovering the schema (problem statement §1).

### FILL IN checklist
- [ ] guide body per the Steps outline
- [ ] presence test

---

## Acceptance Criteria

- [ ] `docs/wiki/schema-plane.md` exists and documents id grammar, merge rule, security invariants and the six CLI verbs (AC15)
- [ ] CLAUDE.md paragraph present after the FEAT-498 paragraph
- [ ] presence test green

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_docs_present.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_docs_present.py
from pathlib import Path

def test_guide_mentions_verbs_and_tools():
    text = Path("docs/wiki/schema-plane.md").read_text()
    for verb in ("sources", "add-source", "sync", "ingest-ddl", "diff", "lookup"):
        assert verb in text
    for tool in ("wiki_schema_lookup", "wiki_schema_search", "wiki_schema_neighbors", "wiki_schema_sources"):
        assert tool in text
    assert "table:<origin>/<schema>.<table>" in text
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3687, TASK-3689` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: haiku, backend: native, attempt_uid 97440ff5db0b42c8914722561308ebaf) — content authored by the native coder, delivery fixed and committed by the orchestrator
**Date**: 2026-09-24
**Notes**: Native attempt 1 delivered correct content (operator guide + CLAUDE.md paragraph + presence test) but ALSO committed an out-of-scope `sdd: mark TASK-3695 completed` mutation of `sdd/tasks/` — SDD state is exclusively the orchestrator's responsibility. `coder_merge` correctly rejected the whole delivery as `fidelity_violation`. The orchestrator cherry-picked only the legitimate content commit (`91a81b6be` from the sub-worktree) and additionally fixed a real bug: `test_docs_present.py` used a bare relative `Path("docs/wiki/schema-plane.md")`, which silently resolves against the wrong repo once pytest's fixture chain imports `parrot` (a known navconfig chdir side-effect to the main checkout) — anchored to `Path(__file__).resolve().parents[6]` instead, matching `tests/knowledge/wiki/test_env_call_sites.py`'s existing pattern. Final commit `330f864993aedb126ef0649e0fd204e5de1d5361` touches exactly the 3 declared files.
Both defects recorded as model feedback (`coder-feedback:b1846f17b1b3919b91b20c68`, `coder-feedback:a6b6da465680afb7ea9279b1`). Reviewed via `coder-review:0f0686e7dabe430329c74f95`.
**Verification**: `test_docs_present.py` 1 passed; CLAUDE.md paragraph 7 lines (within the ≤8 constraint); guide mentions all 6 verbs, 4 MCP tools, and the id grammar.

**Post-merge adversarial review fix**: the independent code-review pass found multiple 🟠 major factual defects in `docs/wiki/schema-plane.md` — none of the `add-source` examples match the real CLI (no positional DSN argument exists; `--dialect`/`--dsn-env` are the real required options), `sync`'s documented `--include-views`/`--sample-data`/`--force` options don't exist (sample data is controlled by a source's `include_samples` config allowlist, not a flag), `ingest-ddl`'s documented `--upsert-only` doesn't exist, `diff`'s documented `--json` option doesn't exist (the real option is `--ledger`), the documented `schema lookup --neighbors` CLI flag doesn't exist (join traversal is MCP-only, `wiki_schema_neighbors`), the documented cache-tier order ("plane first, then Redis") is backwards (real order is LRU -> schema cache -> Redis -> plane -> vector store), and the documented `DatabaseAgent(schema_plane=SchemaPlaneConfig(...))` example doesn't match the real API (`schema_plane` accepts a `str`/`Path`/`SchemaPlaneService`, resolved by `_resolve_schema_plane`). All examples and option lists rewritten to match the verified CLI/API signatures (`cli.py`'s `schema_add_source`/`schema_sync`/`schema_ingest_ddl`/`schema_diff`, `cache.py::CachePartition.get()`, `agent.py::_resolve_schema_plane`). Fix commit `235e185b5`. Verified: `test_docs_present.py` still 1 passed (all required verb/tool/grammar substrings preserved).
**Model feedback NOT recorded**: the native haiku attempt (`attempt_uid 97440ff5db0b42c8914722561308ebaf`) that authored the doc's original content is not the same as the review-fix author (the orchestrator itself, verifying against source); `coder_record_feedback` also requires the execution's `execution_id`, not preserved through a context-compaction boundary before this review fix landed. Pattern for a future manual recording: `pattern: "doc-example-not-verified-against-cli-signature"`, model haiku (native), attempt_uid `97440ff5db0b42c8914722561308ebaf`, file `docs/wiki/schema-plane.md`.

**Deviations from spec**: none
