"""Tests for TASK-2335 (FEAT-448) — PLACE, the granular Country/State/City
cascade. LOCATION (the country picker) means something different and stays
untouched — AC4 asserts that explicitly rather than assuming it.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator, _validate_location


@pytest.fixture
def validator() -> FormValidator:
    return FormValidator()


@pytest.fixture
def place_field() -> FormField:
    return FormField(field_id="hometown", field_type=FieldType.PLACE, label="Hometown", required=False)


@pytest.fixture
def location_field() -> FormField:
    return FormField(field_id="country", field_type=FieldType.LOCATION, label="Country", required=False)


class TestPlaceAccepts:
    @pytest.mark.asyncio
    async def test_ac1_full_shape_validates(self, validator: FormValidator, place_field: FormField):
        value = {"country": "CA", "state": "ON", "city": "Ottawa"}
        errors = await validator.validate_field(place_field, value)
        assert errors == []

    @pytest.mark.asyncio
    async def test_ac3_state_and_city_optional(self, validator: FormValidator, place_field: FormField):
        errors = await validator.validate_field(place_field, {"country": "CA"})
        assert errors == []


class TestPlaceRejectsInvalidCountry:
    @pytest.mark.asyncio
    async def test_ac2_invalid_country_code_rejected(
        self, validator: FormValidator, place_field: FormField
    ):
        errors = await validator.validate_field(
            place_field, {"country": "ZZ", "state": "ON", "city": "Ottawa"}
        )
        assert errors

    @pytest.mark.asyncio
    async def test_ac2_error_message_matches_location_wording(
        self, validator: FormValidator, place_field: FormField
    ):
        """Same message shape is_valid_iso_country_code drives for location."""
        errors = await validator.validate_field(place_field, {"country": "ZZ"})
        assert any("is not a valid ISO 3166 country code" in e for e in errors)

    @pytest.mark.asyncio
    async def test_missing_country_is_rejected(self, validator: FormValidator, place_field: FormField):
        errors = await validator.validate_field(place_field, {"state": "ON", "city": "Ottawa"})
        assert errors

    @pytest.mark.asyncio
    async def test_non_dict_is_rejected(self, validator: FormValidator, place_field: FormField):
        errors = await validator.validate_field(place_field, "CA")
        assert errors


class TestLocationByteIdentical:
    """AC4 — LOCATION behaviour is byte-identical to before. Asserted, not
    assumed: this is the task most likely to 'tidy' location while passing
    through, so pin every observable piece of its behaviour."""

    @pytest.mark.asyncio
    async def test_location_still_accepts_valid_code(
        self, validator: FormValidator, location_field: FormField
    ):
        errors = await validator.validate_field(location_field, "ca")
        assert errors == []

    @pytest.mark.asyncio
    async def test_location_coercion_still_uppercases(self, validator: FormValidator):
        assert validator._coerce_value("ca", FormField(
            field_id="c", field_type=FieldType.LOCATION, label="C"
        )) == "CA"

    @pytest.mark.asyncio
    async def test_location_still_rejects_wrong_length(
        self, validator: FormValidator, location_field: FormField
    ):
        errors = await validator.validate_field(location_field, "USA")
        assert any("2-character ISO 3166 country code" in e for e in errors)

    @pytest.mark.asyncio
    async def test_location_still_rejects_invalid_code(
        self, validator: FormValidator, location_field: FormField
    ):
        errors = await validator.validate_field(location_field, "ZZ")
        assert any("is not a valid ISO 3166 country code" in e for e in errors)

    def test_validate_location_helper_untouched(self):
        """The module-private LOCATION helper still exists and behaves the
        same — PLACE uses a different function (is_valid_iso_country_code)
        entirely, so this one must be unaffected."""
        assert _validate_location("CA") is True
        assert _validate_location("ZZ") is False

    def test_location_registry_entry_untouched(self):
        entry = _BUILTIN_METADATA[FieldType.LOCATION]
        assert entry["description"] == "Country or location selector using ISO codes."
        assert entry["category"] == "selection"
        assert entry["render_hint"] == "select"


class TestPlaceRegistryEntry:
    def test_place_registered(self):
        assert FieldType.PLACE in _BUILTIN_METADATA

    def test_place_label_and_category(self):
        entry = _BUILTIN_METADATA[FieldType.PLACE]
        assert entry["label"]
        assert entry["category"] in {"basic", "selection", "media", "layout", "advanced"}
