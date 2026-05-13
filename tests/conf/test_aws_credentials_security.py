"""Unit tests for the AWS_CREDENTIALS['security'] slot in parrot/conf.py.

Tests verify that:
- The slot is registered when the aws_security INI section provides an aws_key.
- No exception is raised and a warning is logged when the section is absent.
"""
from __future__ import annotations

import importlib
import logging
import sys


class TestAwsSecuritySlotPresent:
    """Tests when aws_security credentials ARE configured."""

    def test_slot_registered_when_key_present(self, monkeypatch) -> None:
        """AWS_CREDENTIALS['security'] is populated when aws_key is configured."""
        # Patch navconfig.config.get so that queries for 'aws_key' in
        # section 'aws_security' return a real value.
        import navconfig as nc
        orig_get = nc.config.get

        def patched_get(key, section=None, fallback=None):
            if section == 'aws_security':
                if key == 'aws_key':
                    return 'TEST_KEY_123'
                if key == 'aws_secret':
                    return 'TEST_SECRET_456'
                if key == 'region_name':
                    return 'eu-west-1'
            return orig_get(key, section=section, fallback=fallback)

        monkeypatch.setattr(nc.config, 'get', patched_get)

        # Force reload so the new monkeypatched config.get is used.
        if 'parrot.conf' in sys.modules:
            del sys.modules['parrot.conf']
        import parrot.conf as conf

        try:
            assert 'security' in conf.AWS_CREDENTIALS, (
                "AWS_CREDENTIALS['security'] must be registered when aws_key is set"
            )
            assert conf.AWS_CREDENTIALS['security']['aws_key'] == 'TEST_KEY_123'
            assert conf.AWS_CREDENTIALS['security']['aws_secret'] == 'TEST_SECRET_456'
            assert conf.AWS_CREDENTIALS['security']['region_name'] == 'eu-west-1'
        finally:
            # Restore original module to avoid poisoning other tests.
            if 'parrot.conf' in sys.modules:
                del sys.modules['parrot.conf']


class TestAwsSecuritySlotAbsent:
    """Tests when aws_security credentials are NOT configured."""

    def test_no_raise_when_key_absent(self, monkeypatch, caplog) -> None:
        """Importing parrot.conf must NOT raise when aws_security.aws_key is None."""
        import navconfig as nc
        orig_get = nc.config.get

        def patched_get(key, section=None, fallback=None):
            if section == 'aws_security':
                return fallback  # always returns fallback (None)
            return orig_get(key, section=section, fallback=fallback)

        monkeypatch.setattr(nc.config, 'get', patched_get)

        if 'parrot.conf' in sys.modules:
            del sys.modules['parrot.conf']

        with caplog.at_level(logging.WARNING):
            import parrot.conf as conf  # must not raise

        try:
            assert 'security' not in conf.AWS_CREDENTIALS, (
                "AWS_CREDENTIALS['security'] must NOT be registered when aws_key is None"
            )
            # A warning must have been emitted.
            assert any(
                'aws_security' in record.message
                for record in caplog.records
            ), "Expected a warning mentioning 'aws_security'"
        finally:
            if 'parrot.conf' in sys.modules:
                del sys.modules['parrot.conf']
