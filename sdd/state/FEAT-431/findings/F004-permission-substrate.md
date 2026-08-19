# F004 — Two-level permissions have an existing group-based substrate

**Repo:** navigator-svelte
**Citations:** `src/lib/helpers/rep-mode.test.ts` L5-17 (and `rep-mode.ts`);
  `src/lib/api/fieldsync/formActivityTypesApi.ts` L143;
  `DashboardActionsDropdown.svelte` guards (`isOwner`, `user.superuser`,
  `isCurrentUserDashboard`, `is_system`)
**Confidence:** medium (pattern verified; not yet traced to a dashboard-authoring gate)

Brainstorm §5.1.B wants two permission levels — **self-service** (business users,
no-code) and **advanced** (Nav/dev: granular envelope config, custom components) — and
§5.2 wisely scopes out "building Navigator's permission system from scratch (assess
existing base first)".

The existing base is **group membership with tenant-prefixed names**, plus a superuser
flag:

```ts
const repUser     = { superuser: false, groups: [`${P}_fieldsync_rep`] }
const adminUser   = { superuser: false, groups: [`${P}_fieldsync_admin`] }
const managerUser = { superuser: false, groups: [`${P}_fieldsync_manager`] }
const superUser   = { superuser: true,  groups: [] }
```

with derivation helpers (`isRepUser(user, tenantPrefix)`) and a documented
"claim — superuser, or membership — and answers 403 otherwise" API convention.

So the two-level model is a **new pair of groups plus a helper**, following an
established pattern — not new infrastructure. The dashboard editor's existing guards
(`isOwner` / `superuser` / `isCurrentUserDashboard`) are the closest analogue for the
authoring gate.
