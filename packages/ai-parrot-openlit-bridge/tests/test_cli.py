"""Unit tests for the parrot-openlit-check CLI entry point.

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 9.
Task: TASK-2477.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from ai_parrot_openlit_bridge.cli import main
from ai_parrot_openlit_bridge.probe import EndpointStatus


class TestCli:
    def test_exit_zero_on_reachable(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["parrot-openlit-check", "http://x:4318"])
        with patch(
            "ai_parrot_openlit_bridge.cli.validate_endpoint",
            return_value=EndpointStatus(reachable=True, status_code=200, collector_info="otel-collector"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "✅" in out
        assert "otel-collector" in out

    def test_exit_one_on_unreachable(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["parrot-openlit-check", "http://x:4318"])
        with patch(
            "ai_parrot_openlit_bridge.cli.validate_endpoint",
            return_value=EndpointStatus(reachable=False, error="Connection refused"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "❌" in out
        assert "Connection refused" in out

    def test_timeout_arg_parsed(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "argv", ["parrot-openlit-check", "http://x:4318", "--timeout", "1.5"])
        called = {}

        async def _fake_validate(url, *, timeout=5.0, headers=None):
            called["url"] = url
            called["timeout"] = timeout
            return EndpointStatus(reachable=True, status_code=200)

        with patch("ai_parrot_openlit_bridge.cli.validate_endpoint", _fake_validate), pytest.raises(SystemExit):
            main()
        assert called["timeout"] == 1.5
        assert called["url"] == "http://x:4318"
