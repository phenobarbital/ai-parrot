"""Unit tests for FEAT-330 — VenueService (fake pool, no real DB).

Covers:
- create_site() happy path + DuplicateVenueError on unique violation.
- get_site() happy path + SiteNotFoundError.
- list_sites() hard-isolation filter (org_id passed to every query).
- create_location() persists geofence params (lat/long/radius).
- get_location() happy path + LocationNotFoundError.
- list_locations() round-trip.
- SQL constants target fieldsync.* and never write networkninja.*.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.services.venue_service import (
    DuplicateVenueError,
    Location,
    LocationNotFoundError,
    Site,
    SiteNotFoundError,
    VenueService,
    _INSERT_LOCATION_SQL,
    _INSERT_SITE_SQL,
    _SELECT_LOCATION_SQL,
    _SELECT_SITE_SQL,
)


# ---------------------------------------------------------------------------
# Fake pool / connection helpers
# ---------------------------------------------------------------------------


def _row(data: dict) -> MagicMock:
    """Build a MagicMock that behaves like an asyncpg Record."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: data[k]
    return row


def _make_conn(
    fetchrow_result: Any = None,
    fetch_result: list | None = None,
    fetchrow_side_effect: Any = None,
) -> MagicMock:
    conn = MagicMock()
    if fetchrow_side_effect is not None:
        conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    else:
        conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.fetch = AsyncMock(return_value=fetch_result or [])
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


def _site_row(
    site_id: int = 1,
    store_id: str = "store-501",
    client_id: int = 42,
    org_id: int = 7,
    name: str = "Vending Zone",
    is_active: bool = True,
) -> MagicMock:
    return _row(
        {
            "site_id": site_id,
            "store_id": store_id,
            "client_id": client_id,
            "org_id": org_id,
            "name": name,
            "is_active": is_active,
        }
    )


def _location_row(
    location_id: int = 1,
    site_id: int = 1,
    client_id: int = 42,
    org_id: int = 7,
    name: str = "Kiosk A-12",
    location_type: str = "kiosk",
    latitude: float | None = 34.0522,
    longitude: float | None = -118.2437,
    geofence_radius_m: int | None = 50,
    is_active: bool = True,
) -> MagicMock:
    return _row(
        {
            "location_id": location_id,
            "site_id": site_id,
            "client_id": client_id,
            "org_id": org_id,
            "name": name,
            "location_type": location_type,
            "latitude": latitude,
            "longitude": longitude,
            "geofence_radius_m": geofence_radius_m,
            "is_active": is_active,
        }
    )


# ---------------------------------------------------------------------------
# SQL safety
# ---------------------------------------------------------------------------


class TestSQLSafety:
    def test_site_insert_targets_fieldsync(self) -> None:
        assert "fieldsync.sites" in _INSERT_SITE_SQL
        assert "networkninja" not in _INSERT_SITE_SQL

    def test_location_insert_targets_fieldsync(self) -> None:
        assert "fieldsync.locations" in _INSERT_LOCATION_SQL
        assert "networkninja" not in _INSERT_LOCATION_SQL

    def test_selects_scope_by_org_id(self) -> None:
        # Hard isolation: single-row selects always filter org_id ($2).
        assert "org_id = $2" in _SELECT_SITE_SQL
        assert "org_id = $2" in _SELECT_LOCATION_SQL


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_site_defaults(self) -> None:
        s = Site(site_id=1, store_id="s1", client_id=1, org_id=1, name="z")
        assert s.is_active is True
        assert s.store_id == "s1"

    def test_location_geofence_optional(self) -> None:
        loc = Location(location_id=1, site_id=1, client_id=1, org_id=1, name="k")
        assert loc.location_type == "kiosk"
        assert loc.latitude is None
        assert loc.geofence_radius_m is None  # None ⇒ geofence disabled


# ---------------------------------------------------------------------------
# create_site
# ---------------------------------------------------------------------------


class TestCreateSite:
    @pytest.mark.asyncio
    async def test_create_returns_site(self) -> None:
        conn = _make_conn(fetchrow_result=_site_row())
        svc = VenueService(_make_pool(conn))
        site = await svc.create_site(
            store_id="store-501", client_id=42, org_id=7,
            name="Vending Zone", tenant="acme",
        )
        assert isinstance(site, Site)
        assert site.site_id == 1
        assert site.store_id == "store-501"
        assert site.tenant == "acme"

    @pytest.mark.asyncio
    async def test_duplicate_site_raises(self) -> None:
        conn = _make_conn(
            fetchrow_side_effect=Exception("duplicate key value UniqueViolation")
        )
        svc = VenueService(_make_pool(conn))
        with pytest.raises(DuplicateVenueError):
            await svc.create_site(
                store_id="s1", client_id=1, org_id=1, name="dup", tenant="t"
            )


# ---------------------------------------------------------------------------
# get_site / list_sites
# ---------------------------------------------------------------------------


class TestReadSites:
    @pytest.mark.asyncio
    async def test_get_site_found(self) -> None:
        conn = _make_conn(fetchrow_result=_site_row(site_id=9))
        svc = VenueService(_make_pool(conn))
        site = await svc.get_site(9, org_id=7)
        assert site.site_id == 9

    @pytest.mark.asyncio
    async def test_get_site_not_found(self) -> None:
        conn = _make_conn(fetchrow_result=None)
        svc = VenueService(_make_pool(conn))
        with pytest.raises(SiteNotFoundError):
            await svc.get_site(999, org_id=7)

    @pytest.mark.asyncio
    async def test_list_sites_filters_by_org(self) -> None:
        conn = _make_conn(fetch_result=[_site_row(), _site_row(site_id=2)])
        svc = VenueService(_make_pool(conn))
        sites = await svc.list_sites(store_id="store-501", org_id=7)
        assert len(sites) == 2
        # org_id + store_id passed positionally to the isolation query
        args = conn.fetch.call_args[0]
        assert args[1] == "store-501"
        assert args[2] == 7


# ---------------------------------------------------------------------------
# Locations (incl. geofence persistence)
# ---------------------------------------------------------------------------


class TestLocations:
    @pytest.mark.asyncio
    async def test_create_location_persists_geofence(self) -> None:
        conn = _make_conn(fetchrow_result=_location_row())
        svc = VenueService(_make_pool(conn))
        loc = await svc.create_location(
            site_id=1, client_id=42, org_id=7, name="Kiosk A-12",
            latitude=34.0522, longitude=-118.2437, geofence_radius_m=50,
            tenant="acme",
        )
        assert isinstance(loc, Location)
        assert loc.geofence_radius_m == 50
        assert loc.latitude == 34.0522
        assert loc.location_type == "kiosk"

    @pytest.mark.asyncio
    async def test_create_location_geofence_none_disabled(self) -> None:
        conn = _make_conn(
            fetchrow_result=_location_row(latitude=None, longitude=None,
                                          geofence_radius_m=None)
        )
        svc = VenueService(_make_pool(conn))
        loc = await svc.create_location(
            site_id=1, client_id=1, org_id=1, name="no-geo",
        )
        assert loc.geofence_radius_m is None

    @pytest.mark.asyncio
    async def test_duplicate_location_raises(self) -> None:
        conn = _make_conn(
            fetchrow_side_effect=Exception("23505 unique violation")
        )
        svc = VenueService(_make_pool(conn))
        with pytest.raises(DuplicateVenueError):
            await svc.create_location(site_id=1, client_id=1, org_id=1, name="d")

    @pytest.mark.asyncio
    async def test_get_location_found(self) -> None:
        conn = _make_conn(fetchrow_result=_location_row(location_id=5))
        svc = VenueService(_make_pool(conn))
        loc = await svc.get_location(5, org_id=7)
        assert loc.location_id == 5

    @pytest.mark.asyncio
    async def test_get_location_not_found(self) -> None:
        conn = _make_conn(fetchrow_result=None)
        svc = VenueService(_make_pool(conn))
        with pytest.raises(LocationNotFoundError):
            await svc.get_location(404, org_id=7)

    @pytest.mark.asyncio
    async def test_list_locations_round_trip(self) -> None:
        conn = _make_conn(fetch_result=[_location_row(), _location_row(location_id=2)])
        svc = VenueService(_make_pool(conn))
        locs = await svc.list_locations(site_id=1, org_id=7)
        assert [loc.location_id for loc in locs] == [1, 2]
