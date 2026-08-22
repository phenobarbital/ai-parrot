# TASK-2318: Bump async-notify pin to >=1.6.0 + add runtime version guard

**Feature**: commcenter-post-launch-fixes
**Feature ID**: FEAT-445
**Spec**: (follow-up to sdd/specs/commcenter-notify.spec.md — FEAT-417)
**Status**: [x] done-with-issues
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

- [x] `pyproject.toml` pins `async-notify>=1.6.0` in all relevant extras
- [x] Runtime version check raises `RuntimeError` with a clear message
      when async-notify < 1.6.0 is installed
- [x] A test mocks `importlib.metadata.version` to return "1.5.5" and
      asserts the RuntimeError is raised
- [x] `docs/comm_center.md` mentions the 1.6.0 minimum
- [ ] `uv lock` succeeds with the new pins — **see Completion Note, this
      one could not be satisfied**

### Completion Note

Bumped `async-notify` to `>=1.6.0` in three places: `ai-parrot-server`'s
`comm-center` extra (the functionally load-bearing one), `ai-parrot`'s
base `dependencies` pin, and `ai-parrot`'s `integrations` extra
(`async-notify[all]`). Added `packaging>=23.0` as an explicit
`ai-parrot-server` dependency (previously an undeclared transitive dep of
the new version-guard code). Added a cached, one-shot
`_check_async_notify_version()` in `dispatch.py`, wired in right after the
existing lazy-import "is it installed at all" check inside
`_get_notify_client()`. Documented the 1.6.0 floor in
`docs/comm_center.md`. Added 4 new tests in `test_comm_center_dispatch.py`
covering: raises on an old installed version, passes on a satisfying
version, the one-shot cache is honored, and `_get_notify_client()` itself
enforces the guard.

**⚠️ Flagging the last acceptance criterion as NOT satisfiable in this
environment right now** (Cardinal Rule 4 — stopping to report rather than
papering over):

1. `uv lock --dry-run` on this workspace **already fails at baseline**,
   before any of this task's changes, due to a pre-existing, unrelated
   conflict: `ai-parrot[gemma4]` and `ai-parrot[security]` require
   incompatible `huggingface-hub` ranges (verified by stashing every
   change in this feature and re-running `uv lock --dry-run` against an
   unmodified worktree). This is out of this task's scope to fix.
2. Independently, bumping `async-notify` to `>=1.6.0` *anywhere* in the
   workspace's dependency graph — verified by testing the bump isolated to
   just the `comm-center` extra, with every other pin reverted — surfaces
   a second, genuine conflict: `async-notify[all]==1.6.0` (the only
   version satisfying `>=1.6.0`) requires `azure-identity>=1.23.0`, while
   `flowtask>=5.12.3` (pulled in via `ai-parrot[flowtask]`) pins
   `azure-identity==1.20.0` exactly. Since `ai-parrot[flowtask]` and some
   extra requiring `async-notify[all]` (e.g. `ai-parrot[all-fast]` /
   `ai-parrot-server[all]`) are both required somewhere in this
   workspace's universal resolution, `uv` cannot find a version of
   `async-notify` that satisfies both `>=1.6.0` and the `azure-identity`
   constraint chain. This reproduces identically regardless of *which*
   pyproject.toml line carries the `>=1.6.0` floor.

Neither issue is fixable within this task's scope (touching `flowtask`'s
or `ai-parrot[gemma4]`/`[security]`'s pins is a separate, unrelated
concern). The pins are still correct as the target floor for when
`async-notify>=1.6.0` becomes resolvable; the runtime version guard
(criteria 2-3 above) provides defense in depth regardless of what actually
gets installed. No `uv.lock` file was modified — `uv lock`/`--dry-run`
failing never writes a partial lockfile, so the existing lockfile is
untouched. Recommend a follow-up ticket to resolve the `flowtask`
`azure-identity` pin conflict before this pin bump can be locked.

**Post-completion code-review fixes**:
1. `ai-parrot[notify-all]`'s `async-notify[all]>=1.4.2` pin was missed by
   the original "all relevant extras" pass (only the base `ai-parrot`
   pin, `ai-parrot[integrations]`, and `ai-parrot-server[comm-center]`
   were bumped). Bumped to `>=1.6.0` for consistency — this does not
   change the `uv lock` outcome above (the conflict already reproduces
   from the other three pins regardless), but it does close the AC's
   literal "all relevant extras" wording.
2. `docs/comm_center.md` claimed the version guard's `RuntimeError` is
   "mapped to `503`" — tracing both `_get_notify_client()` call sites
   (`dispatch.fan_out` for bulk send, `dispatch.publish_one` for single
   send) shows this is inaccurate: on the bulk path it fires inside the
   backgrounded fan-out task (after the `202` has already been returned)
   and is absorbed into per-row retry bookkeeping; on the single-send
   path it is caught by the generic publish-failure handler and mapped
   to `502`, not `503`. Corrected the doc to describe actual behavior on
   both paths.
