# F005 — `src/lib/fn/` is a sandbox mirror of another repo, NOT a fork (corrects F002)

**Source:** verified locally after the navigator-svelte session (FEAT-496) flagged it.
**Citations:** `navigator-svelte/src/lib/fn/README.md` (+ `HANDOFF.md`, `PORTING.md`)
**Confidence:** high (direct source read)

## What it actually is

> Sandbox mirror of **navigator-frontend-next** (FN)'s `$lib` (FEAT-446 — Port Kit,
> Fase A). Porting an FN module means copying its folder to
> `src/lib/fn/components/modules/<Mod>/` ... landed at the **same relative path it has in
> FN** — so the module's relative imports and absolute self-references resolve without
> touching the file.

It also warns that every `.svelte` under `fn/components/modules/` is **mountable by SQL**
via the `fnhost` static module.

## Correction to F002

F002 described the duplicated block trees as "a newer domain-driven layout mid-migration"
and warned against "deepening the fork". **That was wrong.** The two trees are not a fork
of one codebase — one is navigator-svelte's own, the other mirrors a *different
repository*:

| Tree | Owner | Write new code here? |
|---|---|---|
| `src/lib/components/agents/canvas/blocks/` | navigator-svelte | **YES — canonical** |
| `src/lib/fn/components/agents/canvas/blocks/` | mirror of FN's `$lib` | **NO** — must match FN's paths |

## Q4 RESOLVED

FEAT-431 Q4 ("which block tree is canonical?") is answered:
**`src/lib/components/agents/canvas/blocks/`**. The reverse adapter (D1) targets that
vocabulary. The `fn/` copy is not a divergent variant to reconcile — it is FN's source
reflected for porting, and changing it would desynchronize the mirror.

## Additional nuance found while verifying

There is **no `src/lib/dashboard/` outside `fn/`**. The whole dashboard *domain* layer —
the 22 widget classes, `iframe-widget.svelte.ts`, `settings-modal.svelte`,
`ShareWidgetModal.svelte` — exists only under `src/lib/fn/dashboard/`, i.e. it is
FN-ported. navigator-svelte's own dashboard UI is `src/lib/components/dashboards/`
(`DashboardActionsDropdown`, `GridGuides`, `DashboardEditToolbar`, …).

This distinction was **not** made in FEAT-430's handoff brief, which listed several `fn/`
paths as landing surfaces. Corrected there.
