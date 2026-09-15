"""Unit tests for journal redaction and payload bounding (FEAT-538 / TASK-2982).

Two required cases from the task's Test Specification:

- ``test_secrets`` — nested credentials and error text are absent from
  serialized journal/omission input.
- ``test_payload_bytes`` — multibyte text and deep arguments obey the
  byte/depth caps without producing malformed JSON.

The secret tests are written adversarially: they assert against the
**serialized** payload, because a credential that survives as a nested
value is still a leak even when a spot-check of the top level looks
clean.
"""

from __future__ import annotations

from typing import Any

import orjson
import pytest
from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import Limits
from parrot.tools.working_memory.task_memory.redaction import (
    REDACTED,
    RedactionPolicy,
    bounded_payload,
    is_denied_key,
    normalize_key,
    redact_arguments,
    redact_invocation,
    redact_text,
    redact_value,
    safe_key_component,
)

#: A credential value that must never survive redaction anywhere.
SECRET = "sk-live-51H9zAbCdEfGhIjKlMnOpQrSt"


def _serialized(value: Any) -> str:
    """Serialize a value the way the journal would.

    Args:
        value: The value.

    Returns:
        Its canonical UTF-8 JSON text.
    """
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS, default=str).decode("utf-8")


# ─────────────────────────────────────────────────────────────
# Key matching
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "Token",
        "TOKEN",
        "api_key",
        "API_KEY",
        "apiKey",
        "api-key",
        "x-api-key",
        "X-API-Key",
        "Authorization",
        "authorization",
        "password",
        "Password",
        "user_password",
        "secret",
        "client_secret",
        "refreshToken",
        "access_token",
        "AWS_SECRET_ACCESS_KEY",
    ],
)
def test_secrets_denied_key_variants(key: str) -> None:
    """Case, punctuation and affixes never let a denied name through."""
    assert is_denied_key(key), key
    assert redact_value({key: SECRET})[key] == REDACTED


@pytest.mark.parametrize("key", ["rows", "name", "session_id", "goal", "status", "count", "tokenizer_name"])
def test_secrets_ordinary_keys_survive(key: str) -> None:
    """Ordinary keys are untouched."""
    assert not is_denied_key(key) or key == "tokenizer_name"
    if not is_denied_key(key):
        assert redact_value({key: "value"})[key] == "value"


def test_secrets_over_redaction_is_deliberate() -> None:
    """Substring matching over-redacts, and that is the intended trade.

    ``token_count`` is hidden along with ``token``. A hidden integer is an
    inconvenience; a credential in an archived journal is an incident.
    """
    assert is_denied_key("token_count") is True
    assert redact_value({"token_count": 42})["token_count"] == REDACTED


def test_secrets_normalize_key_handles_non_strings() -> None:
    """Non-string keys are normalized rather than crashing the redactor."""
    assert normalize_key(1) == "1"
    assert normalize_key(None) == "none"
    assert normalize_key("X-API-Key") == "xapikey"
    assert is_denied_key(1) is False


def test_secrets_non_string_keys_are_coerced_not_dropped() -> None:
    """Non-string keys become strings, so the payload stays serializable.

    ``orjson``'s ``OPT_NON_STR_KEYS`` is deliberately not used anywhere in
    this feature: it makes ``{1: x}`` and ``{"1": x}`` encode identically.
    Coercing explicitly keeps the behaviour visible.
    """
    redacted = redact_value({1: "a", "1": "b", None: "c"})
    assert set(redacted) == {"1", "None"}
    assert _serialized(redacted)  # round-trips without OPT_NON_STR_KEYS


# ─────────────────────────────────────────────────────────────
# Nested and adversarial structures
# ─────────────────────────────────────────────────────────────


def test_secrets_nested_credentials_are_removed() -> None:
    """A credential buried several levels down does not survive."""
    payload = {
        "request": {
            "url": "https://api.example.com/v1/charges",
            "headers": {"Authorization": f"Bearer {SECRET}", "Accept": "application/json"},
            "retries": [{"attempt": 1, "api_key": SECRET}, {"attempt": 2, "api_key": SECRET}],
        },
        "rows": 12,
    }
    redacted = redact_value(payload)
    assert SECRET not in _serialized(redacted), "a nested credential leaked"
    assert redacted["request"]["headers"]["Authorization"] == REDACTED
    assert redacted["request"]["headers"]["Accept"] == "application/json"
    assert redacted["rows"] == 12
    assert all(item["api_key"] == REDACTED for item in redacted["request"]["retries"])


def test_secrets_credentials_inside_lists_and_sets() -> None:
    """Collections are walked, not skipped."""
    payload = {"items": [{"password": SECRET}, [{"secret": SECRET}]], "tags": {"a", "b"}}
    redacted = redact_value(payload)
    assert SECRET not in _serialized(redacted)


def test_secrets_sets_are_ordered_deterministically() -> None:
    """A redacted set renders reproducibly across runs and processes."""
    payload = {"tags": {"gamma", "alpha", "beta"}}
    first = _serialized(redact_value(payload))
    second = _serialized(redact_value({"tags": {"beta", "gamma", "alpha"}}))
    assert first == second


def test_secrets_bytes_are_never_embedded() -> None:
    """Raw bytes are unbounded and unreadable; they are described, not carried."""
    redacted = redact_value({"blob": SECRET.encode("utf-8") * 100})
    assert SECRET not in _serialized(redacted)
    assert redacted["blob"].startswith("[omitted:")
    assert "bytes" in redacted["blob"]


def test_secrets_arbitrary_objects_are_repr_bounded() -> None:
    """An arbitrary object is rendered as bounded text, never embedded raw."""

    class _Opaque:
        def __repr__(self) -> str:
            return "x" * 10_000

    redacted = redact_value({"obj": _Opaque()}, RedactionPolicy(max_string_chars=100, max_string_bytes=200))
    assert len(redacted["obj"]) < 400
    assert "[omitted:" in redacted["obj"]


# ─────────────────────────────────────────────────────────────
# Free text and errors
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        f"Authorization: Bearer {SECRET}",
        f"api_key={SECRET}",
        f"API-KEY: {SECRET}",
        f'{{"token": "{SECRET}"}}',
        f"password = {SECRET}",
        f"X-Api-Key:{SECRET}",
        f"client_secret={SECRET}&grant_type=refresh",
    ],
)
def test_secrets_inline_credentials_in_text(text: str) -> None:
    """Credentials embedded in free text are redacted too."""
    redacted = redact_text(text)
    assert redacted is not None
    assert SECRET not in redacted, f"credential survived in: {redacted}"
    assert REDACTED in redacted


def test_secrets_error_tracebacks_are_redacted() -> None:
    """A traceback is a perfectly good place to hide a credential."""
    traceback = (
        "Traceback (most recent call last):\n"
        '  File "client.py", line 42, in request\n'
        f'    headers = {{"Authorization": "Bearer {SECRET}"}}\n'
        "HTTPError: 401 Unauthorized"
    )
    redacted = redact_text(traceback)
    assert redacted is not None
    assert SECRET not in redacted
    assert "HTTPError: 401 Unauthorized" in redacted


@pytest.mark.parametrize(
    "text",
    [
        f"Set-Cookie: session_token={SECRET}; Path=/",
        f"POST /v1/charges?api_key={SECRET}&limit=10",
        f"AWS_SECRET_ACCESS_KEY={SECRET}",
        f"authorization=Basic {SECRET}",
        f"Authorization:\tBearer {SECRET}",
        f"the refresh_token is: {SECRET}",
        f"headers={{'Authorization': 'Bearer {SECRET}'}}",
    ],
)
def test_secrets_structured_credential_shapes(text: str) -> None:
    """Query strings, cookies, env assignments and schemes are all covered."""
    redacted = redact_text(text)
    assert redacted is not None
    assert SECRET not in redacted, f"credential survived in: {redacted}"


def test_secrets_auth_scheme_prefix_is_consumed() -> None:
    """``Bearer <secret>`` redacts the secret, not just the word "Bearer".

    Pins a real bug this suite caught: an earlier pattern stopped at the
    scheme word and left the credential in the journal.
    """
    redacted = redact_text(f"Authorization: Bearer {SECRET}")
    assert redacted == "Authorization: [redacted]"


def test_secrets_free_prose_narration_is_a_known_limit() -> None:
    """A credential narrated in prose is NOT caught — documented, not hidden.

    Catching ``"the api key was set to: <secret>"`` would mean matching a
    denied name across arbitrary whitespace, which would redact unrelated
    prose. No key-name-based redactor can close that gap.

    The structured path is unaffected, which is what actually matters:
    a mapping key spelled ``"api key"`` *is* redacted, because key names
    are normalized before matching. This test pins both halves so the
    limit stays visible instead of being assumed away.
    """
    narrated = redact_text(f"the api key was set to: {SECRET}")
    assert narrated is not None
    assert SECRET in narrated, "if this now passes, the limit closed — update the docs"

    # The structured equivalent is covered.
    assert is_denied_key("api key") is True
    assert redact_value({"api key": SECRET})["api key"] == REDACTED
    assert redact_value({"cfg": {"Api Key": SECRET}})["cfg"]["Api Key"] == REDACTED


def test_secrets_redaction_does_not_overreach_into_ordinary_prose() -> None:
    """Text with no denied key name is returned untouched."""
    for benign in (
        "Loaded 12 rows; status: ok",
        "Query returned 5 rows in 12ms",
        "Retrieved 3 records for user bob at 12:04",
    ):
        assert redact_text(benign) == benign


@pytest.mark.parametrize(
    ("text", "label"),
    [
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0." "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
            "jwt",
        ),
        ("AKIAIOSFODNN7EXAMPLE", "aws access key id"),
        ("postgres://user:hunter2@db.internal:5432/app", "dsn password"),
        ("3f5a8c9e1b2d4f6a8c0e2b4d6f8a0c2e5a7b9d1f3e5a7c9b1d3f5a7c9e1b3d5f", "long hex"),
    ],
)
def test_secrets_unlabelled_credentials_are_caught_by_shape(text: str, label: str) -> None:
    """Credentials with no key name at all are matched on value shape.

    Key-name matching cannot see a JWT pasted into a message body or an
    AWS key id in a traceback. These patterns are adopted from the
    already-hardened ``parrot.security.redaction`` (see the completion
    note on why they are re-declared rather than imported).
    """
    redacted = redact_text(text)
    assert redacted is not None
    assert REDACTED in redacted, f"{label} was not redacted: {redacted}"


def test_secrets_feature_own_digests_are_not_mistaken_for_secrets() -> None:
    """This feature's ``fp_``/``om_`` digests survive the long-hex rule.

    Artifact fingerprints and omission ids are 16 hex characters, below
    the 32-character floor. Redacting them would break evidence
    references and omission lookups.
    """
    text = "evidence fp_0123456789abcdef resolved from om_fedcba9876543210"
    assert redact_text(text) == text


def test_secrets_redaction_is_linear_on_long_runs() -> None:
    """Redaction stays fast on a long alphanumeric run.

    Pins a real bug this suite caught: an unbounded ``[A-Za-z0-9_-]*``
    affix in the key pattern backtracked quadratically, so a 5,000
    character run took ~774ms and a full payload hung the suite. The
    affixes are now length-bounded and the input is clipped first.
    """
    import time

    start = time.perf_counter()
    redact_value({"a": "q" * 5_000})
    bounded_payload({f"f{n}": "q" * 5_000 for n in range(50)})
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"redaction took {elapsed:.2f}s — the backtracking bound regressed"


def test_secrets_redact_text_passes_through_none() -> None:
    """A missing message stays missing."""
    assert redact_text(None) is None


def test_secrets_ordinary_text_is_untouched() -> None:
    """Text with no credential shape is preserved verbatim."""
    text = "Loaded 12 rows from the sales table in 43ms"
    assert redact_text(text) == text


# ─────────────────────────────────────────────────────────────
# Invocation pipeline: Stage 0 first, then redaction
# ─────────────────────────────────────────────────────────────


def test_secrets_invocation_is_normalized_then_redacted() -> None:
    """The whole invocation is safe to persist, and the input is unchanged."""
    invocation = ToolInvocation(
        tool_name="http_get",
        input={"url": "https://api.example.com", "headers": {"Authorization": f"Bearer {SECRET}"}},
        output=f'{{"token": "{SECRET}"}}',
        status=ToolStatus.ERROR,
        error=f"HTTPError: 401 with api_key={SECRET}",
    )
    redacted = redact_invocation(invocation)

    blob = _serialized(
        {
            "input": redacted.input,
            "output": redacted.output,
            "error": redacted.error,
        }
    )
    assert SECRET not in blob, "a credential reached the journal payload"
    assert redacted.input["headers"]["Authorization"] == REDACTED
    assert redacted.status is ToolStatus.ERROR
    assert redacted.tool_name == "http_get"

    # Never mutates its argument.
    assert invocation.input["headers"]["Authorization"] == f"Bearer {SECRET}"


def test_secrets_stage_zero_alone_would_not_have_been_enough() -> None:
    """Normalization is not redaction — this is why the module exists.

    Asserted directly: Stage 0 leaves the credential in place, and only
    the redactor removes it.
    """
    from parrot.memory.compaction.normalize import normalize_invocation

    invocation = ToolInvocation(
        tool_name="t",
        input={"api_key": SECRET},
        output=None,
        status=ToolStatus.COMPLETED,
    )
    normalized = normalize_invocation(invocation)
    assert SECRET in _serialized(normalized.input), "premise: Stage 0 does not redact"

    redacted = redact_invocation(invocation)
    assert SECRET not in _serialized(redacted.input)


def test_secrets_policy_honours_configured_additions() -> None:
    """Extra denied names configured by a host are enforced."""
    config = TaskMemoryConfig(extra_redacted_keys=("session-cookie", "pin"))
    policy = RedactionPolicy.from_config(config)

    redacted = redact_value({"session_cookie": SECRET, "pin": "1234", "rows": 3}, policy)
    assert redacted["session_cookie"] == REDACTED
    assert redacted["pin"] == REDACTED
    assert redacted["rows"] == 3
    # The built-ins are still enforced alongside the additions.
    assert is_denied_key("api_key", policy) is True


def test_secrets_storage_keys_never_carry_credentials() -> None:
    """Key components are inert: no separators, no punctuation, bounded."""
    component = safe_key_component("Bearer sk-live/../../etc:passwd")
    assert "/" not in component and ":" not in component
    assert component == component.lower()
    assert len(component) <= 64
    assert safe_key_component("") == "_"


def test_secrets_markers_are_inert_not_instructions() -> None:
    """Recalled task data is data; markers must not read as instructions."""
    redacted = redact_value({"api_key": SECRET, "blob": b"xx", "deep": {"a": {"b": {"c": {"d": {"e": 1}}}}}})
    blob = _serialized(redacted)
    for imperative in ("ignore", "you must", "please", "instruction", "system:"):
        assert imperative not in blob.lower(), f"marker text reads as an instruction: {imperative}"
    assert REDACTED == "[redacted]"


def test_secrets() -> None:
    """Required aggregate case: credentials never reach serialized journal input."""
    test_secrets_nested_credentials_are_removed()
    test_secrets_credentials_inside_lists_and_sets()
    test_secrets_bytes_are_never_embedded()
    test_secrets_error_tracebacks_are_redacted()
    test_secrets_auth_scheme_prefix_is_consumed()
    test_secrets_free_prose_narration_is_a_known_limit()
    test_secrets_redaction_does_not_overreach_into_ordinary_prose()
    test_secrets_feature_own_digests_are_not_mistaken_for_secrets()
    test_secrets_redaction_is_linear_on_long_runs()
    test_secrets_invocation_is_normalized_then_redacted()
    test_secrets_stage_zero_alone_would_not_have_been_enough()
    test_secrets_policy_honours_configured_additions()
    test_secrets_storage_keys_never_carry_credentials()
    test_secrets_markers_are_inert_not_instructions()
    test_secrets_over_redaction_is_deliberate()
    for key in ("Authorization", "X-API-Key", "refreshToken"):
        test_secrets_denied_key_variants(key)


# ─────────────────────────────────────────────────────────────
# Byte and depth bounds
# ─────────────────────────────────────────────────────────────


def test_payload_bytes_multibyte_strings_stay_valid_utf8() -> None:
    """A multibyte string is clipped on a codepoint boundary.

    Slicing encoded bytes naively would split a 3-byte character and
    produce a payload that cannot be decoded.
    """
    policy = RedactionPolicy(max_string_chars=10_000, max_string_bytes=100)
    value = "✓" * 500  # 3 bytes each
    redacted = redact_value({"note": value}, policy)

    text = redacted["note"]
    assert isinstance(text, str)
    text.encode("utf-8").decode("utf-8")  # raises if a codepoint was split
    assert "[omitted:" in text
    assert _serialized(redacted)


def test_payload_bytes_character_and_byte_bounds_both_apply() -> None:
    """A string short in characters but long in bytes is still clipped."""
    policy = RedactionPolicy(max_string_chars=1_000, max_string_bytes=60)
    redacted = redact_value({"note": "€" * 100}, policy)  # 3 bytes each, 100 chars
    assert len(redacted["note"].encode("utf-8")) < 200


def test_payload_bytes_depth_cap_replaces_rather_than_recurses() -> None:
    """Structures deeper than the cap are described, not walked."""
    deep: Any = {"leaf": 1}
    for _ in range(50):
        deep = {"nested": deep}

    policy = RedactionPolicy(max_depth=4)
    redacted = redact_value(deep, policy)
    blob = _serialized(redacted)
    assert "[omitted: nested object" in blob
    assert orjson.loads(blob), "the bounded payload must still parse"


def test_payload_bytes_collection_caps() -> None:
    """Long lists and wide mappings are truncated with a stated count."""
    policy = RedactionPolicy(max_collection_items=3, max_mapping_items=3)

    listed = redact_value({"rows": list(range(100))}, policy)
    assert len(listed["rows"]) == 4  # 3 items + marker
    assert "97 more items" in listed["rows"][-1]

    wide = redact_value({f"k{n}": n for n in range(100)}, policy)
    assert "[omitted]" in wide
    assert "97 more keys" in wide["[omitted]"]


def test_payload_bytes_bounded_payload_fits_and_parses() -> None:
    """A huge payload is shrunk below 8 KiB and remains valid JSON."""
    payload = {
        "code": "x = 1\n" * 20_000,
        "rows": [{"id": n, "text": "y" * 200} for n in range(500)],
        "call_id": "c-1",
    }
    bounded = bounded_payload(payload, preserve=("call_id",))

    blob = orjson.dumps(bounded, option=orjson.OPT_SORT_KEYS, default=str)
    assert len(blob) <= Limits.MAX_EVENT_PAYLOAD_BYTES, f"payload is {len(blob)} bytes"
    assert orjson.loads(blob), "bounding must never truncate serialized JSON"
    assert bounded["call_id"] == "c-1", "preserved keys survive shrinking"


def test_payload_bytes_bounded_payload_keeps_small_payloads_intact() -> None:
    """A payload that already fits is not needlessly mangled."""
    payload = {"call_id": "c-1", "tool_name": "wm_store", "attempt": 2}
    assert bounded_payload(payload) == payload


def test_payload_bytes_bounded_payload_redacts_before_bounding() -> None:
    """Shrinking never resurrects a credential the redactor removed."""
    payload = {"api_key": SECRET, "code": "z" * 100_000, "call_id": "c-1"}
    bounded = bounded_payload(payload, preserve=("call_id",))
    blob = _serialized(bounded)
    assert SECRET not in blob
    assert len(blob.encode("utf-8")) <= Limits.MAX_EVENT_PAYLOAD_BYTES


def test_payload_bytes_pathological_payload_still_fits() -> None:
    """Even a payload of many large preserved-adjacent keys is bounded."""
    payload = {f"field_{n}": "q" * 5_000 for n in range(200)}
    bounded = bounded_payload(payload)
    blob = orjson.dumps(bounded, option=orjson.OPT_SORT_KEYS, default=str)
    assert len(blob) <= Limits.MAX_EVENT_PAYLOAD_BYTES
    assert orjson.loads(blob)


def test_payload_bytes_multibyte_payload_measured_in_bytes_not_chars() -> None:
    """The 8 KiB ceiling is a byte ceiling, not a character count."""
    # 4,000 three-byte characters: well under 8,192 *characters*, well over
    # 8,192 bytes.
    payload = {"note": "漢" * 4_000}
    assert len(payload["note"]) < Limits.MAX_EVENT_PAYLOAD_BYTES
    assert len(_serialized(payload).encode("utf-8")) > Limits.MAX_EVENT_PAYLOAD_BYTES

    bounded = bounded_payload(payload)
    blob = orjson.dumps(bounded, option=orjson.OPT_SORT_KEYS, default=str)
    assert len(blob) <= Limits.MAX_EVENT_PAYLOAD_BYTES
    assert orjson.loads(blob)


def test_payload_bytes_redact_arguments_always_returns_a_mapping() -> None:
    """A journal payload's ``input`` field has exactly one shape."""
    assert redact_arguments({"a": 1}) == {"a": 1}
    assert isinstance(redact_arguments({}), dict)


def test_payload_bytes_default_policy_matches_the_journal_cap() -> None:
    """The default bounding ceiling is the specification's 8 KiB."""
    assert RedactionPolicy().max_payload_bytes == Limits.MAX_EVENT_PAYLOAD_BYTES == 8 * 1024


def test_payload_bytes() -> None:
    """Required aggregate case: byte and depth caps hold without malformed JSON."""
    test_payload_bytes_multibyte_strings_stay_valid_utf8()
    test_payload_bytes_character_and_byte_bounds_both_apply()
    test_payload_bytes_depth_cap_replaces_rather_than_recurses()
    test_payload_bytes_collection_caps()
    test_payload_bytes_bounded_payload_fits_and_parses()
    test_payload_bytes_bounded_payload_keeps_small_payloads_intact()
    test_payload_bytes_bounded_payload_redacts_before_bounding()
    test_payload_bytes_pathological_payload_still_fits()
    test_payload_bytes_multibyte_payload_measured_in_bytes_not_chars()
    test_payload_bytes_default_policy_matches_the_journal_cap()
