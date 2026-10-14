# TASK-4342: Document reviewer repository cache and degradation

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec §3 M7 within the approved external-plane design. Document reviewer repository cache and degradation.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Append all seven settings and defaults to the existing table — operators need the opt-in and resource limits in one place.
- Describe clone/plane/lock layout, remote-default branch behavior, lean builds, incomplete markers, timeout fallback and LRU exceptions.
- Document the snapshot caveat, confined full wiki tools, private auth path and local executable requirements; link the configuration to failure behavior.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/github-reviewer.md` | MODIFY | Document reviewer repository cache and degradation |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No imports: documentation-only deliverable.

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

The configuration table in docs/github-reviewer.md is the existing documentation attachment point.
### Does NOT Exist

- `build_wiki()` or `run_build()` repository-scan API: use the CLI subprocess.
- `GitToolkit.checkout_ref()` and clone `sha=`/`ref=`: PR heads are out of scope.
- `WIKI_ROOT` or `PARROT_WIKI_ROOT`: pass explicit paths/config/store.
- `CodeStructuralToolkit(repository=...)`: constructor takes root/store/config.
- New repo_cache/repo_build symbols and seven GITHUB_REVIEW wiki settings are absent at planning time; rely on prerequisites before importing them.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/github-reviewer.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Describe --storage-dir as run-scoped and not persisted. Defaults: disabled; ~/.cache/parrot/github-reviewer; remote default branch; full history; 5 GiB; 900 seconds; 4000 tokens. Explain roughly four ai-parrot-sized repositories, keep/locked-entry protection and oversized-entry warning. Documentation only; do not add code tests that mirror prose.

**Parallelism**: Independent docs/github-reviewer.md writer; documents the approved spec without importing or testing a feature-created symbol. Existing reviewer tests are a smoke check only, so no implementation edge is needed.

## Implementation Blueprint

### Steps (in order)

1. Append all seven settings and defaults to the existing table — operators need the opt-in and resource limits in one place.
2. Describe clone/plane/lock layout, remote-default branch behavior, lean builds, incomplete markers, timeout fallback and LRU exceptions.
3. Document the snapshot caveat, confined full wiki tools, private auth path and local executable requirements; link the configuration to failure behavior.

### `docs/github-reviewer.md` (MODIFY)

```markdown
# Anchor: | `GITHUB_REVIEW_REPOSITORY`             | Default `owner/name` watched by the bundled subclass                        |
# occurrences: 1 (verified with grep -Fxc; docs/github-reviewer.md:110)
| `GITHUB_REVIEW_WIKI_ENABLED` | Opt in to codebase context; default false. |
| `GITHUB_REVIEW_CACHE_DIR` | Cache root; default ~/.cache/parrot/github-reviewer. |
| `GITHUB_REVIEW_CLONE_BRANCH` | Remote default HEAD unless explicitly set. |
| `GITHUB_REVIEW_CLONE_DEPTH` | Full history unless a depth is set. |
| `GITHUB_REVIEW_CACHE_MAX_BYTES` | Soft cap of 5 GiB with locked/current-entry protection. |
| `GITHUB_REVIEW_BUILD_TIMEOUT` | Build timeout in seconds; default 900. |
| `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS` | Complete injected context budget; default 4000. |

## Codebase context

The wiki describes a base-branch snapshot and does not contain the PR changes.
A symbol added by the PR can therefore be absent from this context.
<!-- FILL IN: describe cache layout, recovery, LRU exceptions and degradation per AC-14. -->
```

**Why**: Operators need explicit defaults, disk costs and the snapshot limitation before enabling enrichment.

### FILL IN checklist

- [ ] Append all seven settings and defaults to the existing table — operators need the opt-in and resource limits in one place.
- [ ] Describe clone/plane/lock layout, remote-default branch behavior, lean builds, incomplete markers, timeout fallback and LRU exceptions.
- [ ] Document the snapshot caveat, confined full wiki tools, private auth path and local executable requirements; link the configuration to failure behavior.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-14: `docs/github-reviewer.md` documents the seven settings, the cache layout, the degradation contract and the base-branch caveat.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

## Test Specification


Manually check seven defaults, CLI non-persistence, layout and caveat against the approved spec. The pytest command is the existing reviewer smoke test, not a prose test.

## Agent Instructions

1. Use `$sdd-start TASK-4342` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Pending implementation; the finalizer records evidence after validation.
