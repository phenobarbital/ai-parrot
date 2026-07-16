---
type: Wiki Entity
title: FormVersionService
id: class:parrot_formdesigner.services.form_version.FormVersionService
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Immutable semver publishing service for ``FormSchema`` objects.
---

# FormVersionService

Defined in [`parrot_formdesigner.services.form_version`](../summaries/mod:parrot_formdesigner.services.form_version.md).

```python
class FormVersionService
```

Immutable semver publishing service for ``FormSchema`` objects.

Each call to :meth:`publish` creates a frozen snapshot identified by a
bumped semver tag.  The snapshot is stored via ``storage.save()`` when
available; an in-memory fallback (dict) is used otherwise (suitable for
tests and development).

Deletion is guarded by the optional ``has_responses`` async hook: if
supplied, the service calls it before any delete to confirm no response
data exists.  If the hook returns ``True``, deletion raises ``ValueError``
and the form is only deactivated (not deleted).

Example::

    svc = FormVersionService(registry, storage)
    tag = await svc.publish("my-form", tenant="navigator")  # → "1.1"
    snap = await svc.get_published("my-form", version="1.1", tenant="navigator")

Args:
    registry: ``FormRegistry`` used to look up the live form state and
        register snapshots when a ``storage`` backend is not available.
    storage: ``FormStorage`` used to persist snapshots. When ``None``,
        the service stores snapshots in an in-memory dict.
    has_responses: Optional async callback ``(form_id, tenant) -> bool``
        that returns ``True`` when the form/version has associated
        responses. When ``True`` is returned, deletion is blocked.

## Methods

- `async def publish(self, form_id: str, *, tenant: str, bump: str='minor') -> str` — Publish the current form as an immutable semver snapshot.
- `async def get_published(self, form_id: str, *, version: str, tenant: str) -> FormSchema | None` — Retrieve an immutable published snapshot.
- `async def list_versions(self, form_id: str, *, tenant: str) -> list[VersionMeta]` — List all published version metadata for a form.
- `async def can_delete(self, form_id: str, *, tenant: str) -> bool` — Return ``True`` if deletion is safe (no responses associated).
- `async def safe_delete(self, form_id: str, *, tenant: str) -> None` — Delete a form only if it has no responses.
- `async def backfill_published(self, *, tenant: str, dry_run: bool=False) -> int` — Backfill pre-existing forms as published v1.0 snapshots.
