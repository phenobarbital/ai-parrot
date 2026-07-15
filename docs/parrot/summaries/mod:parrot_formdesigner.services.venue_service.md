---
type: Wiki Summary
title: parrot_formdesigner.services.venue_service
id: mod:parrot_formdesigner.services.venue_service
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: VenueService — CRUD sobre ``fieldsync.sites`` / ``fieldsync.locations``.
relates_to:
- concept: class:parrot_formdesigner.services.venue_service.DuplicateVenueError
  rel: defines
- concept: class:parrot_formdesigner.services.venue_service.Location
  rel: defines
- concept: class:parrot_formdesigner.services.venue_service.LocationNotFoundError
  rel: defines
- concept: class:parrot_formdesigner.services.venue_service.Site
  rel: defines
- concept: class:parrot_formdesigner.services.venue_service.SiteNotFoundError
  rel: defines
- concept: class:parrot_formdesigner.services.venue_service.VenueService
  rel: defines
---

# `parrot_formdesigner.services.venue_service`

VenueService — CRUD sobre ``fieldsync.sites`` / ``fieldsync.locations``.

Implementa la sub-estructura de tienda de FieldSync (FEAT-330):
``Store → Site → Location``. ``Store`` es geografía read-only
(``networkninja.*``, propiedad de FEAT-302); ``Site`` y ``Location`` son
entidades **propiedad de FieldSync**.

- Una ``Site`` agrupa uno o más ``Location`` dentro de un ``Store`` (p. ej.
  una zona de vending).
- Una ``Location`` es un **kiosk** o cualquier punto/spot dentro de la tienda.
  Lleva los parámetros de **geofence** (``latitude`` / ``longitude`` /
  ``geofence_radius_m``) — el system of record del geofence per-location
  (movido fuera de ``Event.meta``; ver FEAT-303 §8 y FEAT-318 D5.7). Un
  ``geofence_radius_m = NULL`` significa geofence deshabilitado en ese punto.

Diseño (idéntico a ``ProjectService`` — FEAT-302):
- Pool inyectado en el constructor → testable sin DB real.
- SQL 100% parametrizado ($1, $2…); nombres de tabla fijados en constantes.
- **Hard tenant isolation**: todo query filtra ``org_id`` explícitamente.
- Pydantic v2 para modelos de datos.

Uso::

    svc = VenueService(pool)
    site = await svc.create_site(
        store_id="store-501", client_id=42, org_id=7,
        name="Pokémon Vending Zone", tenant="acme",
    )
    loc = await svc.create_location(
        site_id=site.site_id, client_id=42, org_id=7, name="Kiosk A-12",
        location_type="kiosk", latitude=34.0522, longitude=-118.2437,
        geofence_radius_m=50, tenant="acme",
    )

## Classes

- **`DuplicateVenueError(Exception)`** — Raised when a UNIQUE constraint on a site/location is violated.
- **`SiteNotFoundError(Exception)`** — Raised when a site lookup returns no row.
- **`LocationNotFoundError(Exception)`** — Raised when a location lookup returns no row.
- **`Site(BaseModel)`** — An intermediate work-area grouping inside a Store.
- **`Location(BaseModel)`** — A concrete work point inside a Site — a kiosk or any spot in the store.
- **`VenueService`** — CRUD service for ``fieldsync.sites`` and ``fieldsync.locations``.
