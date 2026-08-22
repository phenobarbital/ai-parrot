# TASK-2318: Bump async-notify pin to >=1.6.0 + add runtime version guard

**Feature**: commcenter-post-launch-fixes
**Feature ID**: FEAT-445
**Spec**: (follow-up to sdd/specs/commcenter-notify.spec.md — FEAT-417)
**Status**: [ ] pending
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

CommCenter enqueues an inline Jinja2 template string in the xadd payload
(`"template": "Hello {{ name }}"`).  async-notify < 1.6.0 silently ignores
that key and looks for a `template_file` in `TEMPLATE_DIR` — finding none, it
delivers an **empty body** with no error on either side.

async-notify 1.6.0 was released with FEAT-003 ("Inline Jinja2 template source
for send()"), which is exactly the capability CommCenter relies on.

The current pin in `ai-parrot-server[comm-center]` is `async-notify>=1.5.5`.
The navigator-api venv was running 1.5.5 at ship time.

## Scope

1. **Bump the dependency pin** in
   `packages/ai-parrot-server/pyproject.toml` from `async-notify>=1.5.5`
   to `async-notify>=1.6.0` (the `comm-center` extra).
2. Also bump the base pin in `packages/ai-parrot/pyproject.toml` if it
   carries a lower floor (`>=1.4.2` → `>=1.6.0`), and the `[all]` extra
   (`>=1.5.2` → `>=1.6.0`).
3. **Add a runtime version check** in the CommCenter service init path
   (e.g. `dispatch.py` or `comm_center.py` handler setup) that:
   - Imports `async_notify.__version__` (or `importlib.metadata`)
   - Raises a clear `RuntimeError` if the installed version is < 1.6.0
   - Message: `"CommCenter requires async-notify >= 1.6.0 for inline
     Jinja2 template support (installed: {version}). Upgrade with:
     pip install 'async-notify>=1.6.0'"`
4. **Update `docs/comm_center.md`** to document the 1.6.0 minimum.

## Files to Create/Modify

- `packages/ai-parrot-server/pyproject.toml` — bump comm-center extra pin
- `packages/ai-parrot/pyproject.toml` — bump base + all extra pins
- `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` or
  `packages/ai-parrot-server/src/parrot/services/comm_center/dispatch.py`
  — runtime version check
- `docs/comm_center.md` — document version requirement
- `packages/ai-parrot-server/tests/handlers/test_comm_center_*.py` — test
  for the version guard

## Implementation Notes

- Use `importlib.metadata.version("async-notify")` and
  `packaging.version.Version` for the comparison — avoid regex on version
  strings.
- The check should run at **import time or first use**, not at every
  request. A module-level guard in `dispatch.py` is the natural place
  since that's where `xadd` happens.
- The existing lazy-import guard already catches "not installed" → 503.
  The version guard should sit right after that check.

## Acceptance Criteria

- [ ] `pyproject.toml` pins `async-notify>=1.6.0` in all relevant extras
- [ ] Runtime version check raises `RuntimeError` with a clear message
      when async-notify < 1.6.0 is installed
- [ ] A test mocks `importlib.metadata.version` to return "1.5.5" and
      asserts the RuntimeError is raised
- [ ] `docs/comm_center.md` mentions the 1.6.0 minimum
- [ ] `uv lock` succeeds with the new pins
