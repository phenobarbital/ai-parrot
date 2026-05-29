"""Backward-compatible redirect — credentials_utils relocated to parrot.security in FEAT-203.

This module was moved to :mod:`parrot.security.credentials_utils` in FEAT-203.
This stub re-exports everything from the new location so existing imports
(e.g. ``from parrot.handlers.credentials_utils import encrypt_credential``)
continue to work unchanged.
"""
from parrot.security.credentials_utils import (  # noqa: F401
    encrypt_credential,
    decrypt_credential,
)

__all__ = [
    "encrypt_credential",
    "decrypt_credential",
]
