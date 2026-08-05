"""TASK-2137: SOAP endpoint host rewrite on WorkdayService (bind_service override)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from parrot_tools.interfaces.workday.service import WorkdayService


def _service_instance(workday_url: str | None) -> WorkdayService:
    """Build a bare WorkdayService instance without running __init__."""
    svc = WorkdayService.__new__(WorkdayService)
    svc._logger = logging.getLogger("test.workday")
    svc.workday_url = workday_url
    return svc


def _zeep_service(address: str | None, has_binding_options: bool = True) -> MagicMock:
    service = MagicMock()
    if has_binding_options:
        service._binding_options = {"address": address} if address else {}
    else:
        del service._binding_options
        service.configure_mock(_binding_options=None)
    return service


class TestEndpointRewrite:
    def test_rewrites_host_for_sandbox(self):
        """Bound endpoint host swapped to the configured host; path preserved."""
        svc = _service_instance("https://impl-services1.wd501.myworkday.com")
        zeep_service = _zeep_service(
            "https://services1.wd501.myworkday.com/ccx/service/nav/Human_Resources/v44.2"
        )
        svc._point_endpoint_at_configured_host(zeep_service)
        assert zeep_service._binding_options["address"] == (
            "https://impl-services1.wd501.myworkday.com/ccx/service/nav/Human_Resources/v44.2"
        )

    def test_noop_for_matching_production_host(self):
        """Same host → address left byte-identical."""
        original = "https://services1.wd501.myworkday.com/ccx/service/nav/Human_Resources/v44.2"
        svc = _service_instance("https://services1.wd501.myworkday.com")
        zeep_service = _zeep_service(original)
        svc._point_endpoint_at_configured_host(zeep_service)
        assert zeep_service._binding_options["address"] == original

    def test_preserves_customreport2_path(self):
        """Long /ccx/service/customreport2/... paths survive unchanged."""
        svc = _service_instance("https://impl-services1.wd501.myworkday.com")
        original_path = "/ccx/service/customreport2/nav/isb_troc/My_Custom_Report"
        zeep_service = _zeep_service(
            f"https://services1.wd501.myworkday.com{original_path}"
        )
        svc._point_endpoint_at_configured_host(zeep_service)
        new_addr = zeep_service._binding_options["address"]
        assert new_addr == f"https://impl-services1.wd501.myworkday.com{original_path}"

    def test_missing_binding_options_is_safe(self):
        """service without _binding_options → returns without raising."""
        svc = _service_instance("https://impl-services1.wd501.myworkday.com")
        zeep_service = MagicMock(spec=[])  # no _binding_options attribute at all
        svc._point_endpoint_at_configured_host(zeep_service)  # must not raise

    def test_empty_binding_options_is_safe(self):
        svc = _service_instance("https://impl-services1.wd501.myworkday.com")
        zeep_service = _zeep_service(address=None)
        svc._point_endpoint_at_configured_host(zeep_service)  # must not raise

    def test_malformed_workday_url_is_safe(self):
        """Empty/garbage workday_url → original address intact."""
        original = "https://services1.wd501.myworkday.com/ccx/service/nav/Human_Resources/v44.2"
        svc = _service_instance("not-a-valid-url-no-netloc")
        zeep_service = _zeep_service(original)
        svc._point_endpoint_at_configured_host(zeep_service)
        assert zeep_service._binding_options["address"] == original

    def test_none_workday_url_is_safe(self):
        original = "https://services1.wd501.myworkday.com/ccx/service/nav/Human_Resources/v44.2"
        svc = _service_instance(None)
        zeep_service = _zeep_service(original)
        svc._point_endpoint_at_configured_host(zeep_service)
        assert zeep_service._binding_options["address"] == original

    def test_rewrite_failure_does_not_break_binding(self, caplog):
        """An exception during rewrite is caught, warned, and binding still returns."""
        svc = _service_instance("https://impl-services1.wd501.myworkday.com")
        svc._point_endpoint_at_configured_host = MagicMock(
            side_effect=RuntimeError("boom")
        )
        # simulate SOAPClient.bind_service()
        fake_service = MagicMock()

        with caplog.at_level(logging.WARNING), pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "parrot.interfaces.soap.SOAPClient.bind_service",
                lambda self: fake_service,
            )
            result = svc.bind_service()
        assert result is fake_service
        assert any("Could not override SOAP endpoint host" in r.message for r in caplog.records)

    def test_bind_service_calls_super_and_returns_service(self):
        svc = _service_instance("https://services1.wd501.myworkday.com")
        fake_service = _zeep_service(
            "https://services1.wd501.myworkday.com/ccx/service/nav/Human_Resources/v44.2"
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "parrot.interfaces.soap.SOAPClient.bind_service",
                lambda self: fake_service,
            )
            result = svc.bind_service()
        assert result is fake_service
