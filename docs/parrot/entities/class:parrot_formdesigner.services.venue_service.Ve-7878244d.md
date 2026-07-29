---
type: Wiki Entity
title: VenueService
id: class:parrot_formdesigner.services.venue_service.VenueService
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CRUD service for ``fieldsync.sites`` and ``fieldsync.locations``.
---

# VenueService

Defined in [`parrot_formdesigner.services.venue_service`](../summaries/mod:parrot_formdesigner.services.venue_service.md).

```python
class VenueService
```

CRUD service for ``fieldsync.sites`` and ``fieldsync.locations``.

Args:
    pool: asyncpg pool (or fake pool for tests).

Example::

    svc = VenueService(pool)
    site = await svc.create_site(
        store_id="store-501", client_id=42, org_id=7,
        name="Vending Zone", tenant="acme",
    )

## Methods

- `async def create_site(self, *, store_id: str, client_id: int, org_id: int, name: str, tenant: str | None=None) -> Site` — Create a new site under a store.
- `async def get_site(self, site_id: int, *, org_id: int, tenant: str | None=None) -> Site` — Retrieve a site by PK, scoped to ``org_id`` (hard isolation).
- `async def list_sites(self, *, store_id: str, org_id: int, tenant: str | None=None) -> list[Site]` — List sites under a store within ``org_id`` (hard isolation).
- `async def create_location(self, *, site_id: int, client_id: int, org_id: int, name: str, location_type: str='kiosk', latitude: float | None=None, longitude: float | None=None, geofence_radius_m: int | None=None, tenant: str | None=None) -> Location` — Create a new location under a site.
- `async def get_location(self, location_id: int, *, org_id: int, tenant: str | None=None) -> Location` — Retrieve a location by PK, scoped to ``org_id`` (hard isolation).
- `async def list_locations(self, *, site_id: int, org_id: int, tenant: str | None=None) -> list[Location]` — List locations under a site within ``org_id`` (hard isolation).
