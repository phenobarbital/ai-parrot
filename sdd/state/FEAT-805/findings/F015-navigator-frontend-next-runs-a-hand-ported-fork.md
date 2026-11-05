---
id: F015
query_id: Q015
type: tree
intent: "How is SDD installed today in the reference non-Python repository?"
executed_at: 2026-11-04T22:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F015 — `navigator-frontend-next` runs a hand-ported SDD fork; its state files are format-compatible

## Summary

The reference repository (`/home/jesuslara/proyectos/navigator/navigator-frontend-next`,
SvelteKit + TypeScript, `pnpm@9.15.9`, no `pyproject.toml`) carries a JavaScript port of
the SDD helpers and prompts rewritten for `pnpm check` / `pnpm test` / `vitest`. It has
no `sdd/config.json`, no `.parrot/`, and none of `/sdd-brief`, `/sdd-fix`, the ledger or
`worktree ensure`. Its ID ledger and per-spec indexes use the same schema as ai-parrot.
`parrot sdd install --dry-run` against it plans 53 actions with no non-Python warning.

## Citations

- path: `navigator-frontend-next:scripts/sdd/`
  lines: 1-1235
  symbol: null
  excerpt: |
    check-id-collisions.mjs (256)  close-task.sh (115)  heal-orphans.sh (85)
    id-ledger.mjs (203)  reserve-ids.mjs (422)  sdd-meta.mjs (154)

- path: `navigator-frontend-next:package.json`
  lines: 1-1
  symbol: `scripts`
  excerpt: |
    "check": "svelte-kit sync && svelte-check --tsconfig ./tsconfig.json && pnpm check:themes",
    "test": "vitest run",
    "format": "prettier --write .",
    "lint": "prettier --check ."

- path: `navigator-frontend-next:sdd/tasks/.id_ledger.json`
  lines: 1-6
  symbol: null
  excerpt: |
    { "next_task_id": 523, "next_feature_id": 253, "updated_at": "2026-10-16T03:24:06+00:00", ... }

- path: `navigator-frontend-next:sdd/tasks/index/agentcrew-changes.json`
  lines: 1-1
  symbol: null
  excerpt: |
    keys: feature, feature_id, spec, type, base_branch, created_at, completed_at, tasks[9]

## Notes

Last commit touching `.claude/commands` or `scripts/sdd`: 2026-09-04 (`4f945a05`), the
commands themselves from 2026-06-15 (`80e9d031`). The dry-run plan overwrites the 20
forked commands/agents ("not recorded in the receipt"), seeds `sdd/CONVENTIONS.md` and
`sdd/config.json`, and registers the guard, ledger hooks and the sdd-coder toolkits. The
dry-run changed nothing; the repository had unrelated uncommitted work at the time
(`src/lib/services/websocket-service.ts`, `src/lib/stores/websocket.svelte.ts`).
Its `lint` script is `prettier --check .` and its type check is `svelte-check` — the
toolchain a language profile has to detect.
