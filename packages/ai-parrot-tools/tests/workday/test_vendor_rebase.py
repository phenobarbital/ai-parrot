"""Tests for TASK-1505: verify the vendored Workday composable is correctly rebased."""
import importlib
import subprocess

from parrot.interfaces.soap import SOAPClient
from parrot_tools.interfaces.workday.service import WorkdayService


def test_workdayservice_rebased_soapclient():
    """WorkdayService subclasses the CORE SOAPClient, not the flowtask base."""
    assert issubclass(WorkdayService, SOAPClient)


def test_no_flowtask_import_remains():
    """No vendored file references flowtask."""
    out = subprocess.run(
        ["grep", "-rl", "flowtask",
         "packages/ai-parrot-tools/src/parrot_tools/interfaces/workday"],
        capture_output=True, text=True,
    )
    assert out.stdout.strip() == ""


def test_config_reads_parrot_conf():
    """Vendored config resolves WORKDAY_* from parrot.conf."""
    cfg = importlib.import_module("parrot_tools.interfaces.workday.config")
    assert hasattr(cfg, "WorkdayConfig")
    assert hasattr(cfg, "get_wsdl_path")


def test_parrot_conf_has_missing_wsdl_constants():
    """parrot.conf exposes the 3 constants required by vendored config.py."""
    import parrot.conf as conf
    assert hasattr(conf, "WORKDAY_WSDL_INTEGRATIONS")
    assert hasattr(conf, "WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT")
    assert hasattr(conf, "WORKDAY_WSDL_TIME_BLOCK_REPORT")
