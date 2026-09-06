# TASK-2896: Measure Luau parser limits and declare the optional grammar

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2897, TASK-2900, TASK-2901, TASK-2902, TASK-2903, TASK-2904, TASK-2905, TASK-2908 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements spec sections 3.1 and 8 measurement-first decision. No production scanner or runtime guard implementation in this task. The report is the contract handed to TASK-2898 and TASK-2899. No user approval is needed to run the already-approved measurement; approval of its resulting resource policy is the recorded downstream execution gate.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Add tree-sitter-luau>=1.2 only to the approved optional wiki-languages extra and update the lockfile with uv; keep the base installation optional.
- Measure valid, malformed, deeply nested, long-line and incompatible Lua samples, including the brainstorm size progression and an approximately 842 KB pathological sample. Generate fixtures locally; do not vendor external code or platform dumps.
- Run each native parse in a killable benchmark subprocess with an external deadline. Verify the supported runtime versions and cancellation/reset mechanism; a cancelled future or thread does not terminate a native parser.
- Produce a concrete combined policy: pre-parse byte limit, ERROR-node density calculation and threshold, enforced parse deadline, fallback input bound, mapping JSON byte/depth limits. Treat 32 KiB as a hypothesis, not an accepted bound.
- Record timings, hardware/runtime versions, worst cases and cleanup behavior in artifacts/logs; commit a concise reproducible policy report and benchmark runner. Record review of the measured policy before marking this prerequisite done; if review is outstanding leave dependent scanner/mapping work gated.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Only wiki-languages grammar requirement |
| `uv.lock` | MODIFY | Regenerate with workspace tooling |
| `scripts/benchmarks/luau_parser_limits.py` | CREATE | Deterministic corpus and isolated measurement runner |
| `docs/design/luau-parser-resource-policy.md` | CREATE | Measured bounds, version compatibility and review outcome |
| `tests/knowledge/wiki/roblox/test_resource_corpus.py` | CREATE | Corpus reproducibility and benchmark termination |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.languages.treesitter import get_parser
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py:64` — `def get_parser(language: str) -> Parser | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py:86` — `def _build_parser(language: str) -> Parser | None:`
- `packages/ai-parrot/pyproject.toml:271` — `wiki-languages = [`
- `pyproject.toml:60` — `[dependency-groups]`
- `uv.lock:1` — `version = 1`

### Existing Owned Files

- `packages/ai-parrot/pyproject.toml:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `uv.lock:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.

### Prerequisite Interfaces (new, not existing today)

- No prerequisite task outputs.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/` and `packages/ai-parrot/src/parrot/knowledge/wiki/languages/luau.py` do not exist on the decomposition base; proposed symbols become usable only after their owning tasks complete.
- `LanguageOutline.metadata` and `LanguageOutline.external_edges` do not exist. Its `refs` field is for structural symbol references.
- `resolve_import()` does not accept arbitrary wiki destinations; existing import-edge construction wraps a repository-relative target in `file:`.
- Foreign edge writes and destination-aware neighbor hydration are not existing federation guarantees; TASK-2903 through TASK-2905 establish them.
- `WikiPageRecord` is defined in `store.py`, not wiki `models.py`, and has no arbitrary metadata field.

## Implementation Notes

### Pattern to Follow

Use the verified APIs above and the typed contracts delivered by dependencies.
Follow existing scanner fallback, source-owned slice replacement, namespace
configuration and temporary SQLite test patterns where applicable. Keep
synchronous scanning separate from async acquisition; offload substantial
blocking work in async orchestration. Use ordinary Python logging, Pydantic
models and explicit type annotations; Python 3.11+ and Black/isort conventions.

### Key Constraints

- Preserve the scanner ABC and existing file-page identities.
- Never execute Roblox code or invoke Rojo/luau-lsp/git for runtime acquisition.
- Never mutate foreign API pages while writing local references.
- Use generated tiny fixtures, not vendored API dumps or upstream code archives.
- You are not alone in the codebase: preserve others' changes and coordinate
  shared-file/index updates. FEAT-531 concurrently touches wiki CLI behavior.
- Respect any recorded measurement-review execution gate before implementation.

### References in Codebase

Use the paths and exact signatures in this task's Codebase Contract. The full
spec supplies rationale; final owner decisions in section 8 are binding.

## Acceptance Criteria

- [ ] The complete scoped deliverable is implemented with no production stubs.
- [ ] The same parameters yield identical bytes and documented case sizes.
- [ ] A deliberately stalled parser exits within the outer deadline, leaves no child running and records timeout.
- [ ] A timeout/error case is followed by a valid parse without stale parser state.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_resource_corpus.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2896-luau-resource-measurement.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_corpus_is_repeatable` | The same parameters yield identical bytes and documented case sizes. |
| `test_benchmark_kills_stuck_child` | A deliberately stalled parser exits within the outer deadline, leaves no child running and records timeout. |
| `test_following_parse_is_clean` | A timeout/error case is followed by a valid parse without stale parser state. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2896-luau-resource-measurement.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
