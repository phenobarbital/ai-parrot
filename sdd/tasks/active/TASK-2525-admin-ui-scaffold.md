# TASK-2525: Admin UI scaffold — Vite + Svelte 5 project with copied tokens and primitives

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (UI half) + §3 Module 3 (scaffold part). Creates the
buildable frontend project at `packages/ai-parrot-server/ui/` with the
copy-in reuse base from `navigator-frontend-next`: Tailwind v4 token chain,
vendored shadcn-svelte primitives, `cn()`. Everything later (shell, pages)
builds inside this project.

---

## Scope

- Scaffold `packages/ai-parrot-server/ui/` as a pnpm + Vite + Svelte 5 +
  TypeScript SPA (NO SvelteKit):
  - `package.json` (`"packageManager": "pnpm@9..."`, engines Node >=24),
    `vite.config.ts` (`base: '/admin/'`, `@tailwindcss/vite` plugin, dev
    proxy `/api` → `http://localhost:5000` configurable via env), `tsconfig.json`,
    `svelte.config.js` (vitePreprocess), `vitest` + `@testing-library/svelte`
    + `jsdom` config, `index.html`, `src/main.ts`, `src/App.svelte` placeholder.
  - Build output dir: `../src/parrot/server/ui/dist` (relative to `ui/`),
    emptied on build.
- Copy-in from `/home/jesuslara/proyectos/navigator-frontend-next`:
  - Tailwind v4 token chain: the `@theme inline` mapping from `src/app.css`
    (lines 21-62) and `src/lib/styles/themes/{_schema,_tokens,light,dark}.css`
    (midnight/warm optional). Do NOT port the vestigial root `tailwind.config.ts`.
  - The shadcn primitives the foundation needs (at minimum: button, card,
    input, label, badge, separator, skeleton, select, dialog, avatar) from
    `src/lib/ui/internal/shadcn/ui/` + `internal/shadcn/utils.ts` (`cn()`),
    preserving the internal/ vs components/ layering and `src/lib/ui/README.md`
    conventions (copy the README too).
  - Copy `.agent/skills/svelte5-structural/SKILL.md` (+ `references/`) into
    `packages/ai-parrot-server/ui/docs/` for implementing agents.
- Replace SvelteKit couplings in copied code: `$app/environment`,
  `$app/navigation`, `$env/dynamic/public` → `import.meta.env` / small shims.
- `pnpm build` must produce `dist/index.html` + `dist/assets/*` with hashed
  filenames; `pnpm test` runs vitest; add a trivial smoke test.

**NOT in scope**: router/auth stores (TASK-2527), login/layout (TASK-2528),
codegen (TASK-2526), CI (TASK-2531).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/package.json` | CREATE | pnpm project, scripts: dev/build/test/generate(placeholder) |
| `packages/ai-parrot-server/ui/vite.config.ts` | CREATE | base /admin/, outDir ../src/parrot/server/ui/dist, proxy |
| `packages/ai-parrot-server/ui/tsconfig.json`, `svelte.config.js`, `vitest.config.ts`, `index.html` | CREATE | toolchain |
| `packages/ai-parrot-server/ui/src/{main.ts,App.svelte,app.css}` | CREATE | entry + token chain |
| `packages/ai-parrot-server/ui/src/lib/styles/themes/*.css` | CREATE | copied token files |
| `packages/ai-parrot-server/ui/src/lib/ui/internal/shadcn/**` | CREATE | vendored primitives + utils.ts |
| `packages/ai-parrot-server/ui/docs/svelte5-structural/**` | CREATE | copied skill doc |
| `.gitignore` | MODIFY | `packages/ai-parrot-server/ui/node_modules/` (dist ignore added in TASK-2523) |

---

## Codebase Contract (Anti-Hallucination)

### Copy-in sources (verified in /home/jesuslara/proyectos/navigator-frontend-next)
- `package.json` — installed versions to match: svelte **5.55.7**, vite
  **5.4.21**, bits-ui **2.18.1**, tailwindcss **4.3.0**, typescript
  **5.9.3**, tailwind-variants 3.2.2, tailwind-merge 3.6.0, clsx 2.1.1,
  `@tailwindcss/vite ^4.1.0`, vitest ^3.2.7, `@testing-library/svelte`
  ^5.4.2, jsdom. `"packageManager": "pnpm@9.15.9"`.
- `src/app.css` — `@import "tailwindcss"`, `@custom-variant dark
  (&:where(.dark, .dark *))`, `@theme inline { … }` (lines 21-62: full
  ShadCN token map --color-background/…/-sidebar*, --radius-sm/md/lg/xl).
  The rest of that 1180-line file is legacy component CSS — do NOT copy it.
- `src/lib/styles/themes/index.css` (import-order registry), `_schema.css`
  (canonical slot list), `_tokens.css` (oklch scales), `light.css`
  (`:root, [data-theme="light"]`, `--radius: 0.625rem`), `dark.css`.
- `src/lib/ui/internal/shadcn/ui/<family>/` — 21 families, each with an
  `index.ts` barrel; `src/lib/ui/internal/shadcn/utils.ts` — `cn()`.
- `src/lib/ui/README.md` — semantic tokens inside `internal/shadcn/ui/`,
  scale tokens in wrappers/pages, never arbitrary values.
- `vite.config.ts` — dev proxy precedent (`/api`, `/ws`, `/static` →
  `PUBLIC_API_URL`); `envDir: ./env`.
- `.agent/skills/svelte5-structural/SKILL.md` (268 lines) +
  `references/{patterns.md,state-matchines.md,widgets.md}` (typo in
  filename is real).

### Server-side contract
- Build output target `packages/ai-parrot-server/src/parrot/server/ui/dist/`
  is what TASK-2523's `setup_admin_ui` serves and what
  `pyproject.toml` package-data (`"parrot.server.ui" = ["dist/*",
  "dist/assets/*"]`) ships — keep Vite output FLAT: `index.html` at root,
  everything else under `assets/` (default Vite behavior; enforce with
  `build.assetsDir = 'assets'`).

### Does NOT Exist
- ~~`shadcn-svelte` as an npm dependency~~ — components are vendored
  copies; there is no CLI-managed dependency to install.
- ~~a usable root `tailwind.config.ts` in navigator-frontend-next~~ —
  vestigial v3-style file; Tailwind v4 is CSS-first (`@theme`).
- ~~SvelteKit modules in this project~~ — `$app/*`, `$env/*` must NOT be
  imported; shim or replace during copy.
- ~~any existing frontend source in ai-parrot~~ — `agentui/`,
  `crew-builder/` are dead caches; this is the first real UI tree.

---

## Implementation Notes

### Key Constraints
- pnpm 9 + Node 24 LTS (engines field; do not commit a Node version manager
  config beyond `.nvmrc`/engines).
- `pnpm-lock.yaml` IS committed (source of reproducible CI builds).
- Keep the vendored primitives byte-faithful where possible — divergence is
  allowed later, but the initial copy should be reviewable as a copy.
- Evaluate current Vite major at scaffold time (spec §7 gotcha) — corporate
  pins 5.4; prefer the newest major that works with `@tailwindcss/vite`
  and svelte 5 plugin, and record the choice in the completion note.
- The `generate` script is a placeholder (`echo`) until TASK-2526 lands.

### References in Codebase
- Spec §6 "navigator-frontend-next reuse inventory" — authoritative list.

---

## Acceptance Criteria

- [ ] `pnpm install && pnpm build` (Node 24) produces
  `packages/ai-parrot-server/src/parrot/server/ui/dist/index.html` +
  hashed `dist/assets/*`.
- [ ] Built `index.html` references assets under `/admin/assets/` (base
  path correct).
- [ ] `pnpm test` runs vitest and the smoke test passes.
- [ ] Copied token chain compiles; a sample page using `bg-background` /
  `text-foreground` + one primitive (Button) renders in dev mode.
- [ ] No `$app/*` or `$env/*` imports anywhere (`grep` clean).
- [ ] `pnpm dev` proxies `/api` to a configurable backend origin.

---

## Test Specification

```typescript
// packages/ai-parrot-server/ui/src/App.test.ts (smoke)
import { render } from '@testing-library/svelte';
import App from './App.svelte';

test('renders shell placeholder', () => {
  const { getByText } = render(App);
  expect(getByText(/parrot/i)).toBeTruthy();
});
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the navigator-frontend-next
   paths exist before copying; if the repo moved, STOP and report
4. **Update status** in `sdd/tasks/index/ui-server-backend.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Blocker (STOP condition triggered by sdd-worker, 2026-08-27)

Per this task's own Agent Instructions step 3: "Verify the Codebase
Contract — confirm the navigator-frontend-next paths exist before
copying; if the repo moved, STOP and report."

Verified: `/home/jesuslara/proyectos/navigator-frontend-next` **does
not exist** on this machine (`ls` -> "No existe el archivo o el
directorio"). Checked `~/proyectos/` in full — it is not present under
any name. Searched the filesystem (`find / -maxdepth 4 -iname
"*navigator-frontend*"`) and this repo (`.gitmodules`, vendored
`shadcn`/`svelte5-structural` copies) for any local mirror — none
found. None of the copy-in sources this task requires are reachable:

- `package.json` (pinned dependency versions to match)
- `src/app.css` (Tailwind v4 `@theme inline` token map, lines 21-62)
- `src/lib/styles/themes/{_schema,_tokens,light,dark}.css`
- `src/lib/ui/internal/shadcn/ui/<21 families>/` + `utils.ts` (`cn()`)
- `src/lib/ui/README.md`
- `.agent/skills/svelte5-structural/SKILL.md` + `references/`

Fabricating this content from memory/imagination instead of copying
the verified source would violate the anti-hallucination contract and
Cardinal Rule 1 (builder, not architect) — a hand-invented token chain
and component set is not "the copy-in reuse base from
navigator-frontend-next" the spec and task both mandate, and would
silently diverge from a design decision (maximal copy-in reuse,
byte-faithful initial vendoring) that a human made deliberately.

**Downstream impact**: TASK-2526, 2527, 2528, 2529, 2530, and 2531 all
transitively depend on this task's `packages/ai-parrot-server/ui/`
scaffold and cannot proceed either.

**Action needed from a human/orchestrator**: make
`navigator-frontend-next` available in this environment (clone it
alongside `ai-parrot` at `~/proyectos/navigator-frontend-next`, as the
spec's Codebase Contract assumes), or provide an alternate copy-in
source, before this task (and its dependents) can be implemented.

---

## Completion Note

*(Agent fills this in when done — NOT done; see Blocker above)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
