"""Unit tests for services/unknown_fields.py (FEAT-458 Module 2).

Covers the two pure functions in isolation: compute_extra_data() (the
payload-side diff) and enforce_extras_cap() (hard rejection, never
truncation).
"""

import json

import pytest
from parrot_formdesigner.services.unknown_fields import (
    MAX_EXTRA_BYTES,
    MAX_EXTRA_KEYS,
    ExtrasCapExceeded,
    compute_extra_data,
    enforce_extras_cap,
)


class TestComputeExtraData:
    def test_basic(self):
        assert compute_extra_data({"name": "Ana", "legacy_id": 42}, {"name"}) == {"legacy_id": 42}

    def test_exact_match_returns_empty_dict(self):
        assert compute_extra_data({"name": "Ana"}, {"name"}) == {}

    def test_declared_but_absent_field_is_not_an_extra(self):
        """A declared field missing from the payload contributes nothing."""
        assert compute_extra_data({}, {"name", "email"}) == {}

    def test_declared_but_empty_value_is_not_an_extra(self):
        """The sanitized_data.keys() trap: a declared field whose value is None
        is DECLARED, so it must never be reported as caller junk (spec AC8)."""
        assert compute_extra_data({"name": None}, {"name"}) == {}

    def test_nested_field_ids_are_known(self):
        """GROUP children / ARRAY item_template ids count as declared (spec AC9)."""
        declared = {"address", "address_street", "address_city"}
        assert compute_extra_data({"address_street": "x", "junk": 1}, declared) == {"junk": 1}

    def test_does_not_mutate_payload(self):
        payload = {"a": 1, "b": 2}
        compute_extra_data(payload, {"a"})
        assert payload == {"a": 1, "b": 2}

    def test_empty_payload_returns_empty_dict(self):
        assert compute_extra_data({}, {"a", "b"}) == {}


class TestEnforceExtrasCap:
    def test_under_key_limit_passes(self):
        enforce_extras_cap({f"k{i}": i for i in range(MAX_EXTRA_KEYS - 1)})

    def test_at_key_limit_passes(self):
        """Exactly at the cap is accepted (spec AC6)."""
        enforce_extras_cap({f"k{i}": i for i in range(MAX_EXTRA_KEYS)})

    def test_over_key_limit_raises(self):
        extras = {f"k{i}": i for i in range(MAX_EXTRA_KEYS + 1)}
        with pytest.raises(ExtrasCapExceeded) as exc:
            enforce_extras_cap(extras)
        assert exc.value.limit == "keys"
        assert exc.value.actual == MAX_EXTRA_KEYS + 1
        assert exc.value.maximum == MAX_EXTRA_KEYS

    def test_over_byte_limit_raises(self):
        extras = {"blob": "x" * (MAX_EXTRA_BYTES + 1)}
        with pytest.raises(ExtrasCapExceeded) as exc:
            enforce_extras_cap(extras)
        assert exc.value.limit == "bytes"

    def test_multibyte_counted_as_utf8_bytes(self):
        """A 2-byte-per-char string must not slip past the byte cap."""
        extras = {"blob": "ñ" * MAX_EXTRA_BYTES}
        assert len(json.dumps(extras).encode("utf-8")) > MAX_EXTRA_BYTES
        with pytest.raises(ExtrasCapExceeded):
            enforce_extras_cap(extras)

    def test_never_truncates(self):
        """The input is untouched after a raise (spec AC5)."""
        extras = {f"k{i}": i for i in range(MAX_EXTRA_KEYS + 5)}
        snapshot = dict(extras)
        with pytest.raises(ExtrasCapExceeded):
            enforce_extras_cap(extras)
        assert extras == snapshot

    def test_empty_extras_passes(self):
        enforce_extras_cap({})
