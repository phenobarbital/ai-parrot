"""TASK-3322: safety and status classification tests for the reel error taxonomy.

Verifies ``classify_provider_error`` maps structured google-genai
``APIError``/``ClientError``/``ServerError`` fields (never text substrings)
to stable ``ReelErrorCode`` values, normalizes operation/filtered-output/
download/media failures, redacts sensitive values, and never reclassifies
``asyncio.CancelledError``.
"""

import asyncio

import pytest
from google.genai import errors as genai_errors

from parrot.clients.google.reel.errors import (
    DownloadFailure,
    FilteredOutputError,
    MediaValidationFailure,
    OperationFailure,
    ReelError,
    ReelErrorCode,
    ReelValidationError,
    classify_provider_error,
)


def _client_error(code: int, status: str, message: str, reason: str | None = None) -> genai_errors.ClientError:
    error_body: dict = {"status": status, "message": message}
    if reason is not None:
        error_body["details"] = [{"reason": reason}]
    return genai_errors.ClientError(code, {"error": error_body})


def _server_error(code: int, status: str, message: str) -> genai_errors.ServerError:
    return genai_errors.ServerError(code, {"error": {"status": status, "message": message}})


def test_immediate_client_error_with_structured_safety_reason_is_safety_blocked():
    exc = _client_error(400, "INVALID_ARGUMENT", "request blocked", reason="SAFETY")
    result = classify_provider_error(exc, stage="veo_submit", scene_index=2)
    assert result.code is ReelErrorCode.SAFETY_BLOCKED
    assert result.retryable is False
    assert result.scene_index == 2
    assert result.stage == "veo_submit"


def test_403_permission_denied_is_auth_not_inferred_as_safety():
    """A bare 403 must never be inferred as a safety block (only a structured
    reason may produce SAFETY_BLOCKED)."""
    exc = _client_error(403, "PERMISSION_DENIED", "no access to this model")
    result = classify_provider_error(exc, stage="veo_submit")
    assert result.code is ReelErrorCode.AUTH_OR_ACCESS
    assert result.retryable is False


def test_401_unauthenticated_is_auth_or_access():
    exc = _client_error(401, "UNAUTHENTICATED", "missing credentials")
    result = classify_provider_error(exc, stage="veo_submit")
    assert result.code is ReelErrorCode.AUTH_OR_ACCESS
    assert result.retryable is False


def test_400_invalid_argument_without_reason_is_invalid_configuration_not_safety():
    """A bare 400 must never be inferred as a safety block either."""
    exc = _client_error(400, "INVALID_ARGUMENT", "duration out of range")
    result = classify_provider_error(exc, stage="veo_submit")
    assert result.code is ReelErrorCode.INVALID_CONFIGURATION
    assert result.retryable is False


def test_404_not_found_is_unknown_model():
    exc = _client_error(404, "NOT_FOUND", "model not found")
    result = classify_provider_error(exc, stage="veo_submit")
    assert result.code is ReelErrorCode.UNKNOWN_MODEL
    assert result.retryable is False


def test_429_resource_exhausted_is_quota_and_retryable():
    exc = _client_error(429, "RESOURCE_EXHAUSTED", "rate limited")
    result = classify_provider_error(exc, stage="veo_poll")
    assert result.code is ReelErrorCode.QUOTA_OR_RATE_LIMIT
    assert result.retryable is True


def test_timeout_status_is_retryable():
    exc = _client_error(408, "DEADLINE_EXCEEDED", "timed out")
    result = classify_provider_error(exc, stage="veo_poll")
    assert result.code is ReelErrorCode.TIMEOUT
    assert result.retryable is True


def test_5xx_server_error_is_provider_failure_and_retryable():
    exc = _server_error(503, "UNAVAILABLE", "service down")
    result = classify_provider_error(exc, stage="veo_submit")
    assert result.code is ReelErrorCode.PROVIDER_FAILURE
    assert result.retryable is True


def test_unclassified_exception_is_provider_failure_not_retryable():
    result = classify_provider_error(RuntimeError("something odd"), stage="veo_submit")
    assert result.code is ReelErrorCode.PROVIDER_FAILURE
    assert result.retryable is False


def test_cancelled_error_is_never_reclassified():
    with pytest.raises(asyncio.CancelledError):
        classify_provider_error(asyncio.CancelledError(), stage="veo_submit")


def test_already_classified_reel_error_passes_through_unchanged():
    original = ReelValidationError(ReelErrorCode.UNSUPPORTED_OPTION, "bad option")
    result = classify_provider_error(original, stage="registry_validate")
    assert result is original


def test_operation_failure_preserves_operation_id_and_classifies_by_code():
    exc = OperationFailure("operation errored", code="RESOURCE_EXHAUSTED", operation_id="op-123")
    result = classify_provider_error(exc, stage="veo_poll", scene_index=0)
    assert result.code is ReelErrorCode.QUOTA_OR_RATE_LIMIT
    assert result.retryable is True
    assert result.operation_id == "op-123"


def test_operation_failure_with_numeric_server_code_is_provider_failure():
    exc = OperationFailure("operation errored", code=500, operation_id="op-456")
    result = classify_provider_error(exc, stage="veo_poll")
    assert result.code is ReelErrorCode.PROVIDER_FAILURE
    assert result.retryable is True
    assert result.operation_id == "op-456"


def test_filtered_output_with_structured_safety_reason_is_safety_blocked():
    exc = FilteredOutputError("no clips returned", reason="PROHIBITED_CONTENT", operation_id="op-789")
    result = classify_provider_error(exc, stage="veo_download")
    assert result.code is ReelErrorCode.SAFETY_BLOCKED
    assert result.retryable is False
    assert result.operation_id == "op-789"


def test_filtered_output_without_reason_is_not_inferred_as_safety():
    """Empty output alone (no structured reason) must not be inferred as a
    safety block — only PROVIDER_FAILURE, per the 'never infer safety solely
    from empty output' requirement."""
    exc = FilteredOutputError("no clips returned")
    result = classify_provider_error(exc, stage="veo_download")
    assert result.code is ReelErrorCode.PROVIDER_FAILURE
    assert result.retryable is False


def test_download_failure_is_retryable():
    exc = DownloadFailure("connection reset mid-download")
    result = classify_provider_error(exc, stage="veo_download", scene_index=1)
    assert result.code is ReelErrorCode.DOWNLOAD_FAILED
    assert result.retryable is True
    assert result.scene_index == 1


def test_media_validation_failure_is_not_retryable():
    exc = MediaValidationFailure("zero-byte output file")
    result = classify_provider_error(exc, stage="media_validate")
    assert result.code is ReelErrorCode.MEDIA_INVALID
    assert result.retryable is False


def test_reel_validation_error_is_terminal_before_any_provider_call():
    exc = ReelValidationError(ReelErrorCode.WRONG_API_SURFACE, "veo-3.1 not on vertex")
    assert exc.retryable is False
    assert exc.stage == "validation"
    assert exc.operation_id is None


@pytest.mark.parametrize(
    "code",
    [
        ReelErrorCode.WRONG_API_SURFACE,
        ReelErrorCode.MODEL_DISABLED,
        ReelErrorCode.UNSUPPORTED_OPTION,
    ],
)
def test_registry_validation_codes_are_present_in_taxonomy(code: ReelErrorCode):
    """The profile registry contract (TASK-3323) requires these three codes
    to exist alongside the spec's listed enum values."""
    assert isinstance(code.value, str) and code.value


def test_bearer_token_is_redacted_from_error_message():
    exc = ReelError(
        ReelErrorCode.AUTH_OR_ACCESS,
        "request failed, Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz012345",
        stage="veo_submit",
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in str(exc)
    assert "[REDACTED]" in str(exc)


def test_google_api_key_is_redacted_from_error_message():
    fake_key = "AIza" + "x" * 35
    exc = ReelError(ReelErrorCode.INVALID_CONFIGURATION, f"bad key {fake_key}", stage="veo_submit")
    assert fake_key not in str(exc)
    assert "[REDACTED_KEY]" in str(exc)


def test_base64_blob_is_redacted_from_error_message():
    blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5QUJDREVGR0g="
    exc = ReelError(ReelErrorCode.MEDIA_INVALID, f"payload was {blob}", stage="media_validate")
    assert blob not in str(exc)
    assert "[REDACTED_BASE64]" in str(exc)


def test_key_value_credential_pair_is_redacted():
    exc = ReelError(
        ReelErrorCode.AUTH_OR_ACCESS,
        "request failed with api_key=super-secret-value-123",
        stage="veo_submit",
    )
    assert "super-secret-value-123" not in str(exc)
