---
id: F007
query_id: Q008
type: read
intent: Find the create/edit/publish hook points + app access for exclude sync
executed_at: 2026-06-16T00:00:00Z
duration_ms: 0
parent_id: F006
depth: 1
---

# F007 — Lifecycle hook points where `is_public` would toggle the exclude list

## Summary

The handlers that create/mutate a form all funnel through
`self.registry.register(form, persist=..., overwrite=True, tenant=...)`. Each
handler receives `request`, so it can reach `request.app["auth"]` (F003) to add or
remove exclude paths. There is currently **no** exclude/anonymous wiring in
formdesigner (grep across the package → none), so this is a clean greenfield
integration. The toggle must compute old-vs-new `is_public` to know whether to
add (False→True) or remove (True→False) the form's paths.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 741, 915, 963, 1437
  symbol: `create_form / update_form / patch_form / publish_form`
  excerpt: |
    async def create_form(self, request): ...      # 741
    async def update_form(self, request): ...       # 915
    async def patch_form(self, request): ...        # 963
    async def publish_form(self, request): ...      # 1437

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 927-959
  symbol: `update_form persistence`
  excerpt: |
    existing = await self.registry.get(form_id, tenant=tenant)
    ...
    persist = self.registry.has_storage
    await self.registry.register(form, persist=persist, overwrite=True, tenant=tenant)

## Notes

Centralizing the add/remove in `FormRegistry.register` (or a small
`PublicFormGateway` service) avoids duplicating the toggle across 4 handlers.
`registry.get` already returns the prior form so old-vs-new `is_public` diffing is
cheap.
