# TASK-4900: `AuthStore.loginWithPasskey()` and `authMethod`

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4899
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, G4. A passkey login must leave the SPA in exactly the state a password login
does — same `ai_parrot_token` / `ai_parrot_session` keys, same in-memory `token`/`user` — so the
401 handling, Topbar identity and the `admin.py` / `parrot-formdesigner` interop keep working.
The spec fixes one private helper, `_storeLoginEnvelope()`, shared by `login()` and the new
`loginWithPasskey()`, so the two cannot drift (codex S11). It also adds `authMethod`, read from the
stored envelope's `auth_method` (`"passkey"` after a passkey login, `passkey.py:468-476`), which
drives the Topbar badge (TASK-4903) and the session line on `/account/security` (TASK-4902).

---

## Scope

- Refactor the persistence tail of `login()` into `private _storeLoginEnvelope(data)`; `login()` behaviour and its existing tests stay identical.
- Add `loginWithPasskey(challengeId, credential)` calling `postPasskeyLogin` (bare axios — never `apiClient`).
- Add `authMethod = $derived(...)`.
- Extend `auth.test.ts`.

**NOT in scope**: fixing the BasicAuth `login()` → `apiClient` → `handle401()` path (ledger
`issue:ea1e3a3f2488`, out of scope per spec §1 Non-Goals); any UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/ui/test_vitest_auth_store.py` | CREATE | pytest wrapper running the vitest file(s) (validation contract accepts pytest only) |
| `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` | MODIFY | `_storeLoginEnvelope`, `loginWithPasskey`, `authMethod` |
| `packages/ai-parrot-server/ui/src/lib/stores/auth.test.ts` | MODIFY | Passkey login + authMethod tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ._vitest import run_vitest   # packages/ai-parrot-server/tests/ui/_vitest.py (run_vitest(*files) → pnpm exec vitest run, cwd ui/)
```
```ts
// already in auth.svelte.ts:
import apiClient from "$lib/api/http";
import { config } from "$lib/config";
import { isInAppPath, router } from "$lib/router.svelte";
// add:
import { postPasskeyLogin } from "$lib/api/passkey";          // TASK-4899
import type { PublicKeyCredentialJSON } from "$lib/webauthn";  // TASK-4898
```

### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts
export interface AuthUser { [key: string]: unknown }
class AuthStore {
  token = $state<string | null>(readStoredToken());
  user = $state<AuthUser | null>(readStoredUser());
  loading = $state(false);
  isAuthenticated = $derived(this.token !== null);
  async login(username: string, password: string): Promise<{ success: boolean; error?: string }> {   // :62
    // this.loading = true; try { const { data } = await apiClient.post(config.loginUrl, {username,password},
    //   { headers: { "X-Auth-Method": "BasicAuth" } });   // :68
    //   if (!data?.token) throw new Error("No token received from server");
    //   try { localStorage.setItem(config.tokenStorageKey, data.token); localStorage.setItem(config.sessionStorageKey, JSON.stringify(data)); } catch {}
    //   this.token = data.token; this.user = data; return { success: true };
    // } catch (error) { message = error.response.data.message || error.message || "Login failed"; return {success:false, error: message} }
    // finally { this.loading = false; }
  }
  async logout(): Promise<void>   // :99
  handle401(): void               // :113
}
export { AuthStore };
export const authStore = new AuthStore();
// auth.test.ts:7 describe("AuthStore") — uses `new AuthStore()`, vi.spyOn(apiClient, "post"), localStorage.clear() in beforeEach
```

### Does NOT Exist
- ~~`AuthStore.loginWithPasskey`~~, ~~`AuthStore.authMethod`~~, ~~`AuthStore._storeLoginEnvelope`~~ — added here.
- ~~`AuthStore.setSession()`~~ / ~~`AuthStore.persist()`~~ — no such methods; use the names above.
- ~~`authStore.user.auth_method` typed field~~ — `AuthUser` is index-signature only; read it as `unknown` and narrow.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_auth_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/stores/auth.test.ts", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts#AuthStore",
    "sym:packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts#AuthStore.login",
    "sym:packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts#AuthStore.logout"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Extract `_storeLoginEnvelope` from `login()` without behaviour change; run the existing tests — *why*: proves the refactor before new code.
2. Add `loginWithPasskey` below `logout()` — *why*: spec skeleton places it there; it reuses the helper.
3. Add `authMethod` next to `isAuthenticated` — *why*: both are derived from store state.
4. Extend `auth.test.ts` — *why*: AC03/AC04 rely on these behaviours.

### `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  async login(username: string, password: string): Promise<{ success: boolean; error?: string }> {' auth.svelte.ts)
// REPLACE the body of login() (auth.svelte.ts:62-97) so that, after `const { data } = await apiClient.post(...)`,
// it calls `this._storeLoginEnvelope(data);` instead of the inline token check + localStorage writes + assignments.
// Keep the catch/finally blocks byte-identical.

// INSERT next to `isAuthenticated = $derived(this.token !== null);`
  /** `user.auth_method` from the stored login envelope ("passkey" after a passkey login), else null. */
  authMethod = $derived<string | null>(
    typeof this.user?.auth_method === "string" ? (this.user.auth_method as string) : null,
  );

// INSERT the helper above login():
  /** Shared tail of every login: require data.token, persist both keys (best effort), set token + user. */
  private _storeLoginEnvelope(data: Record<string, unknown>): void {
    const token = data?.token;
    if (typeof token !== "string" || !token) {
      throw new Error("No token received from server");
    }
    try {
      localStorage.setItem(config.tokenStorageKey, token);
      localStorage.setItem(config.sessionStorageKey, JSON.stringify(data));
    } catch {
      // localStorage unavailable — session still works for this tab via in-memory state.
    }
    this.token = token;
    this.user = data;
  }

// occurrences: 1 (verified: grep -c '  async logout(): Promise<void> {' auth.svelte.ts)
// BEFORE — insert above `  async logout(): Promise<void> {` (verified: auth.svelte.ts:99)
  /**
   * Finish a passkey sign-in: POST /api/v1/login with X-Auth-Method: PasskeyAuth
   * (bare axios via postPasskeyLogin — NEVER apiClient, spec §2 rule 1), then persist
   * the envelope exactly like login().
   */
  async loginWithPasskey(
    challengeId: string,
    credential: PublicKeyCredentialJSON,
  ): Promise<{ success: boolean; error?: string }> {
    this.loading = true;
    try {
      const data = await postPasskeyLogin({ challenge_id: challengeId, credential });
      this._storeLoginEnvelope(data);
      return { success: true };
    } catch (error: unknown) {
      // FILL IN: error string = server message (response.data.reason | message) when present,
      //   else "Passkey sign-in failed" — bounded by AC14 (UI shows one generic message anyway; never branch on reason)
      return { success: false, error: "Passkey sign-in failed" };
    } finally {
      this.loading = false;
    }
  }
```
**Why**: one persistence path (S11). `loginWithPasskey` must not call `handle401()` and must not
touch storage on failure — tests assert both.

### `packages/ai-parrot-server/ui/src/lib/stores/auth.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  it("login() surfaces the server error message on failure", async () => {' auth.test.ts)
// BEFORE — insert above that `it(` (verified: auth.test.ts:37); add `import axios from "axios";` to the imports.
  it("loginWithPasskey() posts with X-Auth-Method: PasskeyAuth via bare axios and stores the same keys", async () => {
    const envelope = { token: "pk-1", username: "alice", auth_method: "passkey", mfa: true };
    const bare = vi.spyOn(axios, "post").mockResolvedValue({ data: envelope });
    const client = vi.spyOn(apiClient, "post");

    const store = new AuthStore();
    const result = await store.loginWithPasskey("chal-1", {
      id: "Y3JlZA", rawId: "Y3JlZA", type: "public-key", clientExtensionResults: {}, response: {},
    });

    expect(result).toEqual({ success: true });
    expect(client).not.toHaveBeenCalled();
    expect(bare.mock.calls[0][2]).toMatchObject({ headers: { "X-Auth-Method": "PasskeyAuth" } });
    expect(localStorage.getItem("ai_parrot_token")).toBe("pk-1");
    expect(JSON.parse(localStorage.getItem("ai_parrot_session")!)).toEqual(envelope);
    expect(store.authMethod).toBe("passkey");
  });

  // FILL IN: loginWithPasskey failure (axios rejects 401) → {success:false}, storage untouched, handle401 NOT called (spy)
  // FILL IN: authMethod is null for a BasicAuth envelope without auth_method
```

### `packages/ai-parrot-server/tests/ui/test_vitest_auth_store.py` (CREATE)
```python
"""FEAT-772 (TASK-4900): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_auth_store_vitest() -> None:
    """AuthStore: BasicAuth + passkey login persistence, authMethod, logout, handle401."""
    run_vitest("src/lib/stores/auth.test.ts")
```
**Why**: `check_task_graph` accepts pytest validation commands only; this is the established wrapper
pattern (`tests/ui/_vitest.py::run_vitest`, e.g. `test_vitest_suggestion_chips.py`). It skips when
`pnpm`/`node_modules` is absent.

### FILL IN checklist
- [ ] `auth.svelte.ts::login` — call `_storeLoginEnvelope`; existing tests unchanged; bounded by auth.test.ts:17-49
- [ ] `auth.svelte.ts::loginWithPasskey` — error string; bounded by AC14
- [ ] `auth.test.ts` — failure + BasicAuth `authMethod` cases; bounded by spec §4 M3 rows

---

## Acceptance Criteria

- [ ] Existing `login()` / `logout()` / `handle401()` tests pass unchanged
- [ ] `loginWithPasskey` persists the envelope via the shared helper and never uses `apiClient` (AC03, AC04)
- [ ] On failure: `{success:false}`, storage untouched, `handle401()` not called
- [ ] `authStore.authMethod` is `"passkey"` after a passkey login, `null` otherwise
- [ ] `pnpm exec vitest run src/lib/stores/auth.test.ts` passes

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_auth_store.py -q`

---

## Test Specification

See the `auth.test.ts` blueprint block above (spec §4 rows for Module 3).

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
   `feat(passkey-support): TASK-4900 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4900 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4900
- Feature: passkey-support
- Implementation SHA: 325b696e2d7c0528f16b7fa7adfe9e9bc2718433
- Closed at (UTC): 2026-10-30T15:52:46+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 186s · Tokens: n/a |
