# TASK-3664: Admin UI: lib/api/studio.ts + schema-driven SchemaForm component

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3663
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (first half), AC14: the toolkit drawer renders from the schema ALONE — no
toolkit-specific frontend code. SchemaForm is also reused by the chat "My tool settings" tab
(TASK-3666). The validation contract only accepts pytest commands, so a tiny pytest wrapper runs
the vitest file (skips when node tooling is absent).

---

## Scope

- `studio.ts`: the functions listed in spec §3 M12 (schema, agent toolkits list/put/delete,
  options, mcp servers get/put, reload, my override get/put/delete). Use the final GET-list path
  recorded by TASK-3660's Completion Note.
- `SchemaForm.svelte` props: `{ schema, value, overridable?, showOverridable?, optionsLoader?, readonly?, onchange }`.
  Widgets: string (text; `x-secret` → password, shows `********` placeholder when value equals the
  mask), integer/number, boolean (Switch), enum/Literal (select), array of strings (StringListEditor
  or multi-select when `x-options` + `optionsLoader`), object (JsonEditor), `x-server-managed`
  (read-only note "wired by the server"), array whose `items` is a `oneOf` with discriminator →
  list of cards, each with a kind selector + the branch's sub-form (recursive SchemaForm).
  `$ref` resolved against `schema.$defs`. Per-property "users may override" toggle when `showOverridable`.
  Dynamic options failure → free-text fallback + inline hint.
- vitest: renders text/secret/bool; oneOf kind switch swaps sub-fields; options loader failure falls back.
- pytest helper + wrapper.

**NOT in scope**: the Tools tab composition (TASK-3665).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/api/studio.ts` | CREATE | Typed client for the /api/v1/astudio tooling endpoints |
| `packages/ai-parrot-server/ui/src/lib/components/schema-form/SchemaForm.svelte` | CREATE | Renders a JSON Schema (incl. oneOf kind selector, secrets, dynamic options) |
| `packages/ai-parrot-server/ui/src/lib/components/schema-form/SchemaForm.test.ts` | CREATE | vitest + @testing-library/svelte |
| `packages/ai-parrot-server/tests/ui/__init__.py` | CREATE | Package marker |
| `packages/ai-parrot-server/tests/ui/_vitest.py` | CREATE | pytest → vitest runner helper |
| `packages/ai-parrot-server/tests/ui/test_vitest_schema_form.py` | CREATE | pytest wrapper running SchemaForm.test.ts |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
// see Existing Signatures — every import path is listed there
```

### Existing Signatures to Use
```python
// packages/ai-parrot-server/ui/src/lib/api/agents.ts — `import apiClient from "$lib/api/http";` (:16); axios instance:
//   const { data } = await apiClient.get<T>(url); apiClient.put / post / delete likewise (see getAgent :34, updateAgent :58)
// packages/ai-parrot-server/ui/src/lib/api/http.ts — export class ApiError (:31); export default apiClient (:197)
// Generated types (after TASK-3663): import type { ToolkitSchemaEnvelope } from "$lib/types/generated/ToolkitSchemaEnvelope";
//   same pattern for ToolkitSpec, AgentMCPServerSpec, ConfigOption, ToolkitConfigPutRequest, AgentToolkitsResponse,
//   ToolkitPersistResponse, AgentMcpServersPutRequest, AgentMcpServersResponse, ToolkitOptionsResponse
// Widgets: $lib/ui/internal/shadcn/ui/{checkbox,label,slider,switch}/index.js (used by form/TabsCapabilities.svelte:15-18)
// Kit: $lib/ui/components — AppTabs, AppSheet (drawer), AppDialog, AppToggle, AppTooltip (index.ts)
// Existing editors: $lib/components/JsonEditor.svelte, $lib/components/StringListEditor.svelte
// Svelte 5 runes only: $state, $derived, $props, $effect — never `export let`.
```

### Does NOT Exist
- ~~`$lib/api/studio.ts`~~, ~~`SchemaForm.svelte`~~ — this task creates them.
- ~~a JSON-Schema form library dependency~~ — do NOT add one (no package.json change); hand-rolled renderer.
- ~~any `/astudio` consumer in the SPA today~~ — none exists.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/api/studio.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/schema-form/SchemaForm.svelte",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/schema-form/SchemaForm.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/_vitest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_schema_form.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Keep SchemaForm ≤ ~250 lines; split `SchemaField.svelte` (one property) out if needed — list it
  in the Completion Note (same directory).
- Emit a new object on every change (`onchange({...value, [key]: v}, overridable)`) — no in-place mutation of props.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write `studio.ts` — *why*: typed boundary for both UI tasks.
2. Write SchemaForm (+ optional SchemaField) — *why*: AC14 schema-only rendering.
3. vitest file, then the pytest helper + wrapper — *why*: validation contract requires pytest.

### `packages/ai-parrot-server/ui/src/lib/api/studio.ts` (CREATE)
```ts
/** Agent Studio tooling client (FEAT-593). */
import apiClient from "$lib/api/http";
import type { AgentMCPServerSpec } from "$lib/types/generated/AgentMCPServerSpec";
import type { AgentMcpServersResponse } from "$lib/types/generated/AgentMcpServersResponse";
import type { AgentToolkitsResponse } from "$lib/types/generated/AgentToolkitsResponse";
import type { ConfigOption } from "$lib/types/generated/ConfigOption";
import type { ToolkitConfigPutRequest } from "$lib/types/generated/ToolkitConfigPutRequest";
import type { ToolkitPersistResponse } from "$lib/types/generated/ToolkitPersistResponse";
import type { ToolkitSchemaEnvelope } from "$lib/types/generated/ToolkitSchemaEnvelope";

const BASE = "/api/v1/astudio";
const enc = encodeURIComponent;

export async function getToolkitSchema(slug: string): Promise<ToolkitSchemaEnvelope> {
  const { data } = await apiClient.get<ToolkitSchemaEnvelope>(`${BASE}/toolkits/${enc(slug)}/schema`);
  return data;
}

export async function putAgentToolkit(name: string, slug: string, body: ToolkitConfigPutRequest): Promise<ToolkitPersistResponse> {
  const { data } = await apiClient.put<ToolkitPersistResponse>(`${BASE}/agents/${enc(name)}/toolkits/${enc(slug)}`, body);
  return data;
}

// FILL IN: getAgentToolkits (path per TASK-3660 Completion Note), deleteAgentToolkit, getToolkitOptions
//   (returns ConfigOption[] from ToolkitOptionsResponse.options), getAgentMcpServers, putAgentMcpServers
//   ({ servers }), reloadAgent (POST `${BASE}/agents/${name}/reload`), getMyToolkitOverride,
//   putMyToolkitOverride, deleteMyToolkitOverride (`/agents/${name}/toolkits/${slug}/me`)
```

### `packages/ai-parrot-server/ui/src/lib/components/schema-form/SchemaForm.svelte` (CREATE — skeleton)
```svelte
<!-- SchemaForm (FEAT-593) — renders a Draft 2020-12 object schema; no toolkit-specific code. -->
<script lang="ts">
  import type { ConfigOption } from "$lib/types/generated/ConfigOption";
  import SchemaForm from "./SchemaForm.svelte";

  type JsonSchema = Record<string, any>;
  let {
    schema,
    value,
    overridable = [],
    showOverridable = false,
    optionsLoader,
    readonly = false,
    onchange,
    root,
  }: {
    schema: JsonSchema;
    value: Record<string, unknown>;
    overridable?: string[];
    showOverridable?: boolean;
    optionsLoader?: (param: string) => Promise<ConfigOption[]>;
    readonly?: boolean;
    onchange: (value: Record<string, unknown>, overridable: string[]) => void;
    root?: JsonSchema; // $defs holder for recursive sub-forms
  } = $props();

  const defs = $derived((root ?? schema).$defs ?? {});
  const props = $derived(Object.entries(schema.properties ?? {}) as [string, JsonSchema][]);
  const required = $derived(new Set<string>(schema.required ?? []));

  function resolve(s: JsonSchema): JsonSchema {
    // FILL IN: follow "$ref": "#/$defs/X" into defs; unwrap anyOf [X, null] (Optional)
    return s;
  }

  function set(key: string, v: unknown): void {
    onchange({ ...value, [key]: v }, overridable);
  }

  function toggleOverridable(key: string, on: boolean): void {
    onchange(value, on ? [...overridable, key] : overridable.filter((k) => k !== key));
  }
</script>

<!-- FILL IN: one row per prop — label (+ required marker, x-ui-help/description tooltip), widget chosen by
     resolve(prop): x-server-managed → read-only note; x-secret → password input; enum → select; boolean → Switch;
     integer/number → number input; array+x-options+optionsLoader → multi-select with free-text fallback;
     array of strings → StringListEditor; array with items.oneOf → cards (kind select + <SchemaForm schema={branch} root={root ?? schema} …/>);
     object → JsonEditor; showOverridable → Switch "users may override" bound to overridable.includes(key) -->
```
**Why this shape**: recursion (`SchemaForm` importing itself with `root`) handles `oneOf` branches
without toolkit-specific code (AC14).

### `packages/ai-parrot-server/tests/ui/_vitest.py` (CREATE)
```python
"""Run a vitest file from pytest (FEAT-593 validation contract accepts pytest commands only)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[2] / "ui"


def run_vitest(*files: str) -> None:
    """Run ``pnpm exec vitest run <files>`` in the admin UI; skip when node tooling is absent."""
    if shutil.which("pnpm") is None or not (UI_DIR / "node_modules").is_dir():
        pytest.skip("pnpm / ui node_modules not available")
    proc = subprocess.run(["pnpm", "exec", "vitest", "run", *files], cwd=UI_DIR, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
```

### `packages/ai-parrot-server/tests/ui/test_vitest_schema_form.py` (CREATE)
```python
from ._vitest import run_vitest


def test_schema_form_vitest():
    run_vitest("src/lib/components/schema-form/SchemaForm.test.ts")
```
Also create an empty `packages/ai-parrot-server/tests/ui/__init__.py`.

### FILL IN checklist
- [ ] Remaining studio.ts functions; bounded by spec §2 HTTP table + TASK-3660 final GET path
- [ ] `resolve()` ($ref + Optional unwrap); bounded by pydantic's schema output
- [ ] Widget markup per rule list; bounded by AC14

---

## Acceptance Criteria

- [ ] SchemaForm renders the `dataset_manager` schema with a kind selector that swaps sub-fields (AC14).
- [ ] `x-secret` fields are password inputs; `x-server-managed` read-only.
- [ ] Options loader failure → free text.
- [ ] `pnpm build` succeeds; vitest file passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_schema_form.py -q`

---

## Test Specification

```python
// packages/ai-parrot-server/ui/src/lib/components/schema-form/SchemaForm.test.ts  (vitest + @testing-library/svelte)
// FILL IN: import { render, screen, fireEvent } from "@testing-library/svelte"; import SchemaForm from "./SchemaForm.svelte";
// test("secret renders as password"), test("oneOf kind switch swaps branch fields"),
// test("options loader rejection falls back to text input"), test("server-managed is read-only")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `glm` (`zai.glm-4.7-flash`, MCP backend `nova`), delivered via `coder_run_chunk` job `job-35d6c2136ab8`, attempt 2 `332e54c81194442691cacc580ada9524`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `a70aefd95` (`feat(FEAT-593): TASK-3664 — Admin UI: lib/api/studio.ts + schema-driven SchemaForm component`)
**Lint autofix SHA**: `322dcb21c` (`style(tool-configuration-agentstudio): TASK-3664 — engine lint autofix`, 0 residual, 0 errors)
**Merge commit**: `4c5d8e173`
**Review**: `coder_record_review` recorded — `feedback_id: coder-review:0d21c3a43003cba4b639121d`, `fix_commits: []`.

**Notes**: Attempt 1 on seat `minimax` (`minimax.minimax-m2.5`) failed with `DispatchOutputValidationError: No
assistant text found in dispatch result` (infra/dispatch-layer failure, 21 turns, no delivered diff) — this is
an MCP-seat dispatch failure the engine classifies/handles internally (per protocol, not reported via
`coder_suspend_model`, which is reserved for native attempts or confirmed critical review defects). Attempt 2
on seat `glm` (`zai.glm-4.7-flash`) completed cleanly (59 turns) and is the merged delivery. Diff verified
against the task's file table: `ui/src/lib/api/studio.ts` (CREATE, 88 insertions — typed client for
`/api/v1/astudio` tooling endpoints), `ui/src/lib/components/schema-form/SchemaForm.svelte` (CREATE, 291
insertions — JSON Schema renderer incl. `oneOf` kind selector, secrets, dynamic options),
`SchemaForm.test.ts` (CREATE, 199 insertions, vitest + `@testing-library/svelte`), `tests/ui/__init__.py`
(CREATE, package marker), `tests/ui/_vitest.py` (CREATE, pytest → vitest runner helper), and
`tests/ui/test_vitest_schema_form.py` (CREATE, pytest wrapper) — exactly the 6 declared files, no unlisted
files, nothing under `sdd/` touched. 0 lint residual.

**Deviations from spec**: none.
