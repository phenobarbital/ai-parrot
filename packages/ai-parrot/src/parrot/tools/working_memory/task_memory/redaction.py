"""Secret redaction and payload bounding for the journal (FEAT-538).

Stage 0 normalization is **not** a secret-redaction policy. That is the
whole reason this module exists: ``normalize_invocation`` canonicalizes
JSON, normalizes text and condenses tracebacks, and it contains no
credential redactor at all. Anything heading for the journal, the
omission store, an archive or a cache key goes through Stage 0 *first*
and then through here.

The ordering matters and is not interchangeable. Normalizing after
redacting would re-expand structures the redactor had already collapsed;
redacting after normalizing means the redactor sees one canonical shape
instead of every spelling a tool might have produced.

What this module guarantees about what it emits:

- **No denied key's value survives.** Key matching is case-insensitive
  and punctuation-insensitive, over a *normalized* key name, and it is a
  substring test — ``Authorization``, ``API_KEY``, ``x-api-key`` and
  ``refreshToken`` are all caught.
- **Errors are redacted too.** A traceback is a perfectly good place to
  find ``Authorization: Bearer ...``, so free text is scanned for
  ``<denied-key><separator><value>`` and the value is replaced.
- **Nothing arbitrary is embedded.** Bytes, over-deep structures,
  over-long strings and over-long collections are replaced by bounded
  markers that state what was omitted, rather than being carried into
  the journal.
- **The result always fits and is always valid JSON.** Bounding shrinks
  the *structure* and re-serializes; it never truncates serialized JSON
  text, which would produce a payload that cannot be parsed back.
- **Recalled task data is data, not instructions.** Markers are inert
  bracketed tokens, never imperative sentences a model might follow.

Deliberate over-redaction
-------------------------

Substring matching means ``token_count`` is redacted along with
``token``. That is the intended trade: a hidden integer is an
inconvenience, a leaked credential in an archived journal is an
incident. The bias is documented and tested rather than left to be
discovered.

Known limit of free-text redaction
----------------------------------

:func:`redact_text` targets **structured** credential shapes —
``key: value``, ``key=value``, JSON fragments, HTTP headers and the
``Bearer``-style schemes that prefix them. That is where credentials
actually appear in tool arguments, HTTP errors and tracebacks.

It does **not** catch a credential narrated in free-form English
("the api key was set to: sk-live-..."), because doing so would require
matching a denied name across arbitrary whitespace, which would in turn
match unrelated prose and redact it. No key-name-based redactor can
close that gap, and claiming otherwise would be worse than stating it.

Structured data is unaffected by this limit: :func:`redact_value`
normalizes key names before matching, so a mapping key spelled
``"api key"`` is redacted exactly like ``api_key``. The gap is narration
inside a message body only, and it is pinned by a test so it stays
visible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Mapping, Optional, Sequence, Tuple

import orjson
from parrot.memory.compaction.models import ToolInvocation
from parrot.memory.compaction.normalize import normalize_invocation

from .config import DEFAULT_REDACTED_KEYS, TaskMemoryConfig
from .models import Limits

__all__ = (
    "REDACTED",
    "RedactionPolicy",
    "normalize_key",
    "is_denied_key",
    "redact_value",
    "redact_text",
    "redact_arguments",
    "redact_invocation",
    "bounded_payload",
    "safe_key_component",
)

#: Replacement for a denied key's value. An inert bracketed token, not a
#: sentence — recalled task data is untrusted data, never instructions.
REDACTED: str = "[redacted]"

#: Characters stripped from a key name before matching, so ``api_key``,
#: ``api-key``, ``apiKey`` and ``X-API-KEY`` all normalize alike.
_KEY_NOISE = re.compile(r"[^a-z0-9]+")

#: Authorization schemes that prefix a credential rather than being one.
#: Without these, ``Authorization: Bearer <secret>`` would redact only the
#: word "Bearer" and leave the secret in place.
_AUTH_SCHEMES = r"(?:Bearer|Basic|Token|JWT|Digest|Negotiate)"

# ── Value-shape patterns ──────────────────────────────────────────────
#
# Key-name matching cannot catch a credential that is never labelled — a
# JWT pasted into a message body, an AWS key id in a traceback, a
# connection string with an inline password. These patterns match on the
# *shape of the value* instead, so they work regardless of the key.
#
# The pattern set is adopted from ``parrot.security.redaction``, which
# already hardened them. They are re-declared here rather than imported
# because importing that package pulls in numpy, asyncpg and redis
# (~1s), and this module sits on the journal write path and is
# deliberately leaf-safe. See this task's completion note: consolidating
# the two redactors is a worthwhile follow-up, but it is a cross-cutting
# decision, not one to smuggle in here.

#: A JSON Web Token: three base64url segments starting ``eyJ``.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")

#: An AWS access key id.
_AWS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")

#: A connection string carrying an inline password.
_DSN_RE = re.compile(
    r"(?i)\b(?P<scheme>postgres(?:ql)?|mysql|mongodb|redis|amqp|mssql|oracle)://"
    r"(?P<user>[^:@\s/]+):(?P<password>[^@\s/]+)@"
)

#: A long hex run — a raw key or digest. The 32-character floor is above
#: this feature's own 16-character ``fp_``/``om_`` digests, so artifact
#: fingerprints and omission ids are never mistaken for credentials.
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")

#: A bare auth scheme followed by a credential, with no key name at all.
_BARE_SCHEME_RE = re.compile(rf"(?i)\b({_AUTH_SCHEMES})\s+[A-Za-z0-9._~+/=-]{{8,}}")


def normalize_key(key: Any) -> str:
    """Normalize a mapping key for denied-name matching.

    Args:
        key: Any key, including a non-string one.

    Returns:
        The key lower-cased with punctuation and whitespace removed.
    """
    return _KEY_NOISE.sub("", str(key).lower())


@dataclass(frozen=True)
class RedactionPolicy:
    """Bounds and denied names applied before anything is persisted.

    Attributes:
        denied_keys: Key names whose values are always replaced. Matched
            case- and punctuation-insensitively as substrings of the
            normalized key.
        max_depth: Maximum nesting depth retained. Deeper structures are
            replaced by a marker rather than walked.
        max_string_chars: Maximum characters retained per string.
        max_string_bytes: Maximum UTF-8 bytes retained per string. Both
            bounds apply, because a multibyte string can be short in
            characters and long in bytes.
        max_collection_items: Maximum list/tuple items retained.
        max_mapping_items: Maximum mapping entries retained.
        max_payload_bytes: Serialized UTF-8 ceiling for a whole journal
            payload.
    """

    denied_keys: FrozenSet[str] = DEFAULT_REDACTED_KEYS
    max_depth: int = 6
    max_string_chars: int = 1_000
    max_string_bytes: int = 2_000
    max_collection_items: int = 50
    max_mapping_items: int = 50
    max_payload_bytes: int = Limits.MAX_EVENT_PAYLOAD_BYTES

    #: Normalized denied names, computed once.
    _normalized: Tuple[str, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Precompute the normalized denied-name set."""
        object.__setattr__(
            self,
            "_normalized",
            tuple(sorted({normalize_key(name) for name in self.denied_keys if str(name).strip()})),
        )

    @classmethod
    def from_config(cls, config: TaskMemoryConfig, **overrides: Any) -> "RedactionPolicy":
        """Build a policy from a task-memory configuration.

        Args:
            config: The configuration whose ``redacted_keys`` to adopt.
            **overrides: Bounds to override.

        Returns:
            The policy.
        """
        return cls(denied_keys=frozenset(config.redacted_keys), **overrides)

    @property
    def normalized_denied(self) -> Tuple[str, ...]:
        """The denied names, normalized for matching."""
        return self._normalized


#: The policy used when a caller supplies none.
_DEFAULT_POLICY = RedactionPolicy()


def is_denied_key(key: Any, policy: Optional[RedactionPolicy] = None) -> bool:
    """Whether a key's value must be redacted.

    Args:
        key: The mapping key.
        policy: The policy; the default is used when ``None``.

    Returns:
        ``True`` when the normalized key contains a denied name.
    """
    policy = policy or _DEFAULT_POLICY
    normalized = normalize_key(key)
    if not normalized:
        return False
    return any(denied and denied in normalized for denied in policy.normalized_denied)


def _clip_string(value: str, policy: RedactionPolicy) -> str:
    """Bound a string by both characters and UTF-8 bytes.

    Args:
        value: The string.
        policy: The active policy.

    Returns:
        The original string, or a clipped one carrying a marker that
        states the original length.
    """
    original_chars = len(value)
    clipped = value[: policy.max_string_chars]
    encoded = clipped.encode("utf-8")
    if len(encoded) > policy.max_string_bytes:
        # Slice on a byte boundary, then drop any partial codepoint. This
        # is what keeps multibyte text from producing invalid UTF-8.
        clipped = encoded[: policy.max_string_bytes].decode("utf-8", errors="ignore")
    if len(clipped) == original_chars and len(encoded) <= policy.max_string_bytes:
        return value
    return f"{clipped}[omitted: {original_chars - len(clipped)} more chars]"


def _redact_scalar(value: Any, policy: RedactionPolicy) -> Any:
    """Redact a non-collection value.

    Args:
        value: The value.
        policy: The active policy.

    Returns:
        A JSON-safe, bounded replacement.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        # A string leaf can hold an unlabelled credential just as easily
        # as an error message can, so it gets the same value-shape pass.
        return redact_text(value, policy) or ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        # Never embed raw bytes: they are unbounded, unreadable and a
        # perfectly good place to hide a credential.
        return f"[omitted: {len(bytes(value))} bytes]"
    return _clip_string(repr(value), policy)


def redact_value(value: Any, policy: Optional[RedactionPolicy] = None, *, _depth: int = 0) -> Any:
    """Recursively redact and bound an arbitrary value.

    Args:
        value: The value to sanitize.
        policy: The policy; the default is used when ``None``.
        _depth: Internal recursion depth.

    Returns:
        A JSON-serializable structure with denied values replaced, bytes
        omitted, and depth/size bounds applied.
    """
    policy = policy or _DEFAULT_POLICY

    if _depth >= policy.max_depth:
        if isinstance(value, Mapping):
            return f"[omitted: nested object, {len(value)} keys]"
        if isinstance(value, (list, tuple, set, frozenset)):
            return f"[omitted: nested array, {len(value)} items]"
        return _redact_scalar(value, policy)

    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= policy.max_mapping_items:
                out["[omitted]"] = f"[omitted: {len(value) - policy.max_mapping_items} more keys]"
                break
            # orjson requires string keys, and OPT_NON_STR_KEYS would let
            # {1: x} and {"1": x} collide, so keys are coerced explicitly.
            name = str(key)
            out[name] = REDACTED if is_denied_key(key, policy) else redact_value(item, policy, _depth=_depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        items = [redact_value(item, policy, _depth=_depth + 1) for item in value[: policy.max_collection_items]]
        if len(value) > policy.max_collection_items:
            items.append(f"[omitted: {len(value) - policy.max_collection_items} more items]")
        return items

    if isinstance(value, (set, frozenset)):
        # Sets have no stable order across processes; sort the rendered
        # items so a redacted payload is reproducible.
        rendered = sorted(
            (redact_value(item, policy, _depth=_depth + 1) for item in value),
            key=lambda item: orjson.dumps(item, option=orjson.OPT_SORT_KEYS, default=str),
        )
        extra = len(rendered) - policy.max_collection_items
        rendered = rendered[: policy.max_collection_items]
        if extra > 0:
            rendered.append(f"[omitted: {extra} more items]")
        return rendered

    return _redact_scalar(value, policy)


def _inline_secret_pattern(policy: RedactionPolicy) -> re.Pattern:
    """Build the regex that finds ``<denied-key><sep><value>`` in free text.

    Args:
        policy: The active policy.

    Returns:
        A compiled, case-insensitive pattern.
    """
    if not policy.normalized_denied:
        return re.compile(r"(?!x)x")  # matches nothing

    # Allow the punctuation the key normalizer strips, so the pattern
    # finds ``api_key``, ``api-key``, ``api.key`` and ``apiKey`` alike.
    # Deliberately NOT ``\W`` — that would match across whitespace and
    # let ``t o k e n`` count as a key.
    alternatives = "|".join(
        r"[-_.]*".join(re.escape(char) for char in denied)
        for denied in sorted(policy.normalized_denied, key=len, reverse=True)
    )
    return re.compile(
        rf"""
        (?<![A-Za-z0-9_\-])                    # start at a token boundary
        (?P<key>[A-Za-z0-9_\-]{{0,32}}(?:{alternatives})[A-Za-z0-9_\-]{{0,32}})
        (?P<sep>
            ["']?                               # optional closing quote
            (?:[ \t]+[A-Za-z]+){{0,2}}          # up to two filler words ("... is:")
            [ \t]*[:=][ \t]*                    # then : or =
        )
        (?P<value>
            "(?:[^"\\]|\\.)*"                   # a double-quoted value
          | '(?:[^'\\]|\\.)*'                   # a single-quoted value
          | (?:{_AUTH_SCHEMES}[ \t]+)?          # an optional auth scheme...
            [^\s,;&}}\)\]"']+                   # ...then the credential itself
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )


def redact_text(text: Optional[str], policy: Optional[RedactionPolicy] = None) -> Optional[str]:
    """Redact credentials embedded in free text, then bound its length.

    Used for error messages and condensed tracebacks, which routinely
    carry request headers.

    This scans text for *credential shapes*, which is emphatically not
    the same thing as parsing text to infer an outcome — that remains
    forbidden and lives in :mod:`.adapters`.

    Args:
        text: The text, or ``None``.
        policy: The policy; the default is used when ``None``.

    Returns:
        The redacted, bounded text, or ``None``.
    """
    if text is None:
        return None
    policy = policy or _DEFAULT_POLICY

    # Clip FIRST. Everything past the clip point is discarded outright, so
    # it cannot leak, and bounding the input is what keeps the scan linear
    # in the retained size rather than in the original size.
    text = _clip_string(text, policy)
    pattern = _inline_secret_pattern(policy)

    def _replace(match: "re.Match[str]") -> str:
        value = match.group("value")
        # Keep the quoting shape so a redacted JSON-ish fragment still
        # reads as a quoted value rather than as a dangling quote.
        replacement = f'"{REDACTED}"' if value[:1] in ('"', "'") else REDACTED
        return f"{match.group('key')}{match.group('sep')}{replacement}"

    redacted = pattern.sub(_replace, text)

    # Second pass: credentials that carry no key name at all. A JWT or an
    # AWS key id in a traceback is a leak whatever the surrounding prose
    # says, so these match on the value's shape instead.
    redacted = _JWT_RE.sub(REDACTED, redacted)
    redacted = _AWS_KEY_RE.sub(REDACTED, redacted)
    redacted = _LONG_HEX_RE.sub(REDACTED, redacted)
    redacted = _DSN_RE.sub(rf"\g<scheme>://\g<user>:{REDACTED}@", redacted)
    redacted = _BARE_SCHEME_RE.sub(rf"\1 {REDACTED}", redacted)

    return redacted


def redact_invocation(
    invocation: ToolInvocation,
    policy: Optional[RedactionPolicy] = None,
) -> ToolInvocation:
    """Normalize with Stage 0, then redact, in that order.

    Args:
        invocation: The captured invocation.
        policy: The policy; the default is used when ``None``.

    Returns:
        A new :class:`ToolInvocation` safe to persist. Never mutates the
        input.
    """
    policy = policy or _DEFAULT_POLICY
    normalized = normalize_invocation(invocation)

    return ToolInvocation(
        tool_name=normalized.tool_name,
        input=redact_value(normalized.input, policy),
        output=redact_text(normalized.output, policy),
        status=normalized.status,
        error=redact_text(normalized.error, policy),
        elapsed_ms=normalized.elapsed_ms,
        output_chars=normalized.output_chars,
        omitted=dict(normalized.omitted),
        wm_key=normalized.wm_key,
    )


def _serialized_size(payload: Any) -> int:
    """Return a payload's canonical serialized UTF-8 size.

    Args:
        payload: The payload.

    Returns:
        Its size in bytes.
    """
    return len(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS, default=str))


def bounded_payload(
    payload: Mapping[str, Any],
    policy: Optional[RedactionPolicy] = None,
    *,
    preserve: Sequence[str] = (),
) -> Dict[str, Any]:
    """Redact a payload and shrink it until it fits the byte ceiling.

    Shrinking is **structural**: strings get shorter, collections lose
    items, and finally whole keys are dropped in favour of a marker. The
    serialized JSON text is never truncated, so the result always parses.

    Args:
        payload: The payload mapping.
        policy: The policy; the default is used when ``None``.
        preserve: Keys that must survive shrinking, in priority order.
            Everything else is dropped before these are touched.

    Returns:
        A redacted, bounded, JSON-serializable dictionary.
    """
    policy = policy or _DEFAULT_POLICY
    result = redact_value(dict(payload), policy)
    if _serialized_size(result) <= policy.max_payload_bytes:
        return result

    # 1. Re-redact under progressively tighter string/collection bounds.
    for divisor in (2, 4, 8, 16, 32):
        tighter = RedactionPolicy(
            denied_keys=policy.denied_keys,
            max_depth=max(2, policy.max_depth - 1),
            max_string_chars=max(32, policy.max_string_chars // divisor),
            max_string_bytes=max(64, policy.max_string_bytes // divisor),
            max_collection_items=max(2, policy.max_collection_items // divisor),
            max_mapping_items=max(2, policy.max_mapping_items // divisor),
            max_payload_bytes=policy.max_payload_bytes,
        )
        result = redact_value(dict(payload), tighter)
        if _serialized_size(result) <= policy.max_payload_bytes:
            return result

    # 2. Drop non-preserved keys, largest first, replacing each with a marker.
    preserved = set(preserve)
    droppable = sorted(
        (key for key in result if key not in preserved),
        key=lambda key: _serialized_size(result[key]),
        reverse=True,
    )
    for key in droppable:
        result[key] = "[omitted: payload too large]"
        if _serialized_size(result) <= policy.max_payload_bytes:
            return result

    # 3. Last resort: keep only the preserved keys, then a bare marker.
    minimal: Dict[str, Any] = {key: result[key] for key in preserve if key in result}
    minimal["_omitted"] = "payload exceeded the journal byte limit"
    if _serialized_size(minimal) <= policy.max_payload_bytes:
        return minimal
    return {"_omitted": "payload exceeded the journal byte limit"}


def safe_key_component(text: Any, *, max_chars: int = 64) -> str:
    """Render a value safe to embed in a storage or cache key.

    Storage and cache keys must never contain credentials, and must never
    contain a separator a component value could use to forge another
    key's identity.

    Args:
        text: The component value.
        max_chars: Maximum characters retained.

    Returns:
        A bounded string of ``[a-z0-9_-]`` only. A value whose name or
        content is denied never reaches a key: callers pass the *name*
        through :func:`is_denied_key` first, and this function guarantees
        only that whatever it emits is inert.
    """
    rendered = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(text)).strip("-").lower()
    return rendered[:max_chars] or "_"


def redact_arguments(
    arguments: Mapping[str, Any],
    policy: Optional[RedactionPolicy] = None,
) -> Dict[str, Any]:
    """Redact a tool call's arguments for journal storage.

    A convenience wrapper over :func:`redact_value` that always returns a
    dictionary, so a journal payload's ``input`` field has one shape.

    Args:
        arguments: The call arguments.
        policy: The policy; the default is used when ``None``.

    Returns:
        The redacted arguments.
    """
    redacted = redact_value(dict(arguments), policy)
    return redacted if isinstance(redacted, dict) else {"_value": redacted}
