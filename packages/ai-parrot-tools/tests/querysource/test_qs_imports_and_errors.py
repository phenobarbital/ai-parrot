import pytest
from parrot.exceptions import ToolError
from parrot_tools.querysource import _qs, errors


@pytest.fixture(autouse=True)
def reset_slots(monkeypatch):
    for name in ("QS", "MultiQS", "QueryModel", "ComponentRegistry"):
        monkeypatch.setattr(_qs, name, None)


def test_slot_short_circuits_lazy_import(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(_qs, "QS", sentinel)
    monkeypatch.setattr(_qs, "lazy_import", lambda *a, **k: pytest.fail("lazy_import must not be called"))
    assert _qs.get_qs() is sentinel


def test_missing_dependency_raises_import_error(monkeypatch):
    def boom(module_path, package_name=None, extra=None):
        raise ImportError(f"{package_name} missing; pip install {package_name}[{extra}]")

    monkeypatch.setattr(_qs, "lazy_import", boom)
    with pytest.raises(ImportError, match="querysource"):
        _qs.get_multiqs()


def test_accessor_caches_into_slot(monkeypatch):
    class FakeMod:  # stands in for querysource.models
        QueryModel = type("QueryModel", (), {})

    calls = []
    monkeypatch.setattr(_qs, "lazy_import", lambda mp, package_name=None, extra=None: calls.append(mp) or FakeMod)
    assert _qs.get_query_model() is FakeMod.QueryModel
    assert _qs.get_query_model() is FakeMod.QueryModel
    assert calls == ["querysource.models"]


@pytest.mark.parametrize(
    "cls",
    [
        errors.SlugNotFoundError,
        errors.TenantDeniedError,
        errors.RawSqlForbiddenError,
        errors.WriteDisabledError,
        errors.InvalidConditionsError,
    ],
)
def test_error_hierarchy(cls):
    assert issubclass(cls, errors.QuerysourceToolkitError)
    assert issubclass(cls, ToolError)
