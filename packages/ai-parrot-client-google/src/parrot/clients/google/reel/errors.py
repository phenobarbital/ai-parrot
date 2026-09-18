"""Structured error taxonomy and provider-error classification for video reels.

Implements spec module M2 ("Profile registry & error taxonomy") of
``sdd/specs/video-reel-omni-veo-reliability.spec.md`` §3: a stable
``ReelErrorCode`` enum, the ``ReelError``/``ReelValidationError`` exception
pair, and ``classify_provider_error()`` — the single entry point that turns a
raw provider/local failure into a structured, stable-coded error using only
structured status/reason fields (never message substring inference).

Safety, auth and invalid-configuration failures are always terminal
(``retryable=False``); only quota, timeout and generic provider failures may
be marked retryable, and even then only for bounded, safe reads/downloads —
never as authorization to resubmit generation (see spec §2 item 10).
"""

from __future__ import annotations

import asyncio
import re
from enum import Enum
from typing import Any, Optional

# Lazy SDK guard: see ``client.py`` for the rationale. This module must import
# even when google-genai is not installed; classification simply treats any
# exception as unrecognized until the SDK is present.
try:
    from google.genai import errors as genai_errors
except ImportError:  # pragma: no cover - exercised when extra is missing
    genai_errors = None  # type: ignore[assignment]


class ReelErrorCode(str, Enum):
    """Stable, spec-defined error codes for video-reel generation failures."""

    SAFETY_BLOCKED = "safety_blocked"
    AUTH_OR_ACCESS = "auth_or_access"
    INVALID_CONFIGURATION = "invalid_configuration"
    QUOTA_OR_RATE_LIMIT = "quota_or_rate_limit"
    TIMEOUT = "timeout"
    INSUFFICIENT_DURATION = "insufficient_duration"
    NARRATION_TOO_LONG = "narration_too_long"
    DOWNLOAD_FAILED = "download_failed"
    MEDIA_INVALID = "media_invalid"
    PROVIDER_FAILURE = "provider_failure"
    UNKNOWN_MODEL = "unknown_model"
    # Validation codes used by the profile registry contract (M2 profiles.py,
    # TASK-3323): included here so the taxonomy is complete in one place.
    WRONG_API_SURFACE = "wrong_api_surface"
    MODEL_DISABLED = "model_disabled"
    UNSUPPORTED_OPTION = "unsupported_option"


class ReelError(Exception):
    """Structured, stable-coded error for any stage of reel generation.

    Args:
        code: Stable :class:`ReelErrorCode` identifying the failure category.
        message: Human-readable, redacted description (no credentials/base64).
        stage: Pipeline stage where the failure occurred (e.g. ``"veo_submit"``).
        scene_index: Original scene index, if the failure is scene-scoped.
        retryable: Whether a bounded, safe retry (read/download only, never a
            generation resubmission) is permitted for this failure.
        operation_id: Provider long-running operation ID, if one was issued.
    """

    def __init__(
        self,
        code: ReelErrorCode,
        message: str,
        *,
        stage: str,
        scene_index: Optional[int] = None,
        retryable: bool = False,
        operation_id: Optional[str] = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.scene_index = scene_index
        self.retryable = retryable
        self.operation_id = operation_id
        super().__init__(_redact(message))


class ReelValidationError(ReelError):
    """Raised before any paid provider call (config/registry validation)."""

    def __init__(
        self,
        code: ReelErrorCode,
        message: str,
        *,
        stage: str = "validation",
        scene_index: Optional[int] = None,
    ) -> None:
        super().__init__(
            code,
            message,
            stage=stage,
            scene_index=scene_index,
            retryable=False,
            operation_id=None,
        )


class OperationFailure(Exception):
    """Normalizes a terminal long-running-operation error (e.g. Veo's
    ``operation.error``) so it can be passed through :func:`classify_provider_error`.

    Args:
        code: Provider-reported status/error code, if any (int or gRPC string).
        message: Provider-reported error message.
        operation_id: The operation's provider-assigned ID, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        code: Optional[Any] = None,
        operation_id: Optional[str] = None,
    ) -> None:
        self.code = code
        self.operation_id = operation_id
        super().__init__(message)


class FilteredOutputError(Exception):
    """Normalizes an empty/safety-filtered successful response (no HTTP error
    was raised, but the provider returned no usable content).

    Args:
        message: Description of what was filtered/empty.
        reason: Structured provider reason string, if one was reported
            (e.g. ``"SAFETY"``, ``"PROHIBITED_CONTENT"``, ``"RECITATION"``,
            ``"BLOCKLIST"``). ``None`` means no structured reason was given.
        operation_id: The operation's provider-assigned ID, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> None:
        self.reason = reason
        self.operation_id = operation_id
        super().__init__(message)


class DownloadFailure(Exception):
    """Normalizes a local/transport failure while downloading generated media."""


class MediaValidationFailure(Exception):
    """Normalizes a local failure validating downloaded/decoded media
    (unreadable file, MIME mismatch, zero bytes, corrupt container, ...).
    """


# Structured gRPC-style status strings that map to a terminal, safety-adjacent
# classification. Matched only against the SDK's structured ``status``/reason
# fields — never against free-text messages.
_SAFETY_REASONS = frozenset({"SAFETY", "PROHIBITED_CONTENT", "RECITATION", "BLOCKLIST"})
_AUTH_STATUSES = frozenset({"UNAUTHENTICATED", "PERMISSION_DENIED"})
_INVALID_CONFIG_STATUSES = frozenset({"INVALID_ARGUMENT", "FAILED_PRECONDITION", "OUT_OF_RANGE"})
_NOT_FOUND_STATUSES = frozenset({"NOT_FOUND"})
_QUOTA_STATUSES = frozenset({"RESOURCE_EXHAUSTED"})
_TIMEOUT_STATUSES = frozenset({"DEADLINE_EXCEEDED"})
_TRANSIENT_STATUSES = frozenset({"UNAVAILABLE", "INTERNAL", "ABORTED", "UNKNOWN"})

_AUTH_CODES = frozenset({401, 403})
_INVALID_CONFIG_CODES = frozenset({400, 422})
_NOT_FOUND_CODES = frozenset({404})
_QUOTA_CODES = frozenset({429})
_TIMEOUT_CODES = frozenset({408, 504})


def _extract_structured_reason(details: Any) -> Optional[str]:
    """Pulls a structured ``reason`` value out of a google-genai error body.

    Looks only at well-known structured shapes: a top-level ``reason`` key,
    or an ``ErrorInfo``-style ``details: [{"reason": ...}, ...]`` list
    (``google.rpc.ErrorInfo`` convention). Never inspects free-text message
    content — that is the substring-inference bug this taxonomy replaces.

    Args:
        details: The raw (possibly nested) response JSON/dict from the SDK.

    Returns:
        The structured reason string if present, else ``None``.
    """
    if not isinstance(details, dict):
        return None
    reason = details.get("reason")
    if isinstance(reason, str):
        return reason
    error_body = details.get("error")
    if isinstance(error_body, dict):
        nested_reason = error_body.get("reason")
        if isinstance(nested_reason, str):
            return nested_reason
        for entry in error_body.get("details", []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("reason"), str):
                return entry["reason"]
    for entry in details.get("details", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str):
            return entry["reason"]
    return None


def _classify_status_and_code(
    status: Optional[str], code: Optional[int], reason: Optional[str]
) -> tuple[ReelErrorCode, bool]:
    """Maps structured status/code/reason to a (code, retryable) pair."""
    if reason is not None and reason.upper() in _SAFETY_REASONS:
        return ReelErrorCode.SAFETY_BLOCKED, False

    normalized_status = status.upper() if isinstance(status, str) else None

    if normalized_status in _AUTH_STATUSES or code in _AUTH_CODES:
        return ReelErrorCode.AUTH_OR_ACCESS, False
    if normalized_status in _NOT_FOUND_STATUSES or code in _NOT_FOUND_CODES:
        return ReelErrorCode.UNKNOWN_MODEL, False
    if normalized_status in _QUOTA_STATUSES or code in _QUOTA_CODES:
        return ReelErrorCode.QUOTA_OR_RATE_LIMIT, True
    if normalized_status in _TIMEOUT_STATUSES or code in _TIMEOUT_CODES:
        return ReelErrorCode.TIMEOUT, True
    if normalized_status in _INVALID_CONFIG_STATUSES or code in _INVALID_CONFIG_CODES:
        return ReelErrorCode.INVALID_CONFIGURATION, False
    if normalized_status in _TRANSIENT_STATUSES or (isinstance(code, int) and code >= 500):
        return ReelErrorCode.PROVIDER_FAILURE, True

    return ReelErrorCode.PROVIDER_FAILURE, False


def classify_provider_error(
    exc: BaseException,
    *,
    stage: str,
    scene_index: Optional[int] = None,
) -> ReelError:
    """Maps a provider or local failure to a structured, stable-coded ``ReelError``.

    Classifies ``google.genai.errors.APIError`` (including ``ClientError``/
    ``ServerError``) using structured ``status``/reason fields, plus the
    local normalization types defined in this module for terminal operation
    errors (:class:`OperationFailure`), filtered/empty output
    (:class:`FilteredOutputError`), download failures
    (:class:`DownloadFailure`) and local media failures
    (:class:`MediaValidationFailure`). Safety, auth and invalid-configuration
    failures are always terminal (``retryable=False``).

    ``asyncio.CancelledError`` is always re-raised unchanged so cooperative
    cancellation is never swallowed or reclassified.

    Args:
        exc: The exception to classify.
        stage: Pipeline stage the exception occurred in (e.g. ``"veo_submit"``).
        scene_index: Original scene index, if the failure is scene-scoped.

    Returns:
        A :class:`ReelError` with a stable code, redacted message and
        retryable flag.

    Raises:
        asyncio.CancelledError: Re-raised unchanged, never classified.
    """
    if isinstance(exc, asyncio.CancelledError):
        raise exc

    if isinstance(exc, ReelError):
        return exc

    if genai_errors is not None and isinstance(exc, genai_errors.APIError):
        details = getattr(exc, "details", None)
        reason = _extract_structured_reason(details)
        status = getattr(exc, "status", None)
        code = getattr(exc, "code", None)
        error_code, retryable = _classify_status_and_code(status, code, reason)
        message = f"{stage}: provider error {code} {status}: {getattr(exc, 'message', None) or exc}"
        return ReelError(
            error_code,
            message,
            stage=stage,
            scene_index=scene_index,
            retryable=retryable,
            operation_id=None,
        )

    if isinstance(exc, OperationFailure):
        code = exc.code
        int_code = code if isinstance(code, int) else None
        status = code if isinstance(code, str) else None
        error_code, retryable = _classify_status_and_code(status, int_code, None)
        return ReelError(
            error_code,
            f"{stage}: operation failed ({code}): {exc}",
            stage=stage,
            scene_index=scene_index,
            retryable=retryable,
            operation_id=exc.operation_id,
        )

    if isinstance(exc, FilteredOutputError):
        reason = exc.reason.upper() if isinstance(exc.reason, str) else None
        if reason in _SAFETY_REASONS:
            error_code = ReelErrorCode.SAFETY_BLOCKED
        else:
            error_code = ReelErrorCode.PROVIDER_FAILURE
        return ReelError(
            error_code,
            f"{stage}: filtered/empty output: {exc}",
            stage=stage,
            scene_index=scene_index,
            retryable=False,
            operation_id=exc.operation_id,
        )

    if isinstance(exc, DownloadFailure):
        return ReelError(
            ReelErrorCode.DOWNLOAD_FAILED,
            f"{stage}: download failed: {exc}",
            stage=stage,
            scene_index=scene_index,
            retryable=True,
            operation_id=None,
        )

    if isinstance(exc, MediaValidationFailure):
        return ReelError(
            ReelErrorCode.MEDIA_INVALID,
            f"{stage}: media invalid: {exc}",
            stage=stage,
            scene_index=scene_index,
            retryable=False,
            operation_id=None,
        )

    return ReelError(
        ReelErrorCode.PROVIDER_FAILURE,
        f"{stage}: unclassified failure ({type(exc).__name__}): {exc}",
        stage=stage,
        scene_index=scene_index,
        retryable=False,
        operation_id=None,
    )


_BEARER_TOKEN_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_.]+", re.IGNORECASE)
_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{35}")
_KEY_VALUE_RE = re.compile(r"(?i)\b(api[_-]?key|token|secret|authorization)\b\s*[=:]\s*[^\s&,;'\"]+")
_BASE64_BLOB_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")


def _redact(text: str) -> str:
    """Strips credential-shaped and base64-shaped substrings from a message.

    Args:
        text: The raw message to sanitize before it is stored on a
            :class:`ReelError` (which may end up in logs or ``ReelSceneResult``).

    Returns:
        The message with bearer tokens, Google API keys, ``key=value``
        credential pairs and long base64-looking blobs replaced by
        ``[REDACTED]`` markers.
    """
    redacted = _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", text)
    redacted = _GOOGLE_API_KEY_RE.sub("[REDACTED_KEY]", redacted)
    redacted = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
    redacted = _BASE64_BLOB_RE.sub("[REDACTED_BASE64]", redacted)
    return redacted
