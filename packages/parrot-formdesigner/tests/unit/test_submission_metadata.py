"""Tests for form submission metadata (FormMetadataField + enricher)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.schema import (
    FormField,
    FormMetadataField,
    FormSchema,
    FormSection,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.auth_context import AuthContext
from parrot_formdesigner.services.callback_registry import (
    _clear_registry_for_tests,
    register_form_callback,
)
from parrot_formdesigner.services.metadata_callbacks import (
    MetadataCallbackInput,
    MetadataCallbackOutput,
)
from parrot_formdesigner.services.metadata_enricher import (
    MetadataResolutionError,
    enrich_submission,
)
from parrot_formdesigner.services.submissions import FormSubmission


# ---------------------------------------------------------------------------
# Stubs that mimic aiohttp / navigator-auth shape just enough for resolvers.
# ---------------------------------------------------------------------------


class _StubOrg:
    def __init__(self, org_id: Any) -> None:
        self.org_id = org_id


class _StubUser:
    def __init__(
        self,
        *,
        user_id: Any = None,
        username: str | None = None,
        organizations: list[_StubOrg] | None = None,
    ) -> None:
        self.user_id = user_id
        self.username = username
        self.organizations = organizations or []


class _StubRequest:
    """Minimal stand-in for aiohttp.web.Request used by resolvers."""

    def __init__(
        self,
        *,
        user: _StubUser | None = None,
        session: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        remote: str | None = None,
    ) -> None:
        self.user = user
        self.session = session
        self.headers = headers or {}
        self.remote = remote


def _form(
    *,
    metadata: list[FormMetadataField] | None = None,
    fields: list[FormField] | None = None,
    tenant: str | None = None,
) -> FormSchema:
    return FormSchema(
        form_id="form-1",
        title="t",
        sections=[FormSection(section_id="s", fields=fields or [])],
        metadata=metadata,
        tenant=tenant,
    )


def _submission(tenant: str | None = None) -> FormSubmission:
    return FormSubmission(
        submission_id="sub-1",
        form_id="form-1",
        form_version="1.0",
        data={},
        is_valid=True,
        created_at=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        tenant=tenant,
    )


@pytest.fixture(autouse=True)
def _clear_callbacks():
    """Ensure each test starts with a clean callback registry."""
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


# ---------------------------------------------------------------------------
# FormMetadataField + FormSchema validation
# ---------------------------------------------------------------------------


class TestFormMetadataFieldValidation:
    def test_callback_source_requires_callback_ref(self) -> None:
        with pytest.raises(ValidationError) as exc:
            FormMetadataField(key="x", source="callback")
        assert "callback_ref" in str(exc.value)

    def test_non_callback_source_forbids_callback_ref(self) -> None:
        with pytest.raises(ValidationError) as exc:
            FormMetadataField(
                key="x", source="user_id", callback_ref="oops"
            )
        assert "callback_ref" in str(exc.value)

    def test_builtin_source_constructs_cleanly(self) -> None:
        mf = FormMetadataField(key="user_id", source="user_id")
        assert mf.source == "user_id"
        assert mf.callback_ref is None


class TestFormSchemaMetadataValidator:
    def test_metadata_defaults_none(self) -> None:
        f = _form()
        assert f.metadata is None

    def test_collision_with_field_id_is_rejected(self) -> None:
        field = FormField(
            field_id="email", field_type=FieldType.EMAIL, label="Email"
        )
        with pytest.raises(ValidationError) as exc:
            _form(
                fields=[field],
                metadata=[FormMetadataField(key="email", source="username")],
            )
        assert "collides" in str(exc.value)

    def test_duplicate_metadata_keys_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _form(
                metadata=[
                    FormMetadataField(key="user_id", source="user_id"),
                    FormMetadataField(key="user_id", source="username"),
                ]
            )
        assert "Duplicate" in str(exc.value)

    def test_callback_shadowing_builtin_key_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _form(
                metadata=[
                    FormMetadataField(
                        key="user_id",
                        source="callback",
                        callback_ref="custom_user",
                    )
                ]
            )
        assert "reserved" in str(exc.value)

    def test_invalid_key_identifier_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _form(
                metadata=[
                    FormMetadataField(key="has space", source="username")
                ]
            )
        assert "identifier" in str(exc.value)


# ---------------------------------------------------------------------------
# enrich_submission
# ---------------------------------------------------------------------------


class TestEnrichSubmissionBuiltins:
    async def test_resolves_request_context(self) -> None:
        form = _form(
            metadata=[
                FormMetadataField(key="user_id", source="user_id"),
                FormMetadataField(key="username", source="username"),
                FormMetadataField(key="org_id", source="org_id"),
                FormMetadataField(key="ip", source="ip"),
                FormMetadataField(key="user_agent", source="user_agent"),
                FormMetadataField(key="locale", source="locale"),
                FormMetadataField(
                    key="submitted_at", source="submitted_at"
                ),
                FormMetadataField(key="programs", source="programs"),
            ],
            tenant="acme",
        )
        request = _StubRequest(
            user=_StubUser(
                user_id=42,
                username="alice",
                organizations=[_StubOrg(7)],
            ),
            session={"session": {"programs": ["sales", "ops"]}},
            headers={
                "User-Agent": "ParrotTest/1.0",
                "X-Forwarded-For": "203.0.113.5, 10.0.0.1",
                "Accept-Language": "en-US,en;q=0.8",
            },
            remote="10.0.0.99",
        )
        submission = _submission()

        core, extra = await enrich_submission(
            request=request,
            form=form,
            submission=submission,
            answers={"q1": "yes"},
            auth_context=AuthContext(scheme="none"),
        )

        assert core["user_id"] == "42"
        assert core["username"] == "alice"
        assert core["org_id"] == 7
        assert core["ip"] == "203.0.113.5"
        assert core["user_agent"] == "ParrotTest/1.0"
        assert core["locale"] == "en-US"
        assert core["submitted_at"] == submission.created_at
        # programs is NOT a core column; lives in extra_flat.
        assert extra == {"programs": ["sales", "ops"]}

    async def test_ip_falls_back_to_remote(self) -> None:
        form = _form(
            metadata=[FormMetadataField(key="ip", source="ip")]
        )
        request = _StubRequest(remote="198.51.100.4")
        core, _ = await enrich_submission(
            request=request,
            form=form,
            submission=_submission(),
            answers={},
            auth_context=AuthContext(scheme="none"),
        )
        assert core["ip"] == "198.51.100.4"

    async def test_missing_optional_value_uses_default(self) -> None:
        form = _form(
            metadata=[
                FormMetadataField(
                    key="locale", source="locale", default="en-GB"
                )
            ]
        )
        core, _ = await enrich_submission(
            request=_StubRequest(),
            form=form,
            submission=_submission(),
            answers={},
            auth_context=AuthContext(scheme="none"),
        )
        assert core["locale"] == "en-GB"

    async def test_required_missing_raises(self) -> None:
        form = _form(
            metadata=[
                FormMetadataField(
                    key="user_id", source="user_id", required=True
                )
            ]
        )
        with pytest.raises(MetadataResolutionError):
            await enrich_submission(
                request=_StubRequest(),
                form=form,
                submission=_submission(),
                answers={},
                auth_context=AuthContext(scheme="none"),
            )


class TestEnrichSubmissionCallbacks:
    async def test_single_value_callback(self) -> None:
        @register_form_callback("store_lookup")
        async def _cb(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            assert payload.field.key == "store_id"
            return MetadataCallbackOutput(success=True, value="S-77")

        form = _form(
            metadata=[
                FormMetadataField(
                    key="store_id",
                    source="callback",
                    callback_ref="store_lookup",
                )
            ]
        )
        core, extra = await enrich_submission(
            request=_StubRequest(),
            form=form,
            submission=_submission(),
            answers={},
            auth_context=AuthContext(scheme="none"),
        )
        assert core == {}
        assert extra == {"store_id": "S-77"}

    async def test_fan_out_callback(self) -> None:
        @register_form_callback("geo_lookup")
        async def _cb(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            return MetadataCallbackOutput(
                success=True,
                values={"lat": 1.23, "lng": 4.56, "accuracy": 9.0},
            )

        form = _form(
            metadata=[
                FormMetadataField(
                    key="lat",
                    source="callback",
                    callback_ref="geo_lookup",
                )
            ]
        )
        _, extra = await enrich_submission(
            request=_StubRequest(),
            form=form,
            submission=_submission(),
            answers={},
            auth_context=AuthContext(scheme="none"),
        )
        assert extra == {"lat": 1.23, "lng": 4.56, "accuracy": 9.0}

    async def test_callback_failure_non_required_uses_default(self) -> None:
        @register_form_callback("flaky")
        async def _cb(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            return MetadataCallbackOutput(success=False, error="boom")

        form = _form(
            metadata=[
                FormMetadataField(
                    key="store_id",
                    source="callback",
                    callback_ref="flaky",
                    default="UNKNOWN",
                )
            ]
        )
        _, extra = await enrich_submission(
            request=_StubRequest(),
            form=form,
            submission=_submission(),
            answers={},
            auth_context=AuthContext(scheme="none"),
        )
        assert extra == {"store_id": "UNKNOWN"}

    async def test_callback_failure_required_raises(self) -> None:
        @register_form_callback("flaky")
        async def _cb(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            return MetadataCallbackOutput(success=False, error="boom")

        form = _form(
            metadata=[
                FormMetadataField(
                    key="store_id",
                    source="callback",
                    callback_ref="flaky",
                    required=True,
                )
            ]
        )
        with pytest.raises(MetadataResolutionError):
            await enrich_submission(
                request=_StubRequest(),
                form=form,
                submission=_submission(),
                answers={},
                auth_context=AuthContext(scheme="none"),
            )

    async def test_callback_raises_non_required_uses_default(self) -> None:
        @register_form_callback("explosive")
        async def _cb(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            raise RuntimeError("kaboom")

        form = _form(
            metadata=[
                FormMetadataField(
                    key="store_id",
                    source="callback",
                    callback_ref="explosive",
                    default="UNKNOWN",
                )
            ]
        )
        _, extra = await enrich_submission(
            request=_StubRequest(),
            form=form,
            submission=_submission(),
            answers={},
            auth_context=AuthContext(scheme="none"),
        )
        assert extra == {"store_id": "UNKNOWN"}

    async def test_callback_unregistered_with_required_raises(self) -> None:
        form = _form(
            metadata=[
                FormMetadataField(
                    key="store_id",
                    source="callback",
                    callback_ref="ghost",
                    required=True,
                )
            ]
        )
        with pytest.raises(MetadataResolutionError):
            await enrich_submission(
                request=_StubRequest(),
                form=form,
                submission=_submission(),
                answers={},
                auth_context=AuthContext(scheme="none"),
            )

    async def test_tenant_scoped_callback_overrides_global(self) -> None:
        @register_form_callback("role")
        async def _global(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            return MetadataCallbackOutput(success=True, value="default")

        @register_form_callback("role", tenant="acme")
        async def _acme(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            return MetadataCallbackOutput(success=True, value="acme-role")

        form = _form(
            metadata=[
                FormMetadataField(
                    key="role",
                    source="callback",
                    callback_ref="role",
                )
            ],
            tenant="acme",
        )
        _, extra = await enrich_submission(
            request=_StubRequest(),
            form=form,
            submission=_submission(tenant="acme"),
            answers={},
            auth_context=AuthContext(scheme="none"),
        )
        assert extra == {"role": "acme-role"}


class TestEnrichSubmissionEdgeCases:
    async def test_no_metadata_returns_empty(self) -> None:
        core, extra = await enrich_submission(
            request=_StubRequest(),
            form=_form(),
            submission=_submission(),
            answers={"a": 1},
            auth_context=AuthContext(scheme="none"),
        )
        assert core == {}
        assert extra == {}

    async def test_collision_with_answer_raises(self) -> None:
        @register_form_callback("custom")
        async def _cb(
            payload: MetadataCallbackInput, auth: AuthContext
        ) -> MetadataCallbackOutput:
            return MetadataCallbackOutput(success=True, value="x")

        form = _form(
            metadata=[
                FormMetadataField(
                    key="store_id",
                    source="callback",
                    callback_ref="custom",
                )
            ]
        )
        with pytest.raises(MetadataResolutionError):
            await enrich_submission(
                request=_StubRequest(),
                form=form,
                submission=_submission(),
                # answer key already contains "store_id" — collision.
                answers={"store_id": "user-supplied"},
                auth_context=AuthContext(scheme="none"),
            )
