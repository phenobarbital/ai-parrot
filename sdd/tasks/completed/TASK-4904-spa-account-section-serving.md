# TASK-4904: Serve the SPA shell for `/account` (`SPA_SECTIONS`)

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, AC08. `setup_admin_ui()` only serves `index.html` (and only excludes from auth)
the sections in `SPA_SECTIONS`; a hard reload of `/account/security` currently 404s. The constant
must mirror `config.appSections` (TASK-4903 adds `"account"` on the UI side). No code edge between
the two tasks; both ship in the same PR.

---

## Scope

- `SPA_SECTIONS = ("/login", "/agents", "/account")`.
- Extend `test_admin_ui_serving.py`: `/account/security` served; `/accounts` lookalike neither served nor excluded; exclusion list contains `/account` and `/account/*`.

**NOT in scope**: any UI file, `_spa_paths` / `_auth_exclusion_patterns` logic (they iterate `SPA_SECTIONS` already).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/ui/serving.py` | MODIFY | Add `/account` to `SPA_SECTIONS` |
| `packages/ai-parrot-server/tests/test_admin_ui_serving.py` | MODIFY | Cover `/account` and the `/accounts` lookalike |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.server.ui import serving, setup_admin_ui   # test_admin_ui_serving.py:16 (existing)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/server/ui/serving.py
SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents")                        # :39
def _spa_paths(prefix: str, *, mount_root: bool) -> list[str]                # :124 — section + f"{section}/{{tail:.*}}"
def _auth_exclusion_patterns(prefix: str, *, mount_root: bool) -> list[str]  # :141 — section + f"{section}/*"
def setup_admin_ui(app: web.Application, *, prefix: str = DEFAULT_PREFIX, mount_root: bool | None = None) -> bool  # :235

# packages/ai-parrot-server/tests/test_admin_ui_serving.py
#   :67-69  @pytest.mark.parametrize("path", ["/", "/login", "/agents", "/agents/helpdesk/chat", "/admin/home"])
#           async def test_user_sections_served_at_root(self, fake_dist, aiohttp_client, path)
#   :86     for path in ("/not-a-ui-page", "/agentsfoo", "/api/v1/missing"):   (must 404)
#   :192    for pattern in ("/admin", "/admin/*", "/login", "/agents", "/agents/*", "/ui/assets/*"):  (in exclude list)
#   :198    for path in ("/administer", "/agentsfoo", "/api/v1/bots", "/api/v1/login"):  (must NOT match any pattern)
# fixtures: fake_dist (:20), aiohttp_client (pytest-aiohttp), asyncio_mode = "auto" (pyproject.toml:139)
```

### Does NOT Exist
- ~~`SPA_SECTIONS` containing `/account`~~ — added here.
- ~~a separate account router in `serving.py`~~ — sections are generic; only the tuple changes.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/server/ui/serving.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/test_admin_ui_serving.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/server/ui/serving.py#setup_admin_ui",
    "sym:packages/ai-parrot-server/src/parrot/server/ui/serving.py#_spa_paths",
    "sym:packages/ai-parrot-server/src/parrot/server/ui/serving.py#_auth_exclusion_patterns"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit the tuple — *why*: both helpers iterate it.
2. Extend the four test sites — *why*: AC08 lookalike protection (`/accounts`).

### `packages/ai-parrot-server/src/parrot/server/ui/serving.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'SPA_SECTIONS: tuple\[str, ...\] = ("/login", "/agents")' serving.py)
# REPLACE (verified: serving.py:39) with:
SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents", "/account")
```
Also update the module docstring list of sections (top of file, "(``/login``, ``/agents``, ...)") and the
`setup_admin_ui` docstring mention of `SPA_SECTIONS` contents to include ``/account``.

### `packages/ai-parrot-server/tests/test_admin_ui_serving.py` (MODIFY)
```python
# :68  occurrences: 1 — parametrize list becomes:
        "path", ["/", "/login", "/agents", "/agents/helpdesk/chat", "/admin/home", "/account/security"]
# :86  occurrences: 1 — lookalike list becomes:
        for path in ("/not-a-ui-page", "/agentsfoo", "/accounts", "/api/v1/missing"):
# :192 occurrences: 1 — pattern list becomes:
        for pattern in ("/admin", "/admin/*", "/login", "/agents", "/agents/*", "/account", "/account/*", "/ui/assets/*"):
# :198 occurrences: 1 — must-not-match list becomes:
        for path in ("/administer", "/agentsfoo", "/accounts", "/api/v1/bots", "/api/v1/login"):
```

### FILL IN checklist
- [ ] Docstring mentions of the section list updated (no logic decisions remain)

---

## Acceptance Criteria

- [ ] `/account/security` returns the SPA shell with `Cache-Control: no-cache`; `/accounts` 404s (AC08)
- [ ] Exclusion list contains `/account` and `/account/*`; `/accounts` matches no pattern
- [ ] `ruff check packages/ai-parrot-server/src/parrot/server/ui/serving.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_admin_ui_serving.py -q`

---

## Test Specification

See the test blueprint block above (spec §4 row for Module 7).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug passkey-support --feature-id FEAT-772`)
2. **Read the spec** at `sdd/specs/passkey-support.spec.md` (§2 transport rules, §6 contract, §7 risks)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/passkey-support.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Re-run `grep -c` for every MODIFY anchor in the blueprint; a count that differs means the anchor moved — re-locate it; a count of `0` means drift — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/passkey-support.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `FILL IN` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands. Vitest commands run from
   `packages/ai-parrot-server/ui` (`pnpm exec vitest run <file>`); pytest commands from the worktree
   root with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(passkey-support): TASK-4904 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4904 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4904
- Feature: passkey-support
- Implementation SHA: baebe1f345ac3beb56dd2ccd5620222be9df4b53
- Closed at (UTC): 2026-10-30T15:42:17+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 149s · Tokens: n/a |
