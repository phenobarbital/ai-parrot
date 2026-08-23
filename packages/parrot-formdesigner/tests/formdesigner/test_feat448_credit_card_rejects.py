"""Tests for TASK-2334 (FEAT-448) — credit_card REJECTS cardholder data,
never sanitizes it.

Decided by Juan, 2026-08-22: a validator that quietly strips ``cvv``
satisfies "not stored" while leaving every client free to keep sending it
into request logs. Truncating a PAN server-side is worse: it means the PAN
already reached the server. Both must be hard errors, not silent cleanup —
and the error itself must never echo the offending value back.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


@pytest.fixture
def validator() -> FormValidator:
    return FormValidator()


@pytest.fixture
def field() -> FormField:
    return FormField(
        field_id="payment_card",
        field_type=FieldType.CREDIT_CARD,
        label="Payment Card",
        required=False,
    )


class TestAcceptedShape:
    @pytest.mark.asyncio
    async def test_ac1_accepts_brand_last4_name_expiry(self, validator: FormValidator, field: FormField):
        value = {"brand": "visa", "last4": "4242", "name": "Jane Doe", "expiry": "12/29"}
        errors = await validator.validate_field(field, value)
        assert errors == []


class TestCvvRejected:
    @pytest.mark.asyncio
    async def test_ac2_cvv_present_is_an_error(self, validator: FormValidator, field: FormField):
        value = {
            "brand": "visa",
            "last4": "4242",
            "name": "Jane Doe",
            "expiry": "12/29",
            "cvv": "123",
        }
        errors = await validator.validate_field(field, value)
        assert errors, "a payload carrying cvv must produce a validation error"

    @pytest.mark.asyncio
    async def test_cvv_rejection_is_not_a_silent_strip(self, validator: FormValidator, field: FormField):
        """The forbidden implementation: strip cvv and report success. This
        test fails against that implementation because it demands an error,
        not merely the key's absence from some sanitized output."""
        value = {
            "brand": "visa",
            "last4": "4242",
            "name": "Jane Doe",
            "expiry": "12/29",
            "cvv": "123",
        }
        errors = await validator.validate_field(field, value)
        assert len(errors) > 0


class TestPanRejected:
    @pytest.mark.asyncio
    async def test_ac3_full_number_is_an_error(self, validator: FormValidator, field: FormField):
        value = {
            "brand": "visa",
            "number": "4242424242424242",
            "name": "Jane Doe",
            "expiry": "12/29",
        }
        errors = await validator.validate_field(field, value)
        assert errors, "a payload carrying the full PAN must produce a validation error"

    @pytest.mark.asyncio
    async def test_ac3_last4_of_five_digits_is_an_error(self, validator: FormValidator, field: FormField):
        value = {"brand": "visa", "last4": "42424", "name": "Jane Doe", "expiry": "12/29"}
        errors = await validator.validate_field(field, value)
        assert errors, "a last4 longer than 4 digits must produce a validation error"

    @pytest.mark.asyncio
    async def test_number_is_not_truncated_to_last4(self, validator: FormValidator, field: FormField):
        """The forbidden implementation: truncate 'number' to its last 4
        digits and accept. That means the full PAN already reached the
        server — this must be a hard error instead."""
        value = {
            "brand": "visa",
            "number": "4242424242424242",
            "name": "Jane Doe",
            "expiry": "12/29",
        }
        errors = await validator.validate_field(field, value)
        assert len(errors) > 0


class TestErrorDoesNotEchoValue:
    @pytest.mark.asyncio
    async def test_ac4_cvv_error_does_not_echo_cvv(self, validator: FormValidator, field: FormField):
        secret_cvv = "731"
        value = {
            "brand": "visa",
            "last4": "4242",
            "name": "Jane Doe",
            "expiry": "12/29",
            "cvv": secret_cvv,
        }
        errors = await validator.validate_field(field, value)
        joined = " ".join(errors)
        assert secret_cvv not in joined

    @pytest.mark.asyncio
    async def test_ac4_number_error_does_not_echo_pan(self, validator: FormValidator, field: FormField):
        secret_pan = "4242424242424242"
        value = {"brand": "visa", "number": secret_pan, "name": "Jane Doe", "expiry": "12/29"}
        errors = await validator.validate_field(field, value)
        joined = " ".join(errors)
        assert secret_pan not in joined

    @pytest.mark.asyncio
    async def test_ac4_bad_last4_error_does_not_echo_value(self, validator: FormValidator, field: FormField):
        bad_last4 = "99999"
        value = {"brand": "visa", "last4": bad_last4, "name": "Jane Doe", "expiry": "12/29"}
        errors = await validator.validate_field(field, value)
        joined = " ".join(errors)
        assert bad_last4 not in joined
