# TASK-4057: Document inbox operations and record the MCP follow-up

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4055
**Assigned-to**: unassigned

## Context

Implements spec §3 M9 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC14: Insert an Inbox ingestion guide subsection and TOC entry before Jira Ticket Extraction. Document command options, full inbox config, default/custom taxonomy, tag graph, ADR review, archive layout, collision naming, git staging without commit, and dry-run/no-archive/force.
- Explain exit codes, whole-run processor lock, nonblocking acquisition, per-document failures, verification-before-archive, SQLite transaction guarantees and best-effort memory/ArangoDB retry behavior. Warn custom markdown_dir must be excluded from build scanning.
- Add one Spanish cheatsheet command line after the upsert example. Keep existing guide sections intact.
- AC13: Open exactly one deferred wiki_inbox MCP ledger issue (kind tech_debt, severity low, discovered-from spec:FEAT-626, about tools.py). Check ledger CLI help and existing open issues first; reuse an identical issue rather than duplicating it. Record returned issue id in completion evidence; do not implement MCP or close the issue.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/guides/llm-wiki-guide.md` | MODIFY | Scoped M9 deliverable |
| `docs/wiki/cheatsheet.md` | MODIFY | Scoped M9 deliverable |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No Python imports; modify only the documented guide anchors below.

### Existing Signatures to Use

No existing repository symbols are imported by this task. Pydantic v2, pytest and standard-library contracts apply.

### Does NOT Exist

- wiki_inbox MCP tool is not implemented by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/guides/llm-wiki-guide.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/wiki/cheatsheet.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Documents final inbox options and exit behavior from TASK-4055. Exclusive: opens/reuses an item in the shared SDD work ledger outside declared documentation files.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `docs/guides/llm-wiki-guide.md` (MODIFY)

Verified attachment points (literal `grep -F -c` counts):

- `  - [Jira Ticket Extraction (wikitoolkit ingest-jira)](#jira-ticket-extraction-wikitoolkit-ingest-jira)` — occurrences: 1; `docs/guides/llm-wiki-guide.md:50`.
- `### Jira Ticket Extraction (wikitoolkit ingest-jira)` — occurrences: 1; `docs/guides/llm-wiki-guide.md:1015`.
```markdown
# MODIFY TOC: insert before the existing Jira Ticket Extraction TOC row.
  - [Inbox ingestion (wikitoolkit inbox)](#inbox-ingestion-wikitoolkit-inbox)

# MODIFY BODY: insert before ### Jira Ticket Extraction (wikitoolkit ingest-jira).
### Inbox ingestion (wikitoolkit inbox)

Drop documents into the configured `inbox/` directory, then run `wikitoolkit inbox`.
Use `wikitoolkit inbox --dry-run --json` to inspect planned outcomes.

<!-- FILL IN: AC14 command/options, config and taxonomy examples, archive/git lifecycle,
verification, retry/force semantics, tags/ADR review, exit codes, custom projection exclusions
and backend-dependent crash safety; follow the final CLI contract. -->
```

**Why**: Document the operational contract beside existing ingestion modes so users can distinguish drop-box ingestion from supervised ingest.

### `docs/wiki/cheatsheet.md` (MODIFY)

Verified attachment points (literal `grep -F -c` counts):

- `wikitoolkit upsert path/a/archivo.py path/b/otro.py   # re-ingesta puntual` — occurrences: 1; `docs/wiki/cheatsheet.md:48`.
```markdown
# AFTER the verified upsert example inside the existing bash fence:
wikitoolkit inbox                                  # ingesta inbox/, verifica y archiva originales
```

**Why**: Match the cheatsheet language and retain its existing command sequence.

### FILL IN checklist

- [ ] `docs/guides/llm-wiki-guide.md` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `docs/wiki/cheatsheet.md` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC14: Insert an Inbox ingestion guide subsection and TOC entry before Jira Ticket Extraction. Document command options, full inbox config, default/custom taxonomy, tag graph, ADR review, archive layout, collision naming, git staging without commit, and dry-run/no-archive/force.
- [ ] Explain exit codes, whole-run processor lock, nonblocking acquisition, per-document failures, verification-before-archive, SQLite transaction guarantees and best-effort memory/ArangoDB retry behavior. Warn custom markdown_dir must be excluded from build scanning.
- [ ] Add one Spanish cheatsheet command line after the upsert example. Keep existing guide sections intact.
- [ ] AC13: Open exactly one deferred wiki_inbox MCP ledger issue (kind tech_debt, severity low, discovered-from spec:FEAT-626, about tools.py). Check ledger CLI help and existing open issues first; reuse an identical issue rather than duplicating it. Record returned issue id in completion evidence; do not implement MCP or close the issue.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Manually compare all documented options/defaults and exit codes against the implemented inbox --help and config model.
- Run the existing packaged CLI regression file as a focused smoke check; this docs task creates no artificial implementation-mirroring tests.
- Execute the M9 ledger command after checking help, persist the returned issue id, and verify it remains open.

Use the spec's M9 ledger payload after verifying local `wikitoolkit ledger open --help`:

```bash
wikitoolkit ledger open --kind tech_debt --severity low \
  --discovered-from spec:FEAT-626 --about file:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py \
  --title "wiki_inbox MCP tool wrapping InboxProcessor (deferred from FEAT-626 — FEAT-569 conflict)" \
  --body "Thin AbstractTool over parrot.knowledge.wiki.inbox.InboxProcessor; dry_run default; register in create_wiki_tools after FEAT-569 merges."
```

## Agent Instructions

1. Use `$sdd-start TASK-4057`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.


### Completion Note (orchestrator)
Seat: gemini-3.5-flash (google-compat). Docs-only; the merge-tier selector rejects docs paths, so the declared command (test_cli.py) was run: 16 passed, 3 failed = the pre-existing TestIngestModelResolutionDetectionFallback failures (issue:66599d4e8c84). Review fix 24e6ab1cb: the delivered guide section invented exit codes/config keys/archive layout/--force semantics; rewritten from cli.py/project.py/archive.py. feedback_id coder-feedback:801e3aaf3944131b44654c58. AC13: deferred wiki_inbox MCP ledger issue:f7477bd7bba4.
