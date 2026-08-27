"""Pure-unit tests for document_key() (FEAT-465, TASK-2501).

No ArangoDB server or asyncdb mock required — document_key() is a plain
synchronous function with no I/O.
"""

import hashlib

import pytest

from parrot.knowledge.wiki.arango_store import _KEY_MAX_BYTES, document_key


class TestDocumentKeyShortIdentity:
    """Branch 1: identity that fits within _KEY_MAX_BYTES after encoding."""

    def test_short_identity_returned_as_is(self):
        key = document_key("my-concept")
        assert key == "my-concept"

    def test_short_identity_with_spaces_percent_encoded(self):
        key = document_key("hello world")
        assert " " not in key
        assert len(key.encode("utf-8")) <= _KEY_MAX_BYTES


class TestDocumentKeyLongIdentity:
    """Branch 2: identity that exceeds _KEY_MAX_BYTES — SHA-256 digest path."""

    def _long_id(self, length: int = 300) -> str:
        return "a" * length

    def test_long_identity_produces_key(self):
        key = document_key(self._long_id())
        assert key  # non-empty

    def test_long_identity_key_within_byte_limit(self):
        key = document_key(self._long_id())
        assert len(key.encode("utf-8")) <= _KEY_MAX_BYTES

    def test_long_identity_contains_digest_separator(self):
        key = document_key(self._long_id())
        assert "$" in key, "Expected digest separator '$' in long-key output"

    def test_long_identity_digest_is_16_hex_chars(self):
        key = document_key(self._long_id())
        digest_part = key.rsplit("$", 1)[-1]
        assert len(digest_part) == 16, f"Expected 16-char digest, got {len(digest_part)!r}"
        assert all(c in "0123456789abcdef" for c in digest_part), (
            f"Digest {digest_part!r} is not lowercase hex"
        )

    def test_document_key_long_identity_uses_sha256(self):
        """Long identity falls back to truncated-with-digest form; digest is SHA-256.

        Regression test for FEAT-465 / GHCS alert 212: ensures that the
        digest is derived from SHA-256, not the previously-used SHA-1.
        """
        long_id = self._long_id()
        key = document_key(long_id)

        assert "$" in key, "Expected digest separator '$' in long-key output"
        digest_part = key.rsplit("$", 1)[-1]
        assert len(digest_part) == 16, f"Expected 16-char digest, got {len(digest_part)}"

        expected_sha256_prefix = hashlib.sha256(long_id.encode()).hexdigest()[:16]
        expected_sha1_prefix = hashlib.sha1(long_id.encode()).hexdigest()[:16]  # noqa: S324

        assert digest_part == expected_sha256_prefix, (
            f"Digest {digest_part!r} does not match SHA-256 prefix "
            f"{expected_sha256_prefix!r}; SHA-1 prefix would be {expected_sha1_prefix!r}"
        )
        # Sanity: SHA-1 and SHA-256 prefixes differ for this input so the
        # test actually discriminates between the two algorithms.
        assert expected_sha256_prefix != expected_sha1_prefix, (
            "SHA-256 and SHA-1 prefixes happen to collide for this input — "
            "choose a different test string"
        )
