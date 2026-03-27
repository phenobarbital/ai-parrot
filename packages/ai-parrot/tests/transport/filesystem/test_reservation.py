"""Tests for ReservationManager — cooperative resource reservations."""

import asyncio

import pytest

from parrot.transport.filesystem.reservation import ReservationManager


@pytest.fixture
def res_a(tmp_path):
    return ReservationManager(tmp_path / "reservations", "agent-a")


@pytest.fixture
def res_b(tmp_path):
    return ReservationManager(tmp_path / "reservations", "agent-b")


class TestReservationManager:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self, res_a):
        """Basic acquire and release cycle."""
        ok = await res_a.acquire(["file_a.csv"], reason="processing")
        assert ok is True
        await res_a.release(["file_a.csv"])
        active = await res_a.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_all_or_nothing(self, res_a, res_b):
        """Partial conflict fails entire acquisition."""
        ok1 = await res_a.acquire(["file_a.csv", "file_b.csv"])
        assert ok1 is True
        ok2 = await res_b.acquire(["file_b.csv", "file_c.csv"])
        assert ok2 is False
        # file_c.csv must NOT be reserved by agent-b
        active = await res_b.list_active()
        resources = {r["resource"] for r in active}
        assert "file_c.csv" not in resources

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, res_a, res_b):
        """Expired reservations allow re-acquisition."""
        ok1 = await res_a.acquire(["file.csv"], timeout=0.001)
        assert ok1 is True
        await asyncio.sleep(0.1)
        # Expired, so agent-b can acquire
        ok2 = await res_b.acquire(["file.csv"])
        assert ok2 is True

    @pytest.mark.asyncio
    async def test_release_all(self, res_a):
        """release_all removes all reservations for this agent."""
        await res_a.acquire(["a.csv", "b.csv", "c.csv"])
        await res_a.release_all()
        active = await res_a.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_same_agent_re_acquire(self, res_a):
        """Same agent can re-acquire a resource it already holds."""
        ok1 = await res_a.acquire(["file.csv"])
        assert ok1 is True
        ok2 = await res_a.acquire(["file.csv"])
        assert ok2 is True

    @pytest.mark.asyncio
    async def test_list_active_excludes_expired(self, res_a):
        """list_active returns only non-expired reservations."""
        await res_a.acquire(["expired.csv"], timeout=0.001)
        await res_a.acquire(["active.csv"], timeout=300.0)
        await asyncio.sleep(0.1)
        active = await res_a.list_active()
        resources = {r["resource"] for r in active}
        assert "expired.csv" not in resources
        assert "active.csv" in resources

    @pytest.mark.asyncio
    async def test_release_only_own(self, res_a, res_b):
        """Release only removes reservations owned by the calling agent."""
        await res_a.acquire(["shared.csv"])
        # agent-b tries to release agent-a's reservation — should not work
        await res_b.release(["shared.csv"])
        active = await res_a.list_active()
        resources = {r["resource"] for r in active}
        assert "shared.csv" in resources

    @pytest.mark.asyncio
    async def test_reservation_data_format(self, res_a):
        """Reservation data has expected fields."""
        await res_a.acquire(["data.csv"], reason="testing")
        active = await res_a.list_active()
        assert len(active) == 1
        r = active[0]
        assert r["resource"] == "data.csv"
        assert r["agent_id"] == "agent-a"
        assert r["reason"] == "testing"
        assert "acquired_at" in r
        assert "expires_at" in r

    @pytest.mark.asyncio
    async def test_list_active_empty(self, res_a):
        """list_active on empty dir returns empty list."""
        active = await res_a.list_active()
        assert active == []
