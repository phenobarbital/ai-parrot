# TASK-4902: `/account/security` page — list, add, rename, delete passkeys

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4898, TASK-4899, TASK-4900
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, G2/G8, AC05/AC06/AC07. Without this page nobody can enroll a first passkey.
The page component is created here; the route, nav entry and Topbar link are TASK-4903. Decided
behaviours (spec + codex S5): `GET credentials` lists **every** relying party's credentials, so the
`rp_id` is always shown; after **every** mutation the list is re-fetched (no optimistic edits); a
DELETE 409 ("last login method") is authoritative and the row stays; a 4xx from
`register/options` means the current origin is not in `PASSKEY_RELYING_PARTIES` and shows an
operator hint.

---

## Scope

- Create `pages/account/Security.svelte` with a "Session" card (current method from `authStore.authMethod`) and a "Passkeys" card.
- Create `lib/components/account/PasskeyList.svelte` (rows, inline rename, delete with confirmation dialog).
- Create `lib/components/account/AddPasskeyDialog.svelte` (ceremony → optional label → verify).
- Create `pages/account/Security.test.ts`.

**NOT in scope**: route registration / nav / Topbar (TASK-4903), `SPA_SECTIONS` (TASK-4904),
admin management of other users' passkeys (spec Non-Goals), a "set a password" flow.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/ui/test_vitest_account_security.py` | CREATE | pytest wrapper running the vitest file(s) (validation contract accepts pytest only) |
| `packages/ai-parrot-server/ui/src/pages/account/Security.svelte` | CREATE | Page: session method + passkey card + error/hint states |
| `packages/ai-parrot-server/ui/src/pages/account/Security.test.ts` | CREATE | Page tests (mocked passkey API + WebAuthn) |
| `packages/ai-parrot-server/ui/src/lib/components/account/PasskeyList.svelte` | CREATE | Rows, rename, delete confirmation |
| `packages/ai-parrot-server/ui/src/lib/components/account/AddPasskeyDialog.svelte` | CREATE | Enrollment ceremony dialog |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ._vitest import run_vitest   # packages/ai-parrot-server/tests/ui/_vitest.py (run_vitest(*files) → pnpm exec vitest run, cwd ui/)
```
```ts
import { onMount } from "svelte";
import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";                   // badge/index.ts: Badge, badgeVariants
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "$lib/ui/internal/shadcn/ui/card/index.js";
import * as Dialog from "$lib/ui/internal/shadcn/ui/dialog/index.js";               // Root, Content, Header, Title, Description, Footer, Close, …
import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";
import { ApiError } from "$lib/api/http";                                            // http.ts:31 (.status)
import { authStore } from "$lib/stores/auth.svelte";                                  // .authMethod (TASK-4900)
import {
  deletePasskey, fetchRegisterOptions, listPasskeys, passkeyErrorMessage, renamePasskey, verifyRegistration,
  type PasskeyCredentialSummary,
} from "$lib/api/passkey";                                                            // TASK-4899
import { credentialToJSON, isUserCancelled, isWebAuthnSupported, toCreationOptions } from "$lib/webauthn";  // TASK-4898
```

### Existing Signatures to Use
```ts
// ApiError(message, code, status?, raw?) — http.ts:31. 404 → ApiError("Not found","server",404);
//   409/400/other → ApiError(extractServerMessage(...), "server", status) — use err.status to branch
// Backend: register/options 4xx (origin not an RP) · register/verify 409 duplicate · DELETE 409 last login method
//   (navigator_auth/backends/passkey.py:217, :261, :549). GET credentials returns ALL RPs (:510).
// Page layout precedent: packages/ai-parrot-server/ui/src/pages/Dashboard.svelte (Card grid inside AppShell's <main>)
```

### Does NOT Exist
- ~~`pages/account/`~~, ~~`lib/components/account/`~~ — created here.
- ~~`dropdown-menu` primitive~~ — not vendored; use buttons + `Dialog`.
- ~~`AlertDialog` primitive~~ — not vendored; confirmation uses `Dialog`.
- ~~a toast/notification store~~ — show inline `role="alert"` / `role="status"` messages.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_account_security.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/pages/account/Security.svelte", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/pages/account/Security.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/account/PasskeyList.svelte", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/account/AddPasskeyDialog.svelte", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/ui/src/lib/api/http.ts#ApiError",
    "sym:packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts#AuthStore"
  ]
}
```

---

## Implementation Notes

### Copy (fixed by spec §3 M5 / AC05 — use verbatim)
- Origin not an RP: "This site is not configured for passkeys — ask your administrator to add its origin to PASSKEY_RELYING_PARTIES."
- Duplicate: "This device is already registered."
- Unsupported: "Your browser does not support passkeys."
- Last login method: "You can't delete your only way to sign in. Set a password or add another passkey first."
- Session line: "Signed in with a passkey" / "Signed in with a password".
- Device: `single_device` → "This device only", `multi_device` → "Synced"; label fallback "Unnamed passkey".

---

## Implementation Blueprint

### Steps (in order)
1. Create `PasskeyList.svelte` (pure presentational + callbacks) — *why*: the page owns data and refresh.
2. Create `AddPasskeyDialog.svelte` — *why*: isolates the enrollment ceremony.
3. Create `Security.svelte` wiring both, re-fetching after every mutation — *why*: codex S5, no optimistic edits.
4. Write `Security.test.ts` — *why*: spec §4 M5 rows; it is in the Validation Contract.

### `packages/ai-parrot-server/ui/src/lib/components/account/PasskeyList.svelte` (CREATE)
```svelte
<script lang="ts">
  import type { PasskeyCredentialSummary } from "$lib/api/passkey";
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import * as Dialog from "$lib/ui/internal/shadcn/ui/dialog/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";

  interface Props {
    items: PasskeyCredentialSummary[];
    loading: boolean;
    onRename: (id: string, label: string) => Promise<void>;
    onDelete: (id: string) => Promise<void>;
  }

  let { items, loading, onRename, onDelete }: Props = $props();

  let editingId = $state<string | null>(null);
  let draft = $state("");
  let confirmId = $state<string | null>(null);

  const deviceLabel = (t: string | null): string =>
    t === "multi_device" ? "Synced" : t === "single_device" ? "This device only" : "Unknown device";
  const when = (iso: string | null): string => (iso ? new Date(iso).toLocaleString() : "Never");

  // FILL IN: saveRename() — trim, 1..128 guard, await onRename(editingId, draft), then editingId = null
  // FILL IN: confirmDelete() — await onDelete(confirmId); always close the dialog (the page shows errors)
</script>

<!-- FILL IN markup, data-testid="passkey-list" on the list root:
     loading → 2 <Skeleton class="h-12 w-full" />; empty → nothing (the page renders the empty state);
     each row (data-testid="passkey-row"): label || "Unnamed passkey" · deviceLabel(device_type) · {#if backed_up}<Badge variant="secondary">Synced</Badge>{/if}
       · rp_id · "Added " + when(created_at) · "Last used " + when(last_used_at)
       · Rename (inline <Input maxlength={128}> + Save/Cancel) · Delete (opens confirmation)
     <Dialog.Root open={confirmId !== null} onOpenChange={(o) => !o && (confirmId = null)}> with Title "Delete this passkey?",
       Description "You will no longer be able to sign in with it.", Cancel + destructive "Delete" (data-testid="passkey-confirm-delete") -->
```

### `packages/ai-parrot-server/ui/src/lib/components/account/AddPasskeyDialog.svelte` (CREATE)
```svelte
<script lang="ts">
  import { fetchRegisterOptions, passkeyErrorMessage, verifyRegistration } from "$lib/api/passkey";
  import { ApiError } from "$lib/api/http";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import * as Dialog from "$lib/ui/internal/shadcn/ui/dialog/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { credentialToJSON, isUserCancelled, isWebAuthnSupported, toCreationOptions } from "$lib/webauthn";

  interface Props {
    open: boolean;
    onClose: () => void;
    onRegistered: () => void;
  }

  let { open, onClose, onRegistered }: Props = $props();

  // step: "ceremony" (waiting for the authenticator) → "label" (optional name) → done
  let step = $state<"ceremony" | "label">("ceremony");
  let label = $state("");
  let error = $state("");
  let credential = $state<ReturnType<typeof credentialToJSON> | null>(null);

  async function start(): Promise<void> {
    // FILL IN: if !isWebAuthnSupported() → error = "Your browser does not support passkeys."; return
    //   json = await fetchRegisterOptions()  — a 4xx here (origin not an RP) → error = the PASSKEY_RELYING_PARTIES hint (exact copy)
    //   cred = await navigator.credentials.create({ publicKey: toCreationOptions(json) }); isUserCancelled → onClose() silently
    //   credential = credentialToJSON(cred as PublicKeyCredential); step = "label"
  }

  async function finish(): Promise<void> {
    // FILL IN: await verifyRegistration(credential!, label.trim() || undefined); onRegistered(); onClose()
    //   ApiError status 409 → "This device is already registered."; else passkeyErrorMessage(err)
    void ApiError;
    void passkeyErrorMessage;
  }

  $effect(() => {
    if (open) {
      step = "ceremony";
      label = "";
      error = "";
      credential = null;
      void start();
    }
  });
</script>

<!-- FILL IN markup: <Dialog.Root {open} onOpenChange={(o) => !o && onClose()}> → Title "Add a passkey";
     step "ceremony": "Follow your browser's prompt…"; step "label": <Label for="passkey-label">Name (optional)</Label>
     <Input id="passkey-label" maxlength={128} bind:value={label} placeholder="e.g. Work laptop" /> + Save (data-testid="passkey-save");
     error → role="alert". -->
```

### `packages/ai-parrot-server/ui/src/pages/account/Security.svelte` (CREATE)
```svelte
<!-- Account › Security (FEAT-772, spec §3 Module 5). Route /account/security (registered by the nav task). -->
<script lang="ts">
  import { onMount } from "svelte";

  import { ApiError } from "$lib/api/http";
  import { deletePasskey, listPasskeys, passkeyErrorMessage, renamePasskey, type PasskeyCredentialSummary } from "$lib/api/passkey";
  import AddPasskeyDialog from "$lib/components/account/AddPasskeyDialog.svelte";
  import PasskeyList from "$lib/components/account/PasskeyList.svelte";
  import { authStore } from "$lib/stores/auth.svelte";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";

  const LAST_METHOD = "You can't delete your only way to sign in. Set a password or add another passkey first.";

  let items = $state<PasskeyCredentialSummary[]>([]);
  let loading = $state(true);
  let error = $state("");
  let adding = $state(false);

  async function refresh(): Promise<void> {
    loading = true;
    try {
      items = await listPasskeys();
      error = "";
    } catch (err) {
      error = passkeyErrorMessage(err);
    } finally {
      loading = false;
    }
  }

  async function handleRename(id: string, label: string): Promise<void> {
    // FILL IN: try renamePasskey → catch error = passkeyErrorMessage(err); ALWAYS await refresh() afterwards (no optimistic edit)
  }

  async function handleDelete(id: string): Promise<void> {
    // FILL IN: try deletePasskey → catch: ApiError status 409 → error = LAST_METHOD, else passkeyErrorMessage(err);
    //   ALWAYS await refresh() afterwards — a 409 is authoritative and the row must stay
    void ApiError;
    void LAST_METHOD;
  }

  onMount(refresh);
</script>

<!-- FILL IN markup (max-w-3xl, gap-6):
     Card "Session": "Signed in with a passkey" when authStore.authMethod === "passkey", else "Signed in with a password" (data-testid="session-method")
     Card "Passkeys" + CardDescription (what a passkey is) + Button "Add a passkey" (data-testid="passkey-add") → adding = true
       error → role="alert"; !loading && items.length === 0 → empty-state paragraph (data-testid="passkey-empty")
       <PasskeyList {items} {loading} onRename={handleRename} onDelete={handleDelete} />
     <AddPasskeyDialog open={adding} onClose={() => (adding = false)} onRegistered={refresh} /> -->
```
**Why this shape**: data and refresh live in the page; children only report intent. Never filter
rows by the current origin (rows from other RPs are legitimate).

### `packages/ai-parrot-server/ui/src/pages/account/Security.test.ts` (CREATE)
```ts
import { render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as passkeyApi from "$lib/api/passkey";
import { authStore } from "$lib/stores/auth.svelte";

import Security from "./Security.svelte";

const ROW = { id: "Y3JlZA", label: "Laptop", created_at: "2026-10-30T00:00:00+00:00", last_used_at: null,
              device_type: "multi_device", backed_up: true, rp_id: "localhost" };

beforeEach(() => {
  localStorage.clear();
  authStore.user = { username: "alice", auth_method: "passkey" };
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Account › Security", () => {
  it("lists passkeys with label, synced badge and relying party", async () => {
    vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValue([ROW]);
    const { findByText, getByText } = render(Security);
    expect(await findByText("Laptop")).toBeTruthy();
    expect(getByText("localhost", { exact: false })).toBeTruthy();
  });

  it("states the current session method", async () => {
    vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValue([]);
    const { findByTestId } = render(Security);
    expect((await findByTestId("session-method")).textContent).toContain("Signed in with a passkey");
  });

  // FILL IN: empty state renders data-testid="passkey-empty"
  // FILL IN: add flow — stub PublicKeyCredential + navigator.credentials.create; fetchRegisterOptions → create → label → verifyRegistration(cred, "Work")
  //   then listPasskeys called again (refresh)
  // FILL IN: rename → renamePasskey(id, label) then refresh; delete 409 (ApiError status 409) → LAST_METHOD text and the row stays
  // FILL IN: register/options rejects with ApiError status 400 → PASSKEY_RELYING_PARTIES hint
  void waitFor;
});
```

### `packages/ai-parrot-server/tests/ui/test_vitest_account_security.py` (CREATE)
```python
"""FEAT-772 (TASK-4902): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_account_security_vitest() -> None:
    """Account > Security: list, add, rename, delete passkeys and error copy."""
    run_vitest("src/pages/account/Security.test.ts")
```
**Why**: `check_task_graph` accepts pytest validation commands only; this is the established wrapper
pattern (`tests/ui/_vitest.py::run_vitest`, e.g. `test_vitest_suggestion_chips.py`). It skips when
`pnpm`/`node_modules` is absent.

### FILL IN checklist
- [ ] `PasskeyList.svelte` — rename/delete handlers + markup; bounded by AC05 copy
- [ ] `AddPasskeyDialog.svelte::start` / `finish` + markup; bounded by AC05 copy and silent cancel (spec §7)
- [ ] `Security.svelte::handleRename` / `handleDelete` + markup; bounded by codex S5 (refresh after every mutation)
- [ ] `Security.test.ts` — four FILL IN groups, then delete the `void` line; bounded by spec §4 M5 rows

---

## Acceptance Criteria

- [ ] Lists label/device/synced/RP/dates; add (optional label ≤ 128), rename (1–128), delete with confirmation (AC05)
- [ ] DELETE 409 shows the last-login-method copy and the row stays; origin-not-RP shows the operator hint (AC05)
- [ ] Every call goes through `$lib/api/passkey` authenticated functions (AC06)
- [ ] Session card reflects `authStore.authMethod` (AC07)
- [ ] `pnpm exec vitest run src/pages/account/Security.test.ts` passes

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_account_security.py -q`

---

## Test Specification

See the `Security.test.ts` blueprint block above (spec §4 rows for Module 5).

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
   `feat(passkey-support): TASK-4902 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4902 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
