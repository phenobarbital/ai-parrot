---
type: Concept
title: decrypt_credential()
id: func:parrot.security.credentials_utils.decrypt_credential
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decrypt a credential string retrieved from DocumentDB.
---

# decrypt_credential

```python
def decrypt_credential(encrypted: str, master_keys: dict[int, bytes]) -> dict
```

Decrypt a credential string retrieved from DocumentDB.

Reverses the encoding applied by :func:`encrypt_credential`:
base64-decodes the stored string, decrypts the AES-GCM ciphertext
(selecting the key version from the embedded header), and deserializes
the resulting JSON bytes back to the original dict.

Args:
    encrypted: Base64-encoded encrypted string as stored by
        :func:`encrypt_credential`.
    master_keys: Mapping of ``key_id`` → raw 32-byte master key.  Must
        contain the key version that was used to encrypt the credential.

Returns:
    Original credential dict with ``driver`` and connection ``params``.

Raises:
    KeyError: If the ``key_id`` embedded in the ciphertext is not present
        in ``master_keys``.
    binascii.Error: If ``encrypted`` is not valid base64.
    orjson.JSONDecodeError: If the decrypted bytes are not valid JSON.
