---
name: patch-plan
description: Produces a minimal patch plan and a safe edit checklist before editing.
use_when: You are about to make changes that might affect behavior.
---

Instructions:
1) Propose smallest patch (files + functions).
2) Identify risks (API contract, route params, SSR, auth).
3) Define verification steps (commands + manual checks).
4) Only then proceed to edit.

## Python Patching Guidelines
- **Type Integrity**: Ensure changes match existing type hints.
- **Dependencies**: Watch for circular imports when moving code.
- **Async Safety**: Verify async/sync compatibility; do not block the event loop.
- **Data Models**: If modifying Pydantic/DataModel schemas, check for backward compatibility in serialization/deserialization.

## SvelteKit Patching Guidelines
- **Reactivity**:
  - **Svelte 5**: Correctly use runes (`$state`, `$derived`, `$effect`).
  - **Stores**: Ensure proper subscription cleanup if not using auto-subscription (`$`).
- **Environment**:
  - **Server vs Client**: Use `$app/environment` (`browser`) to guard browser-specific code (e.g., `window`, `document`).
  - **Load Functions**: Distinguish between `+page.server.ts` (secrets allowed) and `+page.ts` (public).
- **State Preservation**: Ensure navigation or form actions do not accidentally reset form state or UI focus unless intended.
