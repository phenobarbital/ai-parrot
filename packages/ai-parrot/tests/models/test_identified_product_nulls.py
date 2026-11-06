"""IdentifiedProduct tolerates null LLM answers and keeps free-form dicts out of its JSON schema."""

from parrot.models.detections import IdentificationResponse, IdentifiedProduct


def _product(**fields) -> IdentifiedProduct:
    return IdentifiedProduct(product_type="printer", confidence=0.8, **fields)


def test_visual_features_drops_null_entries() -> None:
    assert _product(visual_features=[None, "blue", None]).visual_features == ["blue"]


def test_visual_features_null_becomes_empty_list() -> None:
    assert _product(visual_features=None).visual_features == []


def test_visual_features_single_string_is_wrapped() -> None:
    assert _product(visual_features="glossy").visual_features == ["glossy"]


def test_extra_drops_null_values_and_stringifies() -> None:
    assert _product(extra={"a": None, "b": 2, "c": "x"}).extra == {"b": "2", "c": "x"}


def test_extra_null_becomes_empty_dict() -> None:
    assert _product(extra=None).extra == {}


def test_extra_is_not_in_json_schema() -> None:
    schema = IdentificationResponse.model_json_schema()
    properties = schema["$defs"]["IdentifiedProduct"]["properties"]
    assert "extra" not in properties
    assert "visual_features" in properties


def test_identification_response_validates_null_features() -> None:
    payload = {
        "detections": [
            {"product_type": "printer", "confidence": 0.9, "visual_features": [None], "extra": {"k": None}},
        ]
    }
    response = IdentificationResponse.model_validate(payload)
    product = response.identified_products[0]
    assert product.visual_features == []
    assert product.extra == {}
