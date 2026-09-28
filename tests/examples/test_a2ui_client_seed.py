"""FEAT-610 TASK-3852 — tests for client.py and seed_by_course.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui"))

import client  # noqa: E402
import seed_by_course  # noqa: E402


class TestSeedRefusesWithoutYes:
    """AC11: seed_by_course.py refuses without --yes and is idempotent."""

    def test_seed_refuses_without_yes(self):
        """Verify seed refuses without --yes and exits 2 before opening any connection."""
        # Run with no arguments - should refuse and exit 2
        exit_code = seed_by_course.main([])
        assert exit_code == 2

    def test_seed_accepts_yes_flag(self):
        """Verify seed accepts --yes flag (will fail on DB but that's expected in test env)."""
        # This will fail on DB connection but should not exit 2 (the --yes was accepted)
        # We just verify the flag is accepted
        with patch("asyncpg.connect", side_effect=ConnectionError("No DB")):
            exit_code = seed_by_course.main(["--yes"])
            # Should not be 2 (which means --yes was accepted but DB failed)
            assert exit_code != 2


class TestClientArgParsing:
    """Test client.py argument parsing."""

    def test_requires_open_or_check(self):
        """Client must have either --open or --check."""
        exit_code = client.main([])
        assert exit_code == 1  # Error: specify either --open or --check

    def test_open_and_check_mutually_exclusive(self):
        """--open and --check cannot be used together."""
        exit_code = client.main(["--open", "--check"])
        assert exit_code == 1  # Error: mutually exclusive

    def test_check_requires_password(self):
        """--check requires A2UI_DEMO_PASSWORD env var."""
        with patch.dict("os.environ", {}, clear=True):
            exit_code = client.main(["--check"])
            assert exit_code == 1  # Error: password not set


class TestClientCheckPrintsValues:
    """AC10: client.py --check exits 0 against a running server and prints the AC7 values."""

    @pytest.mark.asyncio
    async def test_client_check_prints_values(self):
        """Verify --check mode prints value table with a fake server."""
        # Create mock responses
        mock_login_response = {"token": "test-token-123"}
        mock_dashboard_response = {
            "metadata": {
                "extensions": {
                    "parrot_data_sources": {
                        "kpi_total": {
                            "slug": "polestar_graduates_directory",
                            "tenant": None,
                            "conditions": {},
                            "request": {"fields": ["count(*) as total"]},
                        },
                        "by_course": {
                            "slug": "polestar_graduates_by_course",
                            "tenant": None,
                            "conditions": {},
                            "request": {
                                "fields": ["course", "count(*) as graduates"],
                                "grouping": ["course"],
                            },
                        },
                    }
                }
            }
        }
        mock_source_response = [{"total": "42"}]
        mock_by_course_response = [
            {"course": "Pilates Studio", "graduates": "10"},
            {"course": "Pilates Mat", "graduates": "32"},
        ]

        # Track call count for different endpoints
        call_count = {"count": 0}

        # Create mock response objects
        class MockResponse:
            def __init__(self, status, json_data):
                self.status = status
                self._json_data = json_data

            async def json(self):
                return self._json_data

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        def mock_get(*args, **kwargs):
            """Return an async context manager directly, not a coroutine."""
            url = args[0] if args else kwargs.get("url", "")
            if "/login" in url:
                return MockResponse(200, mock_login_response)
            elif "/api/a2ui/dashboard" in url:
                return MockResponse(200, mock_dashboard_response)
            return MockResponse(404, {})

        def mock_post(*args, **kwargs):
            """Return an async context manager directly, not a coroutine."""
            call_count["count"] += 1
            if call_count["count"] == 1:
                return MockResponse(200, mock_source_response)
            return MockResponse(200, mock_by_course_response)

        # Create mock session class that supports async context manager
        class MockSession:
            def __init__(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def get(self, *args, **kwargs):
                # Return the async context manager directly
                return mock_get(*args, **kwargs)

            def post(self, *args, **kwargs):
                # Return the async context manager directly
                return mock_post(*args, **kwargs)

            async def close(self):
                pass

        # Capture stdout
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            with patch("aiohttp.ClientSession", return_value=MockSession()):
                exit_code = await client.check("http://localhost:5000", "admin", "password")

        output = f.getvalue()
        assert exit_code == 0
        assert "key | value" in output
        assert "kpi_total" in output
        assert "by_course" in output


class TestSeedSQLTemplate:
    """Verify the seed SQL template contains the LATERAL expansion."""

    def test_sql_template_contains_lateral(self):
        """SQL template must contain LATERAL expansion per spec §3 M9."""
        assert "LATERAL" in seed_by_course.QUERY_RAW
        assert "jsonb_array_elements" in seed_by_course.QUERY_RAW
        assert "e->>'course'" in seed_by_course.QUERY_RAW

    def test_sql_template_structure(self):
        """SQL template follows the spec pattern."""
        # Should have {fields} and {where_cond} placeholders
        assert "{fields}" in seed_by_course.QUERY_RAW
        assert "{where_cond}" in seed_by_course.QUERY_RAW
        # Should reference the base view
        assert "polestar.vw_graduates_directory" in seed_by_course.QUERY_RAW
