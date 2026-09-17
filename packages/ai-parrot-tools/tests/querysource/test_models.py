import json
from parrot_tools.querysource import models as m


def test_slug_detail_redaction_by_omission():
    forbidden = {"source", "params", "attributes", "dwh_info", "dwh_scheduler", "cache_options"}
    assert forbidden.isdisjoint(m.SlugDetail.model_fields)


def test_execution_result_defaults_and_json():
    r = m.ExecutionResult(status="empty", returned_rows=0, duration_ms=3)
    assert r.rows == [] and r.truncated is False and r.total_rows is None
    json.dumps(r.model_dump())


def test_component_doc_matches_registry_shape():
    doc = m.ComponentDoc(
        name="Concat",
        category="Operators",
        description="d",
        usage="u",
        json_schema={"type": "object"},
        example='{"Concat": {}}',
        icon="git-merge",
    )
    assert set(doc.model_dump()) == {
        "name",
        "category",
        "description",
        "usage",
        "attributes",
        "json_schema",
        "example",
        "icon",
    }


def test_dialect_reference_variables_default():
    ref = m.DialectReference(
        verified_against="4.5.11",
        option_keys={},
        placeholder_rules=[],
        where_grammar=[],
        operators_list_form=[],
        operators_dict_form=[],
        examples=[],
        notes=[],
    )
    assert ref.variables == {}
