"""FEAT-232 TASK-1516 — legacy SOAP routing is gone; toolkit still works."""
import parrot_tools.workday.tool as wt
from parrot_tools.workday.tool import WorkdayToolkit


def test_legacy_module_symbols_removed():
    assert not hasattr(wt, "WorkdaySOAPClient")
    assert not hasattr(wt, "METHOD_TO_SERVICE_MAP")
    # The legacy WorkdayService(str, Enum) is gone. Only the composable alias remains.
    assert not hasattr(wt, "WorkdayService")
    assert hasattr(wt, "WorkdayComposable")


def test_legacy_instance_attrs_removed():
    tk = WorkdayToolkit()
    assert not hasattr(tk, "wsdl_paths")
    assert not hasattr(tk, "_clients")
    assert not hasattr(tk, "soap_client")
    assert not hasattr(tk, "_get_client_for_service")
    assert not hasattr(tk, "_get_client_for_method")
    # composable path remains
    assert hasattr(tk, "_get_composable")
    assert hasattr(tk, "_composables")


def test_payroll_methods_still_present():
    tk = WorkdayToolkit()
    for m in ("wd_get_payroll_balances", "wd_get_payroll_results", "wd_get_company_payment_dates"):
        assert callable(getattr(tk, m))
