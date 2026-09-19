"""Tests for lazy tokenizer acquisition in ``parrot.skills.parsers``
(FEAT-581 TASK-3516).

Covers:
  - Importing the module in a fresh subprocess (with a fake ``tiktoken``
    substituted before import) never fetches tokenizer data — the encoder
    is not created at import time.
  - The first call to ``_count_tokens``/``_get_encoding`` lazily
    initializes the encoder exactly once, and every subsequent call
    reuses the same cached instance (no re-fetch).
  - A failed encoder acquisition does not poison the cache: it leaves
    ``_ENCODING`` unset so a later call can retry and succeed.
  - Token counts are unchanged by the refactor (same encoding, same
    output for the same input).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.skills import parsers
from parrot.skills.parsers import _count_tokens

# Absolute path to the ``src`` layout of this worktree's ai-parrot package,
# used so the subprocess below imports THIS worktree's copy of
# ``parrot.skills.parsers`` rather than any other copy that might be on the
# ambient PYTHONPATH (mirrors packages/ai-parrot/conftest.py).
_SRC_DIR = Path(__file__).resolve().parents[2] / "src"


class TestLazyEncoderSubprocess:
    """Process-boundary checks: import-time behavior and first-use caching."""

    def test_import_never_fetches_and_first_count_initializes_and_reuses(self):
        script = """
import sys
import types

calls = []


class _FakeEncoding:
    def encode(self, text):
        return list(text.encode("utf-8"))


def _fake_get_encoding(name):
    calls.append(name)
    return _FakeEncoding()


fake_tiktoken = types.ModuleType("tiktoken")
fake_tiktoken.get_encoding = _fake_get_encoding
sys.modules["tiktoken"] = fake_tiktoken

from parrot.skills.parsers import _count_tokens, _get_encoding

# 1. Import alone must never fetch the tokenizer.
assert calls == [], f"import fetched tokenizer eagerly: {calls!r}"

# 2. The first count triggers exactly one lazy fetch.
first = _count_tokens("hello world")
assert calls == ["cl100k_base"], f"first count did not initialize encoder: {calls!r}"

# 3. A second count reuses the cached encoder — no second fetch.
second = _count_tokens("hello world again")
assert calls == ["cl100k_base"], f"second count re-fetched the encoder: {calls!r}"
assert first > 0 and second > 0

# 4. _get_encoding itself returns the same cached instance on reuse.
enc1 = _get_encoding()
enc2 = _get_encoding()
assert enc1 is enc2, "encoder instance was not reused"
assert calls == ["cl100k_base"], f"_get_encoding re-fetched: {calls!r}"

print("OK")
"""
        env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(_SRC_DIR)}
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (
            f"subprocess failed (rc={result.returncode})\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "OK" in result.stdout


class TestGetEncodingFailureCleanup:
    """A failed fetch must not poison the module-level cache."""

    def test_failure_does_not_cache_broken_state_and_retry_succeeds(self, monkeypatch):
        monkeypatch.setattr(parsers, "_ENCODING", None)

        real_get_encoding = parsers.tiktoken.get_encoding
        calls = {"count": 0}

        class _Boom(RuntimeError):
            """Simulated tokenizer-fetch failure."""

        def flaky_get_encoding(name):
            calls["count"] += 1
            if calls["count"] == 1:
                raise _Boom("simulated fetch failure")
            return real_get_encoding(name)

        monkeypatch.setattr(parsers.tiktoken, "get_encoding", flaky_get_encoding)

        with pytest.raises(_Boom):
            parsers._get_encoding()

        # The failed attempt must not leave a half-initialized cache behind.
        assert parsers._ENCODING is None

        # Retrying succeeds and the result is cached.
        encoding = parsers._get_encoding()
        assert encoding is not None
        assert calls["count"] == 2

        # A further call reuses the cached encoder — no third fetch.
        encoding_again = parsers._get_encoding()
        assert encoding_again is encoding
        assert calls["count"] == 2


class TestTokenCountUnchanged:
    """The lazy refactor must not change what gets counted."""

    def test_count_matches_direct_cl100k_base_encoding(self):
        import tiktoken

        text = "Resume textos largos en bullet points."
        expected = len(tiktoken.get_encoding("cl100k_base").encode(text))
        assert _count_tokens(text) == expected

    def test_empty_string_counts_zero(self):
        assert _count_tokens("") == 0

    def test_reuse_across_multiple_in_process_calls(self, monkeypatch):
        monkeypatch.setattr(parsers, "_ENCODING", None)
        real_get_encoding = parsers.tiktoken.get_encoding
        calls = {"count": 0}

        def counting_get_encoding(name):
            calls["count"] += 1
            return real_get_encoding(name)

        monkeypatch.setattr(parsers.tiktoken, "get_encoding", counting_get_encoding)

        _count_tokens("first call")
        _count_tokens("second call")
        _count_tokens("third call")

        assert calls["count"] == 1
