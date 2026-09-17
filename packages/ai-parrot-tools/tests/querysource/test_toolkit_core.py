import pytest
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.querysource.errors import TenantDeniedError


@pytest.fixture
def tk(patched_qs):
    def make(**kw):
        return QuerysourceToolkit(dsn="postgres://fake", **kw)

    return make


def test_tool_names_and_write_gate(tk):
    # Final tool set (spec §5 AC): 7 without write; qs_save_multiquery only when allow_write=True (added TASK-3254).
    assert sorted(tk().list_tool_names()) == [
        "qs_describe_slug",
        "qs_execute_slug",
        "qs_get_dialect_reference",
        "qs_list_components",
        "qs_list_slugs",
        "qs_run_multiquery",
        "qs_validate_pipeline",
    ]
    assert sorted(tk(allow_write=True).list_tool_names()) == [
        "qs_describe_slug",
        "qs_execute_slug",
        "qs_get_dialect_reference",
        "qs_list_components",
        "qs_list_slugs",
        "qs_run_multiquery",
        "qs_save_multiquery",
        "qs_validate_pipeline",
    ]
    assert "save_multiquery" in tk().exclude_tools and "save_multiquery" not in tk(allow_write=True).exclude_tools


async def test_describe_redaction_and_multiquery(tk):
    d = await tk().describe_slug("pokemon_all_fso_odoo_new")
    assert (
        d.is_multiquery
        and d.pipeline
        and d.sql is None
        and not {"source", "params", "attributes"} & set(d.model_dump())
    )
    e = await tk(include_sql=False).describe_slug("epson_field_activity")
    assert e.sql is None and [p.name for p in e.placeholders_detail] == ["firstdate", "lastdate"]


async def test_describe_denied_before_qs(tk, monkeypatch):
    monkeypatch.setattr(_qs, "QS", lambda **kw: pytest.fail("QS must not be built"))
    with pytest.raises(TenantDeniedError):
        await tk(programs=["pokemon"]).describe_slug("epson_field_activity", dry_run=True)


async def test_dry_run_closes(tk, monkeypatch):
    closed = []

    class FakeQS:
        def __init__(self, **kw):
            pass

        async def dry_run(self):
            return ["SELECT 1", None]

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(_qs, "QS", FakeQS)
    d = await tk().describe_slug("epson_field_activity", dry_run=True)
    assert d.rendered_query == "SELECT 1" and closed


async def test_dialect_reference_has_variables_field(tk):
    ref = await tk().get_dialect_reference()
    assert ref.verified_against == "4.5.11" and isinstance(ref.variables, dict)
