"""Tests for Workday response models helpers."""
"""Tests for Workday response models helpers."""

import importlib.util
from pathlib import Path
import sys
import types


def _load_workday_models_module():
    """Load the real workday models module bypassing the lightweight stubs."""

    # Provide a lightweight zeep.helpers implementation so the module can be
    # imported without the optional zeep dependency during unit tests.
    if "zeep.helpers" not in sys.modules:
        zeep_module = types.ModuleType("zeep")
        helpers_module = types.ModuleType("zeep.helpers")

        def _serialize_object(value, *_args, **_kwargs):
            return value

        helpers_module.serialize_object = _serialize_object
        zeep_module.helpers = helpers_module
        sys.modules.setdefault("zeep", zeep_module)
        sys.modules.setdefault("zeep.helpers", helpers_module)

    module_path = Path(__file__).resolve().parents[1] / "parrot" / "tools" / "workday" / "models.py"
    spec = importlib.util.spec_from_file_location("_workday_models", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None  # for mypy/typing tools
    spec.loader.exec_module(module)
    return module


def test_parse_time_off_balance_response_handles_null_worker_data():
    """Regression test for null Worker_Data in time off balance responses."""

    workday_models = _load_workday_models_module()
    WorkdayResponseParser = workday_models.WorkdayResponseParser
    TimeOffBalanceModel = workday_models.TimeOffBalanceModel

    response = {
        "Response_Data": {
            "Worker": [
                {
                    "Worker_Data": None,
                }
            ]
        }
    }

    result = WorkdayResponseParser.parse_time_off_balance_response(
        response,
        worker_id="12345",
    )

    assert isinstance(result, TimeOffBalanceModel)
    assert result.worker_id == "12345"
    assert result.balances == []
    assert result.vacation_balance is None

