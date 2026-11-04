---
id: F001
query_id: Q001
type: read
intent: "Where is the sdd-worker sandbox mode resolved, and what happens without pyproject.toml?"
executed_at: 2026-11-04T22:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — Sandbox mode is read only from `pyproject.toml` `[tool.parrot.sdd] sandbox`

## Summary

`resolve_sandbox_mode` takes the mode from `PARROT_SDD_SANDBOX_MODE`, else from
`[tool.parrot.sdd] sandbox` in `<repo_root>/pyproject.toml`, else `"required"`.
A repository without `pyproject.toml` has no file in which to persist `"preferred"`;
only the environment variable or `--sandbox` on every launch can change it.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`
  lines: 246-290
  symbol: `resolve_sandbox_mode`
  excerpt: |
    environment_value = (os.environ.get(MODE_ENV) or "").strip().lower()
    ...
    else:
        config_path = repo_root / "pyproject.toml"
        mode = "required"
        source = "default"
        if config_path.is_file():
            ...
            for table in ("tool", "parrot", "sdd"):

- path: `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`
  lines: 31-38
  symbol: `SANDBOX_MODES`
  excerpt: |
    BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"
    MODE_ENV = "PARROT_SDD_SANDBOX_MODE"
    SANDBOX_MODES = ("required", "preferred", "off", "legacy")

- path: `docs/dev_loop/claude-native-sandbox.md`
  lines: 87-92
  symbol: null
  excerpt: |
    Resolution order: `PARROT_SDD_SANDBOX_MODE` ... → `[tool.parrot.sdd]
    sandbox = "required" | "preferred"` in the repository root `pyproject.toml` → `required`. **`off` and `legacy`
    can only be set through `PARROT_SDD_SANDBOX_MODE` or `--sandbox`**

## Notes

`off`/`legacy` are deliberately not settable from a file, because the worktree copy is
writable by the sandboxed session. Any new config home must keep that rule.
