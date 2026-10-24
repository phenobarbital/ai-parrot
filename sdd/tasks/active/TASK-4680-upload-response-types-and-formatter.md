# TASK-4680: Typed upload response and the status formatter

**Feature**: FEAT-739 — Admin UI accepts every upload the backend stores, and reports what it stored
**Spec**: `sdd/specs/fixgroup-6630fd230436.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:04dcfd611ebc`

---

## Context

FEAT-639 replaced the agent upload response with an honest report
(`{files, dataframes, errors, agent}`) and answers **400** when nothing was
stored. The admin UI never caught up: `uploadAgentData` is typed `Promise<any>`
and `DataManagementModal` throws the body away in favour of a hardcoded
`"Uploaded"` string (spec §1, holes 1 and 2).

This task builds the two pieces the modal will consume in TASK-4681: the
declared response types, and one pure function that turns an upload payload
into the status line the modal shows. It implements spec §3 Modules 1 and 2.

Keeping the formatter in a plain `.ts` module (not inside the `.svelte` file)
is deliberate: it is the part with all the branching, and it can then be unit
tested without rendering a component.

---

## Scope

- Declare `AgentUploadFileRecord`, `AgentUploadFileError` and
  `AgentUploadResponse` in `$lib/api/agent` and give `uploadAgentData` the
  return type `Promise<AgentUploadResponse>`.
- Implement `formatUploadStatus(payload: unknown): UploadStatus` and
  `uploadPayloadFromError(error: unknown): unknown` in a new
  `upload-status.ts`, per the contract in spec §3 Module 1.
- Write `upload-status.test.ts` covering the four status outcomes plus the
  malformed-input cases.
- Extend `agent.test.ts` with one test asserting `uploadAgentData` PUTs the
  multipart body and returns the response body unchanged.
- Add the pytest→vitest bridge wrapper so these run under the task tier.

**NOT in scope**:
- `DataManagementModal.svelte` and its test — that is TASK-4681.
- Any change to the HTTP request itself (method, path, headers). This is a
  typing change plus a new pure module; the wire call is untouched.
- Any backend file.
- Touching `src/lib/types/generated/` — it is produced by `pnpm generate` and
  holds no type for this response (spec §6 "Does NOT Exist").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/api/agent.ts` | MODIFY | Declare the three interfaces; type `uploadAgentData` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/upload-status.ts` | CREATE | `formatUploadStatus` + `uploadPayloadFromError` |
| `packages/ai-parrot-server/ui/src/lib/components/agents/upload-status.test.ts` | CREATE | Unit tests for the formatter |
| `packages/ai-parrot-server/ui/src/lib/api/agent.test.ts` | MODIFY | One test for `uploadAgentData` |
| `packages/ai-parrot-server/tests/ui/test_vitest_upload_status.py` | CREATE | pytest bridge running the two vitest files |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `be519ab78` (dev), 2026-10-24.

### Verified Imports

```ts
import apiClient from "$lib/api/http";                       // agent.test.ts:3 (default export)
import { afterEach, describe, expect, it, vi } from "vitest"; // agent.test.ts:1
import type { AxiosInstance } from "axios";                   // already imported by agent.ts
```

```python
from ._vitest import run_vitest   # verified: packages/ai-parrot-server/tests/ui/_vitest.py:20
```

### Existing Signatures to Use

```ts
// packages/ai-parrot-server/ui/src/lib/api/agent.ts:153
export const uploadAgentData = async (
  agentName: string,
  formData: FormData,
  client?: AxiosInstance,
): Promise<any> => {
  const http = client ?? apiClient;
  const response = await http.put(`${BASE_PATH}/${agentName}`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
};
// BASE_PATH is module-local in agent.ts and resolves to "/api/v1/agents/chat".

// packages/ai-parrot-server/ui/src/lib/api/http.ts:31
export class ApiError extends Error {
  constructor(message: string,
              code: "network" | "timeout" | "server" | "auth" | "unknown",
              status?: number,
              raw?: unknown)
}
// safeRaw (http.ts:51-73) builds `raw` as
//   { message, code, response: { status, statusText, data }, request: {...} }
// so the upload body is at raw.response.data — and ONLY there.
```

```python
# packages/ai-parrot-server/tests/ui/_vitest.py:20
def run_vitest(*files: str) -> None:
    """Run ``pnpm exec vitest run <files>``; skips when pnpm / ui node_modules are absent."""
```

### Does NOT Exist

- ~~`added_files`~~ — not a key of the FEAT-639 response. `test_agent_uploads.py`
  asserts `"added_files" not in response.content`. Never read or emit it.
- ~~`upload-status.ts`~~ — this task creates it.
- ~~`extractServerMessage` giving a useful upload message~~ — it exists
  (`http.ts:80`) but the upload 400 body has no `error`/`message`/`detail` key,
  so it returns the literal `"HTTP 400"`. Do not route the upload error through it.
- ~~`ApiError.data` / `ApiError.body` / `ApiError.response`~~ — not properties of
  `ApiError`. The only fields are `message`, `code`, `status`, `raw`.
- ~~a generated TS type for the upload response~~ — `src/lib/types/generated/`
  has none; declare the interfaces by hand in `agent.ts`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/api/agent.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/upload-status.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/upload-status.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/api/agent.test.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_upload_status.py",
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

- TypeScript `strict`. `formatUploadStatus` takes `unknown` and narrows it
  itself — it must never assume the shape it was handed, because it is called
  with an error body as well as a success body.
- Neither exported function may throw, for any input. AC5 is absolute: the
  modal's catch block calls them, and a throw there would lose the error.
- No prettier/eslint step exists — match the surrounding formatting (2-space
  indent, double quotes, trailing commas) by hand.

### References in Codebase

- `packages/ai-parrot-server/ui/src/lib/api/agent.test.ts` — the
  `vi.spyOn(apiClient, "post")` idiom to mirror with `"put"`.
- `packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py` — the
  one-function bridge wrapper to copy.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three interfaces to `agent.ts` and change only the return type of
   `uploadAgentData` — *why*: the formatter and the modal both need a declared
   shape, and the wire call must stay byte-identical.
2. Write `upload-status.ts` with the two exported functions — *why*: this is the
   only place that decides what an upload result says, so the success path and
   the 400 path cannot drift.
3. Write `upload-status.test.ts` — *why*: the branching lives here, so this is
   where the coverage belongs.
4. Append one `uploadAgentData` test to `agent.test.ts` — *why*: AC7 says the
   request shape is unchanged; that needs an assertion, not a promise.
5. Add the pytest bridge — *why*: the task tier runs pytest, and the vitest
   files are otherwise invisible to it.

### `packages/ai-parrot-server/ui/src/lib/api/agent.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c 'export const uploadAgentData = async (' packages/ai-parrot-server/ui/src/lib/api/agent.ts)
// BEFORE — insert above `export const uploadAgentData = async (` (verified: agent.ts:153)

/** One persisted file as the session store reports it (FEAT-639). */
export interface AgentUploadFileRecord {
  file_id: string;
  filename?: string;
  [key: string]: unknown;
}

/** One file the backend refused, with its reason. */
export interface AgentUploadFileError {
  filename: string;
  error: string;
}

/**
 * The agent upload report. The same shape arrives on a 200 and, inside
 * `ApiError.raw.response.data`, on the 400 the handler returns when nothing
 * was stored.
 */
export interface AgentUploadResponse {
  files: AgentUploadFileRecord[];
  dataframes: string[];
  errors: AgentUploadFileError[];
  agent?: string;
}

// THEN — change ONLY the return type on the existing declaration:
//   ): Promise<any> => {      ->      ): Promise<AgentUploadResponse> => {
// The body stays exactly as it is.
```
**Why**: the interfaces are the contract TASK-4681 codes against, and they are
hand-declared here because `src/lib/types/generated/` carries no type for this
response. Do not alter the method, path, headers, or the `client ?? apiClient`
fallback — AC7 and the "request unchanged" constraint depend on it.

### `packages/ai-parrot-server/ui/src/lib/components/agents/upload-status.ts` (CREATE)
```ts
/**
 * Turn an agent upload report into the status line the data-management modal
 * shows. Pure and total: every exported function here is safe to call from a
 * catch block, so neither may throw for any input (spec AC5).
 */
import type {
  AgentUploadFileError,
  AgentUploadFileRecord,
} from "$lib/api/agent";

export type UploadStatusType = "success" | "warning" | "error";

export interface UploadStatus {
  type: UploadStatusType;
  message: string;
}

/** The status shown when the payload tells us nothing usable. */
const UNKNOWN_FAILURE: UploadStatus = { type: "error", message: "Upload failed." };

function asArray(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null;
}

/**
 * Derive the status line from an upload payload.
 *
 * success  — at least one file stored and no errors
 * warning  — files stored AND some rejected
 * error    — nothing stored
 *
 * A payload that is not an object, or whose `files` / `dataframes` / `errors`
 * are missing or not arrays, yields UNKNOWN_FAILURE rather than a throw.
 */
export function formatUploadStatus(payload: unknown): UploadStatus {
  if (payload === null || typeof payload !== "object") return UNKNOWN_FAILURE;
  const p = payload as Record<string, unknown>;
  const files = asArray(p.files) as AgentUploadFileRecord[] | null;
  const dataframes = asArray(p.dataframes) as unknown[] | null;
  const errors = asArray(p.errors) as AgentUploadFileError[] | null;
  if (files === null || dataframes === null || errors === null) return UNKNOWN_FAILURE;

  // FILL IN: build the parts and pick the type — bounded by spec §3 Module 1's
  // message grammar (parts joined with " · "; stored -> `Stored <n> file(s)`,
  // omitted when empty; dataframes -> `registered as dataset(s): <a>, <b>`,
  // omitted when empty; each error -> `<filename>: <error>`, joined with "; ")
  // and by AC2/AC3/AC4. Return UNKNOWN_FAILURE only when no part can be built.
  return UNKNOWN_FAILURE;
}

/**
 * Return the response body an ApiError preserved, or undefined.
 *
 * `safeRaw` (http.ts:51-73) keeps the body at `raw.response.data` and nowhere
 * else, so that is the only path read here. Never throws.
 */
export function uploadPayloadFromError(error: unknown): unknown {
  // FILL IN: walk error -> .raw -> .response -> .data, returning undefined as
  // soon as a hop is absent or not an object — bounded by AC5 (no throw) and by
  // the verified safeRaw shape in the Codebase Contract.
  return undefined;
}
```
**Why this shape**: `formatUploadStatus` is given `unknown` because it is called
with both a success body and an error body, and the error body reaches it only
after passing through `safeRaw`. The early `asArray` guards exist so that a
partially-shaped payload degrades to one known status instead of producing a
message built from `undefined`. Do not change the exported names, the
`UploadStatusType` union, or the return type — TASK-4681 imports all three.

### `packages/ai-parrot-server/ui/src/lib/components/agents/upload-status.test.ts` (CREATE)
```ts
import { describe, expect, it } from "vitest";

import { formatUploadStatus, uploadPayloadFromError } from "./upload-status";

const CLEAN = {
  files: [{ file_id: "f-1", filename: "report.docx" }],
  dataframes: [],
  errors: [],
  agent: "a",
};
const PARTIAL = {
  files: [{ file_id: "f-1", filename: "ok.csv" }],
  dataframes: ["ok"],
  errors: [{ filename: "bad.docx", error: "invalid" }],
  agent: "a",
};
const NOTHING = {
  files: [],
  dataframes: [],
  errors: [{ filename: "bad.docx", error: "invalid" }],
  agent: "a",
};

describe("formatUploadStatus", () => {
  it("formats a clean success", () => {
    // FILL IN: assert type === "success" and that the message names the stored
    // count — bounded by the §3 Module 1 grammar.
  });

  it("names registered dataframes", () => {
    // FILL IN: assert PARTIAL's message contains "ok" as a registered dataset.
  });

  it("reports a partial result as a warning", () => {
    // FILL IN: assert PARTIAL -> type === "warning" and both the stored part
    // and "bad.docx: invalid" appear — bounded by AC4.
  });

  it("reports nothing stored as an error", () => {
    // FILL IN: assert NOTHING -> type === "error" and the per-file reason is
    // present and the message does not contain "HTTP 400" — bounded by AC3.
  });

  it.each([null, undefined, "nope", 7, {}, { files: "x", dataframes: [], errors: [] }])(
    "never throws for %p",
    (bad) => {
      // FILL IN: assert the call does not throw and returns
      // { type: "error", message: "Upload failed." } — bounded by AC5.
    },
  );
});

describe("uploadPayloadFromError", () => {
  it("reads the preserved response body", () => {
    // FILL IN: build { raw: { response: { data: NOTHING } } } and assert the
    // body comes back.
  });

  it.each([null, undefined, {}, { raw: {} }, { raw: { response: {} } }])(
    "returns undefined for %p",
    (bad) => {
      // FILL IN: assert undefined, no throw — bounded by AC5.
    },
  );
});
```
**Why**: these are the branches the modal cannot exercise cheaply, so they are
tested here against the fixtures the spec fixes. Keep the three fixtures
verbatim — TASK-4681's component test reuses the same shapes.

### `packages/ai-parrot-server/ui/src/lib/api/agent.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c 'import { chatWithAgent } from "./agent";' packages/ai-parrot-server/ui/src/lib/api/agent.test.ts)
// Change that import line to also pull in uploadAgentData:
//   import { chatWithAgent, uploadAgentData } from "./agent";
// THEN append a new describe block at END OF FILE:

describe("uploadAgentData", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("PUTs the multipart body and returns the response body", async () => {
    const body = { files: [{ file_id: "f-1" }], dataframes: [], errors: [], agent: "my-agent" };
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: body });
    const formData = new FormData();

    // FILL IN: call uploadAgentData("my-agent", formData), then assert `put`
    // received "/api/v1/agents/chat/my-agent", the same formData instance, and
    // the multipart Content-Type header, and that the returned value is `body`
    // — bounded by AC7 (request unchanged) and the verified signature.
  });
});
```
**Why**: mirrors the existing `vi.spyOn(apiClient, "post")` test so the file
stays idiomatic. The point of the assertion is that the typing change did not
move the wire call.

### `packages/ai-parrot-server/tests/ui/test_vitest_upload_status.py` (CREATE)
```python
from ._vitest import run_vitest


def test_upload_status_vitest():
    run_vitest(
        "src/lib/components/agents/upload-status.test.ts",
        "src/lib/api/agent.test.ts",
    )
```
**Why**: the task tier runs pytest only, and `run_vitest` skips cleanly when
pnpm or `ui/node_modules` are absent, so this never fails a machine without the
node toolchain.

### FILL IN checklist
- [ ] `upload-status.ts::formatUploadStatus` — the parts/joining and type
      selection; bounded by §3 Module 1's grammar and AC2/AC3/AC4.
- [ ] `upload-status.ts::uploadPayloadFromError` — the guarded property walk;
      bounded by AC5 and the verified `safeRaw` shape.
- [ ] `upload-status.test.ts` — every assertion body; bounded by the stated AC.
- [ ] `agent.test.ts::uploadAgentData` — the call and its four assertions;
      bounded by AC7.

---

## Acceptance Criteria

- [ ] `AgentUploadResponse`, `AgentUploadFileRecord` and `AgentUploadFileError`
      are exported from `$lib/api/agent`, and `uploadAgentData` returns
      `Promise<AgentUploadResponse>`.
- [ ] The `uploadAgentData` body (method, path, headers, client fallback) is
      byte-identical to `be519ab78`.
- [ ] `formatUploadStatus` returns `success` / `warning` / `error` per spec §3
      Module 1, and never throws for any input (AC5).
- [ ] `uploadPayloadFromError` returns `raw.response.data`, else `undefined`,
      and never throws.
- [ ] No file under `src/lib/types/generated/` and no backend file is modified (AC7).
- [ ] Validation commands pass.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_upload_status.py -q`

---

## Test Specification

Covered by `upload-status.test.ts` and the appended `agent.test.ts` block
above; both are run by the bridge in the Validation Commands.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-6630fd230436 --feature-id FEAT-739`)
2. **Read the spec** at `sdd/specs/fixgroup-6630fd230436.spec.md`
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** before writing any code; if an anchor moved,
   fix the contract first.
5. **Update status** in `sdd/tasks/index/fixgroup-6630fd230436.json` →
   `"in-progress"` (set `started_at`) and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   and never change a signature or path the blueprint fixes.
7. **Verify** the acceptance criteria; run the Validation Commands.
8. **Commit the code** — stage only this task's five files.
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4680 fixgroup-6630fd230436 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
