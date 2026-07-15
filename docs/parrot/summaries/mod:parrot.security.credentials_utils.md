---
type: Wiki Summary
title: parrot.security.credentials_utils
id: mod:parrot.security.credentials_utils
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Credential encryption/decryption helpers for DocumentDB storage.
relates_to:
- concept: func:parrot.security.credentials_utils.decrypt_credential
  rel: defines
- concept: func:parrot.security.credentials_utils.encrypt_credential
  rel: defines
---

# `parrot.security.credentials_utils`

Credential encryption/decryption helpers for DocumentDB storage.

This module provides thin wrappers around
:mod:`navigator_session.vault.crypto` specialized for credential dictionaries.

Credentials are serialized to JSON bytes with ``orjson``, encrypted with
AES-GCM via :func:`encrypt_for_db`, and stored as base64-encoded ASCII
strings in DocumentDB.  Decryption reverses the process.

Encryption format (from navigator_session vault):
    ``[key_id 2B uint16 BE][nonce 12B][encrypted_payload + tag]``

## Functions

- `def encrypt_credential(credential: dict, key_id: int, master_key: bytes) -> str` — Encrypt a credential dict for DocumentDB storage.
- `def decrypt_credential(encrypted: str, master_keys: dict[int, bytes]) -> dict` — Decrypt a credential string retrieved from DocumentDB.
