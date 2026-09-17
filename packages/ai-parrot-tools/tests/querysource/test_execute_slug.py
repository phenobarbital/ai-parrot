import pytest
import pandas as pd
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.querysource.errors import InvalidConditionsError, TenantDeniedError, QuerysourceToolkitError


class _Exc:  # stand-in for querysource.exceptions
    class QueryException(Exception):
        pass

    class SlugNotFound(QueryException):
        pass

    class DataNotFound(QueryException):
        pass


@pytest.fixture
def fake_qs(patched_qs, monkeypatch):
    state = {"init": None, "query": None, "closed": 0, "behaviour": "ok"}

    class FakeQS:
        def __init__(self, **kw):
            state["init"] = kw

        async def query(self, output_format=None):
            state["query"] = output_format
            if state["behaviour"] == "empty":
                raise _Exc.DataNotFound("no data")
            if state["behaviour"] == "error":
                return None, "boom"
            return pd.DataFrame({"a": range(3)}), None

        async def close(self):
            state["closed"] += 1

    monkeypatch.setattr(_qs, "QS", FakeQS)
    monkeypatch.setattr(_qs, "get_exceptions", lambda: _Exc)
    return state


async def test_payload_cap_and_close(fake_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake", max_rows=200)
    r = await tk.execute_slug(
        "epson_field_activity",
        placeholders={"firstdate": "2026-08-09", "lastdate": "2026-08-15"},
        filter={"store": ["1", "2"]},
        limit=5000,
    )
    assert (
        fake_qs["init"]["conditions"]["querylimit"] == 200
        and fake_qs["init"]["conditions"]["firstdate"] == "2026-08-09"
    )
    assert fake_qs["query"] == "pandas" and fake_qs["closed"] == 1 and r.returned_rows == 3


async def test_validation_before_qs(fake_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError):
        await tk.execute_slug("epson_field_activity", placeholders={"nope": 1})
    with pytest.raises(InvalidConditionsError):
        await tk.execute_slug("epson_field_activity", filter={"a b": 1})
    with pytest.raises(TenantDeniedError):
        await QuerysourceToolkit(dsn="postgres://fake", programs=["pokemon"]).execute_slug("epson_field_activity")
    assert fake_qs["init"] is None


async def test_empty_and_error(fake_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    fake_qs["behaviour"] = "empty"
    assert (await tk.execute_slug("epson_field_activity")).status == "empty" and fake_qs["closed"] == 1
    fake_qs["behaviour"] = "error"
    with pytest.raises(QuerysourceToolkitError):
        await tk.execute_slug("epson_field_activity")
    assert fake_qs["closed"] == 2
