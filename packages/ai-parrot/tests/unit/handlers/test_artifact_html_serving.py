"""Unit tests for ArtifactPublicHTMLView signing logic (FEAT-197, TASK-1322).

These tests exercise the signature verification helpers directly, without
spinning up a full HTTP server.
"""
from __future__ import annotations

import sys
import time
import pytest

# Force real handlers module.
sys.modules.pop("parrot.handlers.artifacts", None)
sys.modules.pop("parrot.handlers.csp", None)

import parrot.handlers.csp as _real_csp
sys.modules["parrot.handlers.csp"] = _real_csp

import parrot.handlers.artifacts as _real_artifacts
sys.modules["parrot.handlers.artifacts"] = _real_artifacts

from parrot.handlers.artifacts import _sign_artifact, _verify_artifact_signature  # noqa: E402


_TEST_KEY = b"test-signing-key-for-unit-tests"


class TestSignAndVerify:
    """Direct unit tests for the signing / verification helpers."""

    def test_valid_signature_accepted(self):
        """A freshly-signed artifact_id should verify successfully."""
        expiry = int(time.time()) + 600
        sig = _sign_artifact("art-1", expiry, _TEST_KEY)
        assert _verify_artifact_signature("art-1", f"{expiry}.{sig}", _TEST_KEY)

    def test_expired_signature_rejected(self):
        """An expired signature (past expiry) should be rejected."""
        expiry = int(time.time()) - 1  # already past
        sig = _sign_artifact("art-1", expiry, _TEST_KEY)
        assert not _verify_artifact_signature("art-1", f"{expiry}.{sig}", _TEST_KEY)

    def test_tampered_sig_rejected(self):
        """A tampered sig string should fail."""
        expiry = int(time.time()) + 600
        assert not _verify_artifact_signature("art-1", f"{expiry}.deadbeef", _TEST_KEY)

    def test_wrong_artifact_id_rejected(self):
        """Signature for art-1 should not verify for art-2."""
        expiry = int(time.time()) + 600
        sig = _sign_artifact("art-1", expiry, _TEST_KEY)
        assert not _verify_artifact_signature("art-2", f"{expiry}.{sig}", _TEST_KEY)

    def test_malformed_signature_segment_rejected(self):
        """Completely malformed segment should be rejected without exception."""
        assert not _verify_artifact_signature("art-1", "not-a-valid-segment", _TEST_KEY)

    def test_different_keys_produce_different_sigs(self):
        """Different signing keys should produce different signatures."""
        expiry = int(time.time()) + 600
        sig1 = _sign_artifact("art-1", expiry, b"key-A")
        sig2 = _sign_artifact("art-1", expiry, b"key-B")
        assert sig1 != sig2

    def test_sig_no_padding(self):
        """Generated signature should not contain base64 padding characters."""
        expiry = int(time.time()) + 600
        sig = _sign_artifact("art-1", expiry, _TEST_KEY)
        assert "=" not in sig
