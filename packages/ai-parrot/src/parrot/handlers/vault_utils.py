"""Backward-compatible redirect — vault_utils relocated to parrot.security in FEAT-203.

This module was moved to :mod:`parrot.security.vault_utils` in FEAT-203.
This stub re-exports everything from the new location so existing imports
(e.g. ``from parrot.handlers.vault_utils import store_vault_credential``)
continue to work unchanged.
"""
from parrot.security.vault_utils import (  # noqa: F401
    VAULT_CRED_COLLECTION,
    load_vault_keys,
    store_vault_credential,
    retrieve_vault_credential,
    delete_vault_credential,
    oauth2_vault_name,
)

__all__ = [
    "load_vault_keys",
    "store_vault_credential",
    "retrieve_vault_credential",
    "delete_vault_credential",
    "oauth2_vault_name",
    "VAULT_CRED_COLLECTION",
]
