"""Utilities for redacting secrets before data leaves trusted process memory."""

from __future__ import annotations

import re
from typing import Any

REDACTION_MARKER = "[REDACTED]"

_SECRET_KEY_RE = re.compile(
    r"(?i)\b("
    r"api[_-]?key|token|secret|password|passwd|pwd|credential|credentials|"
    r"private[_-]?key|client[_-]?secret|access[_-]?key|refresh[_-]?token|"
    r"session[_-]?id|cookie|authorization"
    r")\b"
)

_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|"
    r"CREDENTIALS?|PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|ACCESS[_-]?KEY|"
    r"REFRESH[_-]?TOKEN|COOKIE|AUTHORIZATION)[A-Z0-9_]*\b\s*[:=]\s*)"
    r"(['\"]?)([^,'\"\s})\]]{4,})(['\"]?)"
)

_DICT_ITEM_RE = re.compile(
    r"(?i)(['\"]?[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|"
    r"CREDENTIALS?|PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|ACCESS[_-]?KEY|"
    r"REFRESH[_-]?TOKEN|COOKIE|AUTHORIZATION)[A-Z0-9_]*['\"]?\s*:\s*)"
    r"(['\"])(.*?)(['\"])(?=\s*[,}])"
)

_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")


def looks_sensitive_key(key: Any) -> bool:
    """Return True when a mapping key/name likely denotes a secret."""
    return bool(_SECRET_KEY_RE.search(str(key)))


def redact_text(text: str) -> str:
    """Redact common secret assignments and token-like values in text."""
    redacted = _DICT_ITEM_RE.sub(rf"\1\2{REDACTION_MARKER}\4", text)
    redacted = _ASSIGNMENT_RE.sub(rf"\1\2{REDACTION_MARKER}\4", redacted)
    redacted = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTION_MARKER}", redacted)
    redacted = _JWT_RE.sub(REDACTION_MARKER, redacted)
    redacted = _AWS_ACCESS_KEY_RE.sub(REDACTION_MARKER, redacted)
    redacted = _LONG_HEX_RE.sub(REDACTION_MARKER, redacted)
    return redacted


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-like values from JSON-ish structures."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if looks_sensitive_key(key):
                result[key] = REDACTION_MARKER
            else:
                result[key] = redact_secrets(item)
        return result
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value
