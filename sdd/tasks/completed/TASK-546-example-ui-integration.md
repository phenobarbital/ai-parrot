# TASK-546: Example UI Integration for Database Forms

**Feature**: Form Builder from Database Definition
**Spec**: `sdd/specs/formbuilder-database.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-544, TASK-545
**Assigned-to**: unassigned

---

## Context

The existing `form_server.py` example lets users create forms via natural language.
This task adds a "Load from Database" section so users can enter a `formid` and `orgid`
and get the database-defined form rendered as HTML5.

Implements **Module 3** from the spec.

---

## Scope

- Add a "Load from Database" card to the index page (`handle_index`) with:
  - `formid` numeric input
  - `orgid` numeric input
  - "Load from Database" submit button
- Add `POST /api/forms/from-db` endpoint that:
  - Accepts JSON `{"formid": int, "orgid": int}`
  - Instantiates `DatabaseFormTool` with the app's `FormRegistry`
  - Calls the tool
  - Returns the generated `FormSchema` as JSON (or error)
- After successful load, redirect/link to `/forms/{form_id}` to render the form
- Wire `DatabaseFormTool` into `create_app()` setup (store in `app["db_form_tool"]`)

**NOT in scope**: Tool implementation (TASK-544), package exports (TASK-545), tests (TASK-547)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/forms/form_server.py` | MODIFY | Add DB form loading UI section + API endpoint |

---

## Implementation Notes

### Pattern to Follow
```python
# In create_app(), add alongside existing create_tool:
db_form_tool = DatabaseFormTool(registry=registry)
app["db_form_tool"] = db_form_tool

# New route:
app.router.add_post("/api/forms/from-db", handle_api_load_db_form)
```

### UI Addition
Add a second card below the existing prompt builder:
```html
<div class="card">
  <h2>Load from Database</h2>
  <p>Enter a Form ID and Org ID to load an existing form definition.</p>
  <label>Form ID: <input type="number" id="formid" /></label>
  <label>Org ID: <input type="number" id="orgid" /></label>
  <button class="btn btn-primary" onclick="loadFromDB()">Load from Database</button>
</div>
```

### Key Constraints
- Follow existing aiohttp handler patterns in the file
- Use existing CSS classes (`.card`, `.btn`, `.btn-primary`)
- Error handling: show `.error-banner` if tool returns error

### References in Codebase
- `examples/forms/form_server.py` — existing server structure
- `handle_api_create_form` — pattern for API endpoint handler

---

## Acceptance Criteria

- [ ] Index page shows "Load from Database" section with formid/orgid inputs
- [ ] `POST /api/forms/from-db` endpoint works with `{"formid": 4, "orgid": 71}`
- [ ] Successfully loaded form redirects to `/forms/{form_id}` for rendering
- [ ] Error cases show user-friendly error message
- [ ] Existing natural language form creation still works unchanged

---

## Test Specification

```python
# Manual testing — verify via browser at http://localhost:8080
# 1. Enter formid=4, orgid=71
# 2. Click "Load from Database"
# 3. Verify form renders with sections, fields, and conditional logic
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formbuilder-database.spec.md` for full context
2. **Check dependencies** — TASK-544 and TASK-545 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-546-example-ui-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-start)
**Date**: 2026-04-03
**Notes**: Created `examples/forms/form_server.py` in the worktree (file was previously
untracked in git, covered by `examples/**/*.py` gitignore — force-added with `git add -f`).
Added "Load from Database" card with formid/orgid inputs and `loadFromDB()` JS function.
Added `handle_api_load_db_form` for `POST /api/forms/from-db` — validates inputs,
calls DatabaseFormTool, distinguishes 404 (not found) from 500 (other errors).
Wired `DatabaseFormTool` into `create_app()` as `app["db_form_tool"]`. All 274 form tests pass.

**Deviations from spec**: File was not tracked by git (gitignore `examples/**/*.py`),
so it was committed fresh to the worktree via `git add -f`.
