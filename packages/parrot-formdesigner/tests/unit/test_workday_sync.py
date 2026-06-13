"""Unit tests for TASK-017 — WorkdayIdentitySyncAdapter stub.

Verifies:
- sync_user returns accepted dict with stub=True (no HTTP calls).
- Both action=provision and action=deprovision work.
- Response keys are stable (upgrade contract).
- No aiohttp.ClientSession is opened (zero network I/O).
- Adapter can be instantiated with or without base_url/api_key.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from parrot_formdesigner.services.workday_sync import WorkdayIdentitySyncAdapter


class TestWorkdayIdentitySyncAdapterConstruction:
    def test_no_args_construction(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        assert adapter._base_url is None
        assert adapter._api_key is None

    def test_with_base_url(self) -> None:
        adapter = WorkdayIdentitySyncAdapter("https://workday.example.com")
        assert adapter._base_url == "https://workday.example.com"

    def test_with_api_key(self) -> None:
        adapter = WorkdayIdentitySyncAdapter(api_key="secret")
        assert adapter._api_key == "secret"


class TestWorkdayIdentitySyncAdapterSyncUser:
    @pytest.mark.asyncio
    async def test_provision_returns_accepted(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        result = await adapter.sync_user("user-1", action="provision", org_id=7)
        assert result["status"] == "accepted"
        assert result["stub"] is True
        assert result["action"] == "provision"
        assert result["user_id"] == "user-1"
        assert result["org_id"] == 7

    @pytest.mark.asyncio
    async def test_deprovision_returns_accepted(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        result = await adapter.sync_user("user-2", action="deprovision", org_id=3)
        assert result["status"] == "accepted"
        assert result["stub"] is True
        assert result["action"] == "deprovision"
        assert result["user_id"] == "user-2"
        assert result["org_id"] == 3

    @pytest.mark.asyncio
    async def test_response_has_all_required_keys(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        result = await adapter.sync_user("u", action="provision", org_id=1)
        for key in ("status", "stub", "action", "user_id", "org_id"):
            assert key in result, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_no_http_call_made(self) -> None:
        """Verify no aiohttp.ClientSession is opened (no network I/O)."""
        with patch("aiohttp.ClientSession") as mock_session:
            adapter = WorkdayIdentitySyncAdapter("https://example.com")
            result = await adapter.sync_user("u", action="provision", org_id=1)
            mock_session.assert_not_called()
        assert result["stub"] is True

    @pytest.mark.asyncio
    async def test_no_aiohttp_import_needed(self) -> None:
        """Stub works even if aiohttp is not importable."""
        import sys
        aiohttp_backup = sys.modules.get("aiohttp")
        try:
            sys.modules["aiohttp"] = None  # type: ignore[assignment]
            # Re-import should not be needed — stub has no HTTP dependency
            adapter = WorkdayIdentitySyncAdapter()
            result = await adapter.sync_user("u", action="deprovision", org_id=5)
            assert result["stub"] is True
        finally:
            if aiohttp_backup is not None:
                sys.modules["aiohttp"] = aiohttp_backup
            elif "aiohttp" in sys.modules:
                del sys.modules["aiohttp"]

    @pytest.mark.asyncio
    async def test_stub_logs_info(self) -> None:
        """Verify that sync_user emits an INFO log."""
        adapter = WorkdayIdentitySyncAdapter()
        with patch.object(adapter.logger, "info") as mock_log:
            await adapter.sync_user("u1", action="provision", org_id=1)
            mock_log.assert_called_once()
            call_args = mock_log.call_args[0]
            assert "STUB" in call_args[0] or "stub" in str(call_args).lower()
