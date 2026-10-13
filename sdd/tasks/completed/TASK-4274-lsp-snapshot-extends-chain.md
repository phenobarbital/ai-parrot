# TASK-4274: Follow pyrightconfig.json extends chain in manifest

**Feature**: FEAT-658 — lsp-toolkit-tech-debt
**Spec**: sdd/specs/lsp-toolkit-tech-debt.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: agent

## Context

`_is_manifest_relevant` in `snapshot.py` matches `pyrightconfig.json` by
basename but doesn't follow the `extends` key. A config layering via
`extends` (e.g. `pyrightconfig.json` → `base.json`) wouldn't trigger session
invalidation when the referenced file changes, because `base.json` doesn't
match the fixed basename set.

Resolves ledger issue:5bb51322e7b0.

## Scope

When `pyrightconfig.json` is in the manifest, read its `extends` key and add
referenced paths to the manifest set, following the chain up to depth 5.

### NOT in scope
- Other JSON config files (tsconfig, etc.)
- Network-located extends references

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py` | MODIFY | Follow extends chain |
| `packages/ai-parrot-tools/tests/lsp/test_snapshot.py` | MODIFY | Add extends chain tests |

## Codebase Contract

### Verified Imports
- `parrot_tools.lsp.snapshot._is_manifest_relevant` — function at line 171
- `parrot_tools.lsp.snapshot._build_manifest` — async function at line 151

### Existing Signatures
- `def _is_manifest_relevant(rel_path: str) -> bool` (line 171)
- `async def _build_manifest(repo_root: Path) -> tuple[set[str], set[str]]` (line 151)

## Implementation Notes

Add a new helper `_follow_extends_chain(repo_root: Path, manifest: set[str]) -> set[str]`
that:
1. For each `pyrightconfig.json` path in the manifest, reads the file
2. Parses JSON, extracts `extends` value (a relative path string)
3. Resolves the extended path relative to the pyrightconfig.json's directory
4. If the resolved path is within repo_root AND is not already in manifest, adds it
5. Follows the chain recursively up to depth 5
6. Returns the augmented manifest set
7. Silently ignores JSON parse errors or missing files (these are manifest
   candidates, not validation targets)

Call this from `_build_manifest` after the initial manifest is built, before
returning.

## Acceptance Criteria

- [ ] A pyrightconfig.json with `"extends": "base.json"` causes `base.json` to appear in manifest
- [ ] Chain depth > 5 is silently truncated
- [ ] Missing or malformed JSON in extended files doesn't crash
- [ ] Existing snapshot tests pass

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/lsp/test_snapshot.py -x -q
ruff check packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py
```

## Completion Note

(filled by implementing agent)


Completed: implemented as specified; tests in tests/lsp (33 passed).
