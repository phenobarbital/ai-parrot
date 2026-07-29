---
type: Wiki Entity
title: Location
id: class:parrot_formdesigner.services.venue_service.Location
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A concrete work point inside a Site — a kiosk or any spot in the store.
---

# Location

Defined in [`parrot_formdesigner.services.venue_service`](../summaries/mod:parrot_formdesigner.services.venue_service.md).

```python
class Location(BaseModel)
```

A concrete work point inside a Site — a kiosk or any spot in the store.

Carries the geofence parameters used to validate a Visit/Assignment
check-in. A ``geofence_radius_m`` of ``None`` means geofence is disabled
for this location.

Attributes:
    location_id: Auto-incremented serial PK.
    site_id: FK to ``fieldsync.sites``.
    client_id: Client this location belongs to.
    org_id: Organization identifier (hard-isolation key).
    name: Human-readable location name.
    location_type: One of ``kiosk`` | ``endcap`` | ``gondola`` |
        ``backroom`` | ``other`` (free-form; default ``"kiosk"``).
    latitude: Geofence center latitude (optional).
    longitude: Geofence center longitude (optional).
    geofence_radius_m: Geofence radius in metres; ``None`` ⇒ disabled.
    is_active: Whether the location is currently active.
    tenant: Tenant slug (metadata, not stored in the table directly).
