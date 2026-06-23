"""Utilities for redacting secrets before data leaves trusted process memory.

Provides both legacy flat-marker helpers (``redact_text`` / ``redact_secrets``)
for backward compatibility and the policy-driven ``OutputScrubber`` introduced
in FEAT-252 (TASK-1612).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, FrozenSet, Optional

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


# =============================================================================
# FEAT-252 (TASK-1612) — policy-driven OutputScrubber
# =============================================================================

# Reason tags (spec §5.2 taxonomy)
_REASON_ENV_DUMP = "env_dump"
_REASON_SECRET_KV = "secret_kv"
_REASON_DSN = "dsn"
_REASON_JWT = "jwt"
_REASON_CLOUD_KEY = "cloud_key"
_REASON_NET_TOPOLOGY = "net_topology"

# Compiled patterns per reason tag
_ENV_DUMP_RE = re.compile(
    r"(?i)KeysView\s*\(\s*environ\s*\("
    r"|environ\s*\(\s*\{"
    r"|os\.environ"
    r"|dict\s*\(\s*os\.environ"
)
_DSN_RE = re.compile(
    r"(?i)(?:postgres(?:ql)?|mysql|mongodb|redis|amqp|mssql|oracle)://"
    r"[^:@\s]+:[^@\s]+@[^\s/]+"
)
_NET_TOPOLOGY_RE = re.compile(
    r"(?i)(?:internal[-_]host|internal[-_]ip|vpc[-_]cidr|subnet[-_]id)"
    r"\s*[:=]\s*[^\s,;\"']{4,}"
)

_REASON_TAG_MAP: list[tuple[str, re.Pattern]] = [
    (_REASON_ENV_DUMP, _ENV_DUMP_RE),
    (_REASON_DSN, _DSN_RE),
    (_REASON_JWT, _JWT_RE),
    (_REASON_CLOUD_KEY, _AWS_ACCESS_KEY_RE),
    (_REASON_NET_TOPOLOGY, _NET_TOPOLOGY_RE),
]

# Already-scrubbed guards (idempotency)
_SCRUBBED_GUARDS = re.compile(
    r"\*\*\*REDACTED:[a-z_]+\*\*\*"
    r"|\[REDACTED\]"
)


def _already_scrubbed(text: str) -> bool:
    """Return True if the string contains any redaction marker."""
    return bool(_SCRUBBED_GUARDS.search(text))


@dataclass(frozen=True)
class ScrubPolicy:
    """Policy controlling OutputScrubber behaviour.

    Attributes:
        reason_tags: Emit reason-tagged markers (``***REDACTED:<reason>***``)
            instead of the plain ``[REDACTED]`` sentinel.
        audit_log: Record matched tag + tool name (never the secret value)
            via ``logging.getLogger(__name__)``.
        allowlist: Context allowlist — strings matching any of these exact
            substrings are left un-scrubbed (e.g. a ticket body containing
            the literal text ``token=`` as documentation).
        max_output_bytes: Inputs larger than this are scrubbed wholesale rather
            than per-pattern (defence-in-depth for giant blobs).
    """

    reason_tags: bool = True
    audit_log: bool = True
    allowlist: FrozenSet[str] = field(default_factory=frozenset)
    max_output_bytes: int = 1_048_576  # 1 MiB


class OutputScrubber:
    """Policy-driven output scrubber for tool results and egress text.

    Wraps the existing ``redact_text``/``redact_secrets`` logic and adds:
    - Reason-tagged redaction markers (``***REDACTED:env_dump***``, …).
    - Idempotency: re-scrubbing an already-scrubbed value is a no-op.
    - Audit logging: tag + tool name only — the secret value is never logged.
    - Allowlist awareness: callers can exempt known-safe substrings.
    - Recursive structure traversal (dict / list / tuple / str).

    Example:
        >>> scrubber = OutputScrubber(ScrubPolicy())
        >>> scrubber.scrub("PASSWORD=hunter2")
        '***REDACTED:secret_kv***'
        >>> scrubber.scrub({"token": "abc", "ok": "plain"})
        {'token': '***REDACTED:secret_kv***', 'ok': 'plain'}
    """

    def __init__(
        self,
        policy: Optional[ScrubPolicy] = None,
        tool_name: str = "unknown",
    ) -> None:
        """Initialise the scrubber.

        Args:
            policy: The scrub policy to apply. Defaults to ``ScrubPolicy()``.
            tool_name: Hint used in audit logs. Can be updated per-call via
                ``scrub(value, tool_name=...)``.
        """
        self.policy = policy if policy is not None else ScrubPolicy()
        self.tool_name = tool_name
        self.logger = logging.getLogger(__name__)

    def scrub(self, value: Any, tool_name: Optional[str] = None) -> Any:
        """Recursively scrub *value*, returning a sanitised copy.

        The operation is idempotent: ``scrub(scrub(x)) == scrub(x)``.

        Args:
            value: The value to scrub (str, dict, list, tuple, or other).
            tool_name: Override the instance-level ``tool_name`` for this call.

        Returns:
            Sanitised copy.  Non-string/collection scalars are returned as-is.
        """
        _tool = tool_name or self.tool_name
        return self._scrub_value(value, _tool)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrub_value(self, value: Any, tool_name: str) -> Any:
        """Dispatch scrubbing based on value type."""
        if isinstance(value, str):
            return self._scrub_str(value, tool_name)
        if isinstance(value, dict):
            return {
                k: (
                    self._emit_tag(_REASON_SECRET_KV, tool_name)
                    if looks_sensitive_key(k)
                    else self._scrub_value(v, tool_name)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self._scrub_value(item, tool_name) for item in value]
        if isinstance(value, tuple):
            return tuple(self._scrub_value(item, tool_name) for item in value)
        return value

    def _scrub_str(self, text: str, tool_name: str) -> str:
        """Scrub a single string value.

        Idempotency guard: if the string already contains a redaction marker
        produced by this scrubber or the legacy helpers, skip re-scrubbing.
        """
        # Idempotency: already scrubbed
        if _already_scrubbed(text):
            return text

        # Allowlist check: if any allowlisted substring appears, skip
        for allowed in self.policy.allowlist:
            if allowed in text:
                return text

        # Max-output-bytes guard: scrub the whole thing if too large
        if len(text.encode("utf-8", errors="replace")) > self.policy.max_output_bytes:
            self._audit(_REASON_ENV_DUMP, tool_name)
            return self._emit_tag(_REASON_ENV_DUMP, tool_name)

        result = text

        # Reason-tagged passes (ordered: env_dump, dsn, jwt, cloud_key, net_topology)
        for reason, pattern in _REASON_TAG_MAP:
            if pattern.search(result):
                self._audit(reason, tool_name)
                result = pattern.sub(self._emit_tag(reason, tool_name), result)

        # Secret key=value / Bearer / long-hex pass (secret_kv reason tag)
        for compiled_pattern, sub_fn in self._legacy_patterns(tool_name):
            result = compiled_pattern.sub(sub_fn, result)

        return result

    def _legacy_patterns(self, tool_name: str):
        """Yield (compiled_pattern, substitution_fn) for secret_kv patterns.

        Order matters: Bearer/Basic must be replaced before ASSIGNMENT_RE so
        that ``Authorization: Bearer <token>`` is not partially matched by the
        key=value pattern (which would redact only ``Bearer``, leaving the
        token value exposed).
        """
        tag = self._emit_tag(_REASON_SECRET_KV, tool_name)

        def _kv_sub(m):
            self._audit(_REASON_SECRET_KV, tool_name)
            return m.group(1) + m.group(2) + tag + m.group(4)

        def _bearer_sub(m):
            self._audit(_REASON_SECRET_KV, tool_name)
            return f"{m.group(1)} {tag}"

        # Bearer/Basic first to avoid partial match by key=value patterns
        yield _BEARER_RE, _bearer_sub
        yield _DICT_ITEM_RE, _kv_sub
        yield _ASSIGNMENT_RE, _kv_sub

    def _emit_tag(self, reason: str, tool_name: str) -> str:  # noqa: ARG002
        """Return the redaction marker string for a given reason tag."""
        if self.policy.reason_tags:
            return f"***REDACTED:{reason}***"
        return REDACTION_MARKER

    def _audit(self, reason: str, tool_name: str) -> None:
        """Log the tag + tool name (never the secret value)."""
        if self.policy.audit_log:
            self.logger.warning(
                "OutputScrubber: redacted reason=%s tool=%s",
                reason,
                tool_name,
            )
