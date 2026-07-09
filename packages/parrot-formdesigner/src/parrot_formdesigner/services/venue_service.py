"""VenueService — CRUD sobre ``fieldsync.sites`` / ``fieldsync.locations``.

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
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from ._db_utils import is_unique_violation

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DuplicateVenueError(Exception):
    """Raised when a UNIQUE constraint on a site/location is violated.

    Attributes:
        kind: ``"site"`` or ``"location"``.
        name: The duplicate name.
    """

    def __init__(self, kind: str, name: str) -> None:
        self.kind = kind
        self.name = name
        super().__init__(f"{kind} {name!r} already exists in its parent scope")


class SiteNotFoundError(Exception):
    """Raised when a site lookup returns no row.

    Attributes:
        site_id: The missing site identifier.
    """

    def __init__(self, site_id: int) -> None:
        self.site_id = site_id
        super().__init__(f"Site {site_id} not found")


class LocationNotFoundError(Exception):
    """Raised when a location lookup returns no row.

    Attributes:
        location_id: The missing location identifier.
    """

    def __init__(self, location_id: int) -> None:
        self.location_id = location_id
        super().__init__(f"Location {location_id} not found")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Site(BaseModel):
    """An intermediate work-area grouping inside a Store.

    A Store may contain multiple Sites; a Site groups one or more Locations.
    Owned by FieldSync (``fieldsync.sites``); tenant-isolated by ``org_id``.

    Attributes:
        site_id: Auto-incremented serial PK.
        store_id: Identifier of the parent store (networkninja geography).
            Kept as ``str`` for parity with ``OrgNode.node_id``.
        client_id: Client this site belongs to.
        org_id: Organization identifier (hard-isolation key).
        name: Human-readable site name.
        is_active: Whether the site is currently active.
        tenant: Tenant slug (metadata, not stored in the table directly).
    """

    model_config = ConfigDict(extra="forbid")

    site_id: int
    store_id: str
    client_id: int
    org_id: int
    name: str
    is_active: bool = True
    tenant: str | None = None


class Location(BaseModel):
    """A concrete work point inside a Site — a kiosk or any spot in the store.

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
    """

    model_config = ConfigDict(extra="forbid")

    location_id: int
    site_id: int
    client_id: int
    org_id: int
    name: str
    location_type: str = "kiosk"
    latitude: float | None = None
    longitude: float | None = None
    geofence_radius_m: int | None = None
    is_active: bool = True
    tenant: str | None = None


# ---------------------------------------------------------------------------
# SQL constants (table names FIXED in constants — not from user input)
# ---------------------------------------------------------------------------

_INSERT_SITE_SQL = """
INSERT INTO fieldsync.sites
    (store_id, client_id, org_id, name)
VALUES ($1, $2, $3, $4)
RETURNING site_id, store_id, client_id, org_id, name, is_active
"""

_SELECT_SITE_SQL = """
SELECT site_id, store_id, client_id, org_id, name, is_active
FROM fieldsync.sites
WHERE site_id = $1 AND org_id = $2
"""

_SELECT_SITES_BY_STORE_SQL = """
SELECT site_id, store_id, client_id, org_id, name, is_active
FROM fieldsync.sites
WHERE store_id = $1 AND org_id = $2
ORDER BY site_id
"""

_INSERT_LOCATION_SQL = """
INSERT INTO fieldsync.locations
    (site_id, client_id, org_id, name, location_type,
     latitude, longitude, geofence_radius_m)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
RETURNING location_id, site_id, client_id, org_id, name, location_type,
          latitude, longitude, geofence_radius_m, is_active
"""

_SELECT_LOCATION_SQL = """
SELECT location_id, site_id, client_id, org_id, name, location_type,
       latitude, longitude, geofence_radius_m, is_active
FROM fieldsync.locations
WHERE location_id = $1 AND org_id = $2
"""

_SELECT_LOCATIONS_BY_SITE_SQL = """
SELECT location_id, site_id, client_id, org_id, name, location_type,
       latitude, longitude, geofence_radius_m, is_active
FROM fieldsync.locations
WHERE site_id = $1 AND org_id = $2
ORDER BY location_id
"""

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class VenueService:
    """CRUD service for ``fieldsync.sites`` and ``fieldsync.locations``.

    Args:
        pool: asyncpg pool (or fake pool for tests).

    Example::

        svc = VenueService(pool)
        site = await svc.create_site(
            store_id="store-501", client_id=42, org_id=7,
            name="Vending Zone", tenant="acme",
        )
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Site CRUD
    # ------------------------------------------------------------------

    async def create_site(
        self,
        *,
        store_id: str,
        client_id: int,
        org_id: int,
        name: str,
        tenant: str | None = None,
    ) -> Site:
        """Create a new site under a store.

        Args:
            store_id: Parent store identifier (networkninja geography).
            client_id: Client this site belongs to.
            org_id: Organization identifier (hard-isolation key).
            name: Site name (UNIQUE per ``(store_id, client_id)``).
            tenant: Tenant slug (stored in the returned model only).

        Returns:
            The newly created ``Site`` with its DB-assigned ``site_id``.

        Raises:
            DuplicateVenueError: If ``(store_id, client_id, name)`` exists.
        """
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    _INSERT_SITE_SQL, store_id, client_id, org_id, name
                )
            except Exception as exc:
                if is_unique_violation(exc):
                    raise DuplicateVenueError("site", name) from exc
                raise

        return self._row_to_site(row, tenant=tenant)

    async def get_site(
        self, site_id: int, *, org_id: int, tenant: str | None = None
    ) -> Site:
        """Retrieve a site by PK, scoped to ``org_id`` (hard isolation).

        Args:
            site_id: Primary key of the site.
            org_id: Organization the caller is scoped to.
            tenant: Optional tenant slug (stored in returned model).

        Returns:
            ``Site`` populated from the DB row.

        Raises:
            SiteNotFoundError: If no site with ``site_id`` exists in ``org_id``.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_SELECT_SITE_SQL, site_id, org_id)
        if row is None:
            raise SiteNotFoundError(site_id)
        return self._row_to_site(row, tenant=tenant)

    async def list_sites(
        self, *, store_id: str, org_id: int, tenant: str | None = None
    ) -> list[Site]:
        """List sites under a store within ``org_id`` (hard isolation).

        Args:
            store_id: Parent store identifier.
            org_id: Organization the caller is scoped to (REQUIRED — every
                query is filtered by it; there is no cross-tenant path).
            tenant: Tenant slug stored in returned models.

        Returns:
            List of ``Site`` instances (empty if none match).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_SITES_BY_STORE_SQL, store_id, org_id)
        return [self._row_to_site(row, tenant=tenant) for row in rows]

    # ------------------------------------------------------------------
    # Location CRUD
    # ------------------------------------------------------------------

    async def create_location(
        self,
        *,
        site_id: int,
        client_id: int,
        org_id: int,
        name: str,
        location_type: str = "kiosk",
        latitude: float | None = None,
        longitude: float | None = None,
        geofence_radius_m: int | None = None,
        tenant: str | None = None,
    ) -> Location:
        """Create a new location under a site.

        Args:
            site_id: FK to ``fieldsync.sites``.
            client_id: Client this location belongs to.
            org_id: Organization identifier (hard-isolation key).
            name: Location name (UNIQUE per ``site_id``).
            location_type: Kind of location (default ``"kiosk"``).
            latitude: Geofence center latitude (optional).
            longitude: Geofence center longitude (optional).
            geofence_radius_m: Geofence radius in metres; ``None`` ⇒ disabled.
            tenant: Tenant slug (stored in the returned model only).

        Returns:
            The newly created ``Location`` with its DB-assigned ``location_id``.

        Raises:
            DuplicateVenueError: If ``(site_id, name)`` already exists.
        """
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    _INSERT_LOCATION_SQL,
                    site_id,
                    client_id,
                    org_id,
                    name,
                    location_type,
                    latitude,
                    longitude,
                    geofence_radius_m,
                )
            except Exception as exc:
                if is_unique_violation(exc):
                    raise DuplicateVenueError("location", name) from exc
                raise

        return self._row_to_location(row, tenant=tenant)

    async def get_location(
        self, location_id: int, *, org_id: int, tenant: str | None = None
    ) -> Location:
        """Retrieve a location by PK, scoped to ``org_id`` (hard isolation).

        Args:
            location_id: Primary key of the location.
            org_id: Organization the caller is scoped to.
            tenant: Optional tenant slug (stored in returned model).

        Returns:
            ``Location`` populated from the DB row (includes geofence params).

        Raises:
            LocationNotFoundError: If no location with ``location_id`` exists
                within ``org_id``.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_SELECT_LOCATION_SQL, location_id, org_id)
        if row is None:
            raise LocationNotFoundError(location_id)
        return self._row_to_location(row, tenant=tenant)

    async def list_locations(
        self, *, site_id: int, org_id: int, tenant: str | None = None
    ) -> list[Location]:
        """List locations under a site within ``org_id`` (hard isolation).

        Args:
            site_id: Parent site identifier.
            org_id: Organization the caller is scoped to (REQUIRED).
            tenant: Tenant slug stored in returned models.

        Returns:
            List of ``Location`` instances (empty if none match).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_LOCATIONS_BY_SITE_SQL, site_id, org_id)
        return [self._row_to_location(row, tenant=tenant) for row in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_site(row: Any, *, tenant: str | None) -> Site:
        """Build a ``Site`` model from a DB row."""
        return Site(
            site_id=row["site_id"],
            store_id=str(row["store_id"]),
            client_id=row["client_id"],
            org_id=row["org_id"],
            name=row["name"],
            is_active=row["is_active"],
            tenant=tenant,
        )

    @staticmethod
    def _row_to_location(row: Any, *, tenant: str | None) -> Location:
        """Build a ``Location`` model from a DB row."""
        return Location(
            location_id=row["location_id"],
            site_id=row["site_id"],
            client_id=row["client_id"],
            org_id=row["org_id"],
            name=row["name"],
            location_type=row["location_type"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            geofence_radius_m=row["geofence_radius_m"],
            is_active=row["is_active"],
            tenant=tenant,
        )
