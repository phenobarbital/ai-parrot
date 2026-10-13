# TASK-4273: Fix path resolution asymmetry in LSPToolkit

**Feature**: FEAT-658 — lsp-toolkit-tech-debt
**Spec**: sdd/specs/lsp-toolkit-tech-debt.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: XS
**Depends-on**: none
**Assigned-to**: agent

## Context

`_relative_to_root` resolves the candidate path via `.resolve()` and compares
against `_canonical_root` (also resolved at line 833). But `_uri_for_path`
builds from the unresolved `self._config.repo_root / path` (line 936). With
symlinks these can diverge: a round-trip through `_uri_for_path` →
`_relative_to_root` could silently fail.

Resolves ledger issue:528a3a206a6d.

## Scope

Use `_canonical_root` in `_uri_for_path` to match the resolution path used by
`_relative_to_root`.

### NOT in scope
- Changing `_relative_to_root` logic
- Canonicalizing LSPConfig.repo_root at construction time

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py` | MODIFY | Fix `_uri_for_path` |

## Codebase Contract

### Verified Imports
- `parrot_tools.lsp.toolkit.LSPToolkit._uri_for_path` — method at line 934
- `parrot_tools.lsp.toolkit.LSPToolkit._relative_to_root` — method at line 849
- `parrot_tools.lsp.toolkit._path_to_file_uri` — module-level function

### Existing Signatures
- `def _uri_for_path(self, path: str) -> str` (line 934)
- `def _relative_to_root(self, uri: str) -> str | None` (line 849)

## Implementation Notes

Change line 936 from:
```python
return _path_to_file_uri(self._config.repo_root / path)
```
to:
```python
root = self._canonical_root if self._canonical_root is not None else self._config.repo_root
return _path_to_file_uri(root / path)
```

This ensures the URI is built from the same resolved root that
`_relative_to_root` compares against.

## Acceptance Criteria

- [ ] `_uri_for_path` uses `_canonical_root` when available
- [ ] Existing LSP tests pass

## Validation Commands

```bash
ruff check packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/lsp/ -x -q -k 'not benchmark'
```

## Completion Note

(filled by implementing agent)
