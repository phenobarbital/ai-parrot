---
type: Concept
title: encrypt_credential()
id: func:parrot.security.credentials_utils.encrypt_credential
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Encrypt a credential dict for DocumentDB storage.
---

# encrypt_credential

```python
def encrypt_credential(credential: dict, key_id: int, master_key: bytes) -> str
```

Encrypt a credential dict for DocumentDB storage.

Serializes the ``credential`` dict to JSON bytes, encrypts the bytes
using AES-GCM with the supplied master key, and returns a base64-encoded
ASCII string safe for storage in a DocumentDB string field.

Args:
    credential: asyncdb-syntax dict containing at minimum a ``driver``
        key plus any connection ``params`` (host, port, user, password,
        database, etc.).  All unicode characters and special symbols in
        values are preserved through the serialization round-trip.
    key_id: Integer key version identifier.  Embedded in the ciphertext
        header so that :func:`decrypt_credential` can select the correct
        master key on decryption.
    master_key: Raw 32-byte AES master key for this ``key_id`` version.

Returns:
    Base64-encoded (ASCII) encrypted string ready for DocumentDB storage.

Raises:
    ValueError: If ``master_key`` is not 32 bytes.
    TypeError: If ``credential`` is not JSON-serialisable.
