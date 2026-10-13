# LSP Toolkit Tech Debt — FEAT-658

```yaml
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [lsp, tech-debt, logging, paths, ledger-fix]
```

## 1. Problem

Three tech-debt issues from the FEAT-580 adversarial review of the LSP toolkit:

1. **No logging** (issue:f00bb9ef1e72, major) — `LSPToolkit` is a 947-line stateful
   component with zero `self.logger` calls. Session start, restart, close, idle
   shutdown, and `LSPFailure → LSPResult` conversions are all silent. Both
   `PyrightSession` and `_ToolkitStdioMCPServer` log correctly; `LSPToolkit` is
   the outlier.

2. **Path asymmetry** (issue:528a3a206a6d, minor) — `_relative_to_root` resolves
   the candidate path via `.resolve()` and compares against `_canonical_root`
   (also resolved), but `_uri_for_path` builds from the unresolved
   `self._config.repo_root / path`. With symlinks these can diverge.

3. **Extends chain** (issue:5bb51322e7b0, minor) — `_is_manifest_relevant` in
   `snapshot.py` matches `pyrightconfig.json` by basename but doesn't follow the
   `extends` key. A config referenced by `extends` from a different filename
   wouldn't trigger session invalidation on change.

## 2. Solution

### M1 — Add structured logging to LSPToolkit (toolkit.py)

Add `self.logger` calls at key lifecycle points:
- `_open()` / `_ensure_session_locked()`: `debug` on cold start vs. cache hit
- `_close()` / `_close_session_locked()`: `debug` on session teardown
- `_idle_shutdown()`: `debug` when idle timer fires
- `_failure_result()`: `warning` with operation name, code, and detail

### M2 — Resolve path symmetry (toolkit.py)

In `_uri_for_path`, use `self._canonical_root / path` (the resolved root)
instead of `self._config.repo_root / path`, matching the resolution
`_relative_to_root` already does. Guard with the same `_canonical_root is not None`
assertion.

### M3 — Follow pyrightconfig extends chain (snapshot.py)

In `_is_manifest_relevant` (or its caller `_build_manifest`), when a path is
`pyrightconfig.json`, read its `extends` key (if present) and add those
referenced paths to the manifest set. Limit depth to 5 to avoid cycles.

## 3. Files

| File | Module | Action |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py` | M1, M2 | MODIFY |
| `packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py` | M3 | MODIFY |
| `packages/ai-parrot-tools/tests/lsp/test_toolkit_logging.py` | M1 | CREATE |
| `packages/ai-parrot-tools/tests/lsp/test_snapshot.py` | M3 | MODIFY |

## 4. Acceptance Criteria

- AC1: `grep -c 'self\.logger\.' toolkit.py` returns ≥ 4 (start, close, idle, failure)
- AC2: `_uri_for_path` uses `_canonical_root`, never unresolved `repo_root`
- AC3: A pyrightconfig.json with `"extends": "base.json"` causes `base.json` to appear in
  the manifest set
- AC4: `extends` chain depth > 5 is silently truncated, not a crash
- AC5: `ruff check packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py` passes
- AC6: Existing LSP tests pass: `PYTHONPATH=packages/ai-parrot-tools/src pytest packages/ai-parrot-tools/tests/lsp/ -x -q`
