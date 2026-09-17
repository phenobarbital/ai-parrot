"""Unit tests for the AWS_CREDENTIALS['security'] slot in parrot/conf.py.

The slot was introduced by TASK-1115 (c93a6ca5d) as an optional entry read
from an ``[aws_security]`` INI section.  Commit dae3bc14b ("AWS credentials")
intentionally replaced that with two always-present slots, ``security`` and
``security_bucket``, read from flat environment/config keys
(``AWS_ACCESS_SECURITY_KEY_ID`` / ``AWS_SECRET_SECURITY_KEY`` / ...).

Tests verify that:
- The slot carries the configured key, secret and region.
- Importing ``parrot.conf`` never raises when the keys are absent; the slot is
  still registered, with ``None`` credentials and the default region.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Iterator

_SECURITY_VALUES = {
    "AWS_ACCESS_SECURITY_KEY_ID": "TEST_KEY_123",
    "AWS_SECRET_SECURITY_KEY": "TEST_SECRET_456",
    "AWS_ACCESS_SECURITY_REGION": "eu-west-1",
    "AWS_SECURITY_REGION": "eu-west-2",
    "AWS_SECURITY_BUCKET_NAME": "security-bucket",
}


@contextmanager
def _fresh_conf(monkeypatch, overrides: dict[str, Any]) -> Iterator[Any]:
    """Re-import ``parrot.conf`` with ``navconfig.config.get`` patched.

    Keys in *overrides* resolve to their mapped value (``None`` means "not
    configured", so the caller's ``fallback`` applies). The original module
    object is restored afterwards so other tests keep a consistent
    ``parrot.conf``.

    Args:
        monkeypatch: pytest ``monkeypatch`` fixture.
        overrides: Config keys to intercept and their values.

    Yields:
        The freshly imported ``parrot.conf`` module.
    """
    import navconfig as nc
    import parrot

    orig_get = nc.config.get

    def patched_get(key, *args, **kwargs):
        if key in overrides:
            value = overrides[key]
            return kwargs.get("fallback") if value is None else value
        return orig_get(key, *args, **kwargs)

    monkeypatch.setattr(nc.config, "get", patched_get)

    orig_module = sys.modules.pop("parrot.conf", None)
    try:
        import parrot.conf as conf  # noqa: PLC0415 - re-import under the patch

        yield conf
    finally:
        sys.modules.pop("parrot.conf", None)
        if orig_module is not None:
            sys.modules["parrot.conf"] = orig_module
            monkeypatch.setattr(parrot, "conf", orig_module, raising=False)


class TestAwsSecuritySlotPresent:
    """Tests when the security credentials ARE configured."""

    def test_slot_registered_when_key_present(self, monkeypatch) -> None:
        """AWS_CREDENTIALS['security'] carries the configured key/secret/region."""
        with _fresh_conf(monkeypatch, _SECURITY_VALUES) as conf:
            slot = conf.AWS_CREDENTIALS["security"]
            assert slot["use_credentials"] is True
            assert slot["aws_key"] == "TEST_KEY_123"
            assert slot["aws_secret"] == "TEST_SECRET_456"
            assert slot["region_name"] == "eu-west-1"

            bucket = conf.AWS_CREDENTIALS["security_bucket"]
            assert bucket["aws_key"] == "TEST_KEY_123"
            assert bucket["aws_secret"] == "TEST_SECRET_456"
            assert bucket["region_name"] == "eu-west-2"
            assert bucket["bucket_name"] == "security-bucket"


class TestAwsSecuritySlotAbsent:
    """Tests when the security credentials are NOT configured."""

    def test_no_raise_when_key_absent(self, monkeypatch) -> None:
        """Importing parrot.conf must NOT raise when the security keys are unset."""
        absent: dict[str, Any] = dict.fromkeys(_SECURITY_VALUES)
        with _fresh_conf(monkeypatch, absent) as conf:  # must not raise
            slot = conf.AWS_CREDENTIALS["security"]
            assert slot["aws_key"] is None
            assert slot["aws_secret"] is None
            assert slot["region_name"] == "us-east-2"
            assert conf.AWS_CREDENTIALS["security_bucket"]["bucket_name"] is None
