# TASK-4681: Data-management modal accepts any file and renders the server's report

**Feature**: FEAT-739 — Admin UI accepts every upload the backend stores, and reports what it stored
**Spec**: `sdd/specs/fixgroup-6630fd230436.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4680
**Assigned-to**: unassigned

**Discovered-from**: `issue:04dcfd611ebc`

---

## Context

This is the task that actually closes `issue:04dcfd611ebc`. TASK-4680 built the
types and the formatter; this task removes the two gates in the modal itself
(spec §3 Module 3):

1. The client-side `.xlsx`/`.xls` guard and the `accept=".xlsx"` attribute,
   which make a `.docx` or `.pdf` unreachable through the admin UI even though
   `BasicAgent.handle_files` persists any bytes.
2. The hardcoded `"Uploaded"` status, which tells the user "success" from a
   string that is not derived from the server's answer.

It also fixes the consequence the issue did not name: a 400 currently renders as
the literal `HTTP 400`, because `extractServerMessage` finds no known key in the
upload body. The per-file reasons live only in `ApiError.raw.response.data`.

---

## Scope

- Delete the `.xlsx`/`.xls` guard and rename `handleUploadExcel` → `handleUpload`.
- Remove `accept=".xlsx"` from the file input and update the three Excel-specific
  copy strings.
- Render the status from `formatUploadStatus`, on both the success path and the
  400 path (via `uploadPayloadFromError`).
- Widen the status paragraph to three colours and stop auto-clearing anything
  that is not a clean success.
- Write `DataManagementModal.test.ts` plus its pytest bridge.

**NOT in scope**:
- Multi-file upload. The input stays single and `uploadFiles[0]` is still what
  is sent.
- Client-side size validation — the session store owns the cap (FEAT-643) and
  reports it per file.
- The `Refresh Data` and `Add Query` sections, the other four tabs, and
  `toastStore` / `notificationStore`. The upload section uses the inline
  `uploadStatus` paragraph; do not add toasts to it.
- `agent.ts` and `upload-status.ts` — owned by TASK-4680.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte` | MODIFY | Drop the gate, widen the picker, render the report |
| `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.test.ts` | CREATE | Component tests |
| `packages/ai-parrot-server/tests/ui/test_vitest_data_management_modal.py` | CREATE | pytest bridge |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `be519ab78` (dev), 2026-10-24. The `$lib/api/agent` and
> `./upload-status` symbols below are created by TASK-4680 — verify them in the
> worktree before use.

### Verified Imports

```ts
import { AppDialog, AppTabs } from "$lib/ui/components";                    // DataManagementModal.svelte:2
import Icon from "@iconify/svelte";                                          // DataManagementModal.svelte:3
import { refreshAgentData, uploadAgentData, addAgentQuery } from "$lib/api/agent";  // :4-8
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte"; // MyToolkitSettings.test.ts:1
```

```ts
// Created by TASK-4680 — confirm before use:
import { formatUploadStatus, uploadPayloadFromError } from "./upload-status";
import type { UploadStatusType } from "./upload-status";
```

```python
from ._vitest import run_vitest   # verified: packages/ai-parrot-server/tests/ui/_vitest.py:20
```

### Existing Signatures to Use

```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte
let uploadFiles = $state<FileList | null>(null);                  // line 35
let uploadStatus = $state<{ type: "success" | "error" | null; message: string }>(
  { type: null, message: "" },
);                                                                 // lines 38-41
async function handleUploadExcel() { ... }                         // line 100
//   :101-107  empty-selection guard  -> KEEP VERBATIM
//   :108-115  the .xlsx/.xls guard   -> DELETE
//   :117-119  "Uploading..." + FormData.append("file", file)  -> KEEP
//   :122-127  await + hardcoded "Uploaded" + 3s clear          -> REPLACE
//   :128-134  catch: console.error + error.message fallback    -> REPLACE BODY, keep console.error
<input type="file" class="hidden" accept=".xlsx" bind:files={uploadFiles} />   // lines 246-251
<button ... onclick={handleUploadExcel} ...>Upload</button>                     // line 255
{#if uploadStatus.type} <p class={... "text-red-500" : "text-green-500"}>       // lines 261-267
```

Copy strings to change, each occurring once:
- `>Upload Excel</span` — line 225
- `>Upload .xlsx file as dataset</span` — line 228
- `>Click to choose .xlsx file</span` — line 243

### Does NOT Exist

- ~~`DataManagementModal.test.ts`~~ — this task creates it.
- ~~`added_files`~~ — not a key of the FEAT-639 response; never read it.
- ~~`ApiError.data` / `ApiError.body`~~ — the body is only at
  `raw.response.data`; use `uploadPayloadFromError`.
- ~~`error.message` carrying the per-file reason~~ — on a 400 it is the literal
  `"HTTP 400"` (`extractServerMessage`, `http.ts:80`). It is the *fallback*, not
  the source.
- ~~`toastStore` on the upload path~~ — the upload section has no toast; only
  `handleRefreshData` uses one. Do not add one.
- ~~a `warning` variant on the existing status `<p>`~~ — the class ternary at
  :261-267 is two-way today; this task widens it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_data_management_modal.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/tests/ui/_vitest.py#run_vitest"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Svelte 5 runes only** (`$state`, `$derived`, `$props`). The file already
  uses them; never introduce `export let`.
- Tailwind utilities only, matching the surrounding classes. The warning colour
  is `text-amber-500` — do not invent a palette entry.
- The 3-second auto-clear must run **only** for `type === "success"`, so a
  warning or an error stays on screen for the user to read.
- `uploadFiles` is cleared only when the status is not `"error"` — a rejected
  file stays selected so the user can see what failed.

### References in Codebase

- `packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.test.ts`
  — the `vi.mock("$lib/api/...")` + `render(Component, { props })` idiom.
- `packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py` — the
  bridge wrapper to copy.

---

## Implementation Blueprint

### Steps (in order)
1. Import the two formatter functions and the `UploadStatusType` type — *why*:
   the modal must stop deciding status text itself.
2. Widen the `uploadStatus` state type to `UploadStatusType | null` — *why*: the
   third `warning` state has no home otherwise.
3. Rewrite `handleUploadExcel` as `handleUpload`, deleting the extension guard —
   *why*: the server is the only gate (spec §8, resolved from the code).
4. Update the `onclick` at line 255 to the new name — *why*: a renamed handler
   with a stale binding silently does nothing.
5. Remove `accept=".xlsx"` and update the three copy strings — *why*: the OS
   dialog is the first of the two gates, and the copy would otherwise lie.
6. Widen the status paragraph's class to three colours — *why*: AC4.
7. Write the component test and its bridge — *why*: AC1/AC2/AC3 are behavioural.

### `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte` (MODIFY — script)
```ts
// occurrences: 1 (verified: grep -c '  async function handleUploadExcel() {' .../DataManagementModal.svelte)
// REPLACE the whole function at DataManagementModal.svelte:100-135 with:

  async function handleUpload() {
    if (!uploadFiles || uploadFiles.length === 0) {
      uploadStatus = {
        type: "error",
        message: "Please select a file first.",
      };
      return;
    }
    const file = uploadFiles[0];

    uploadStatus = { type: null, message: "Uploading..." };
    const formData = new FormData();
    formData.append("file", file);

    try {
      const result = await uploadAgentData(agentId, formData);
      uploadStatus = formatUploadStatus(result);
    } catch (error: any) {
      console.error("Upload Error", error);
      const payload = uploadPayloadFromError(error);
      // FILL IN: when `payload` is defined use formatUploadStatus(payload);
      // otherwise fall back to { type: "error", message: error.message || "Upload failed." }
      // — bounded by AC3 (a 400 must show errors[].filename/error, never "HTTP 400").
    }

    // FILL IN: clear `uploadFiles` only when uploadStatus.type !== "error", and
    // schedule the existing 3-second reset ONLY when uploadStatus.type === "success"
    // — bounded by AC4 and the auto-clear constraint above.
  }

// ALSO at line 38-41, widen the state type:
//   let uploadStatus = $state<{ type: "success" | "error" | null; message: string }>(
//     -> let uploadStatus = $state<{ type: UploadStatusType | null; message: string }>(
// ALSO add to the import block at :4-8's neighbourhood:
//   import { formatUploadStatus, uploadPayloadFromError } from "./upload-status";
//   import type { UploadStatusType } from "./upload-status";
```
**Why**: the extension guard is deleted outright rather than widened, because a
UI allowlist would be a second source of truth beside the session store and
would drift (spec §8, Q1). The catch block is the subtle half: `error.message`
on a 400 is the literal `"HTTP 400"`, so it is only the fallback for a network
or timeout error — the per-file reasons must come from the preserved body. Do
not change the empty-selection guard, the `FormData.append("file", file)` key,
or the `console.error` call.

### `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte` (MODIFY — markup)
```html
<!-- occurrences: 1 each (verified by grep -c on each literal below) -->
<!-- :249  remove the attribute entirely -->
        accept=".xlsx"            ->   (delete this line)

<!-- :255  rebind the button -->
        onclick={handleUploadExcel}   ->   onclick={handleUpload}

<!-- :225 / :228 / :243  copy -->
  >Upload Excel</span                  ->   >Upload File</span
  >Upload .xlsx file as dataset</span  ->   >Any file is stored for the agent; .xlsx, .xls and .csv also register as datasets</span
  >Click to choose .xlsx file</span     ->   >Click to choose a file</span

<!-- :261-267  three-colour status -->
<!-- FILL IN: replace the two-way ternary on uploadStatus.type with a three-way
     mapping — "error" -> text-red-500, "warning" -> text-amber-500,
     "success" -> text-green-500 — bounded by AC4. Keep the surrounding
     `mt-2 text-xs font-medium` classes and the {#if uploadStatus.type} guard. -->
```
**Why**: removing `accept` is what makes a `.docx` selectable at all — deleting
only the JS guard would still leave the OS dialog filtered, and the issue names
both. The copy must stop saying "Excel" or it contradicts the new behaviour.

### `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.test.ts` (CREATE)
```ts
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataManagementModal from "./DataManagementModal.svelte";

const uploadAgentData = vi.fn();
const refreshAgentData = vi.fn();
const addAgentQuery = vi.fn();

vi.mock("$lib/api/agent", () => ({
  uploadAgentData: (...args: unknown[]) => uploadAgentData(...args),
  refreshAgentData: (...args: unknown[]) => refreshAgentData(...args),
  addAgentQuery: (...args: unknown[]) => addAgentQuery(...args),
}));

/** A FileList standing in for the one the picker binds. */
function fileListOf(file: File): FileList {
  return {
    0: file,
    length: 1,
    item: (i: number) => (i === 0 ? file : null),
    [Symbol.iterator]: function* () { yield file; },
  } as unknown as FileList;
}

describe("DataManagementModal upload", () => {
  beforeEach(() => {
    uploadAgentData.mockReset();
    refreshAgentData.mockReset();
    addAgentQuery.mockReset();
  });

  it("sends a .docx instead of blocking it", async () => {
    // FILL IN: render with { open: true, agentId: "a" }, put a
    // new File(["x"], "report.docx") on the file input, click Upload, and
    // assert uploadAgentData was called — bounded by AC1.
  });

  it("shows the server's report, not a fixed string", async () => {
    // FILL IN: resolve uploadAgentData with
    // { files: [{ file_id: "f-1", filename: "report.docx" }], dataframes: [], errors: [], agent: "a" }
    // and assert the rendered status is derived from it and is not "Uploaded"
    // — bounded by AC2.
  });

  it("shows the per-file reason behind a 400", async () => {
    // FILL IN: reject uploadAgentData with an ApiError-shaped object
    // { message: "HTTP 400", raw: { response: { status: 400, data: {
    //   files: [], dataframes: [], errors: [{ filename: "bad.docx", error: "invalid" }] } } } }
    // then assert "bad.docx" and "invalid" are rendered and "HTTP 400" is not
    // — bounded by AC3.
  });
});
```
**Why**: the three tests map one-to-one onto AC1, AC2 and AC3 — the three claims
the issue makes. The hand-rolled `FileList` is needed because jsdom will not let
you assign a real one to `bind:files`. Mock `$lib/api/agent` as a whole (the
`MyToolkitSettings.test.ts` idiom) so the component's other imports resolve.

### `packages/ai-parrot-server/tests/ui/test_vitest_data_management_modal.py` (CREATE)
```python
from ._vitest import run_vitest


def test_data_management_modal_vitest():
    run_vitest("src/lib/components/agents/DataManagementModal.test.ts")
```
**Why**: the task tier runs pytest only; `run_vitest` skips cleanly without the
node toolchain.

### FILL IN checklist
- [ ] `DataManagementModal.svelte::handleUpload` catch branch — payload vs
      `error.message` fallback; bounded by AC3.
- [ ] `DataManagementModal.svelte::handleUpload` tail — conditional
      `uploadFiles` clear and success-only 3s reset; bounded by AC4.
- [ ] `DataManagementModal.svelte` status `<p>` — three-way colour mapping;
      bounded by AC4.
- [ ] `DataManagementModal.test.ts` — the three test bodies; bounded by AC1–AC3.

---

## Acceptance Criteria

- [ ] AC1. Neither the `.xlsx`/`.xls` guard nor `accept=".xlsx"` remains; a
      `.docx` chosen in the modal reaches `uploadAgentData`.
- [ ] AC2. The literal status `"Uploaded"` appears nowhere; every post-request
      status comes from `formatUploadStatus`.
- [ ] AC3. A 400 renders its `errors[].filename` / `errors[].error`, and the
      rendered text does not contain `HTTP 400`.
- [ ] AC4. A partial result renders amber, distinct from a green success, and is
      not auto-cleared after 3 seconds.
- [ ] AC7. No backend file and nothing under `src/lib/types/generated/` changes.
- [ ] Validation commands pass.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_data_management_modal.py -q`

---

## Test Specification

Covered by `DataManagementModal.test.ts` above, run through the bridge.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-6630fd230436 --feature-id FEAT-739`)
2. **Read the spec** at `sdd/specs/fixgroup-6630fd230436.spec.md`
3. **Check dependencies** — TASK-4680 must be `"done"` in
   `sdd/tasks/index/fixgroup-6630fd230436.json`.
4. **Verify the Codebase Contract** — in particular that `./upload-status`
   exports `formatUploadStatus`, `uploadPayloadFromError` and `UploadStatusType`.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
7. **Verify** the acceptance criteria; run the Validation Commands.
8. **Commit the code** — stage only this task's three files.
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4681 fixgroup-6630fd230436 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5.5 (/sdd-fix, agent:sdd-fix)
**Date**: 2026-10-24
**Notes**: Deleted the `.xlsx`/`.xls` guard and the `accept=".xlsx"` attribute,
renamed `handleUploadExcel` -> `handleUpload` (and its `onclick`), and replaced
the hardcoded `"Uploaded"` with `formatUploadStatus(result)`. The catch branch
reads `uploadPayloadFromError(error)` first and only falls back to
`error.message` when there is no body, so a 400 shows `bad.docx: invalid`
instead of the literal `HTTP 400`. `uploadFiles` is now cleared only when the
status is not an error, and the 3-second auto-clear runs only on success.
Status paragraph widened to three colours (red / amber / green). Copy updated:
"Upload File", "Any file is stored for the agent; .xlsx, .xls and .csv also
register as datasets", "Click to choose a file".

Evidence: `pnpm exec vitest run` over the feature's three files -> 3 files,
28 tests passed; `pytest .../test_vitest_data_management_modal.py
.../test_vitest_upload_status.py -q` -> 2 passed; `pnpm exec vite build` -> exit 0.

Two test-harness facts worth recording, both found by running the tests rather
than assumed: (1) `AppDialog` portals its content to `document.body`, so the
upload controls are NOT inside render()'s `container` — the test queries
`document`. (2) `bind:files` assigns back to `input.files`, so the stubbed
`FileList` must be defined `writable: true` or Svelte throws
"Cannot assign to read only property 'files'". The module mock also had to
spread `importOriginal()`, because the modal mounts `MCPServerTab`, which eagerly
calls `getAgentMCPServers` from the same module on render.

**Deviations from spec**: none
