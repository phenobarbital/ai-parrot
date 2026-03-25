"""Credential encryption/decryption helpers for DocumentDB storage.

This module provides thin wrappers around
:mod:`navigator_session.vault.crypto` specialized for credential dictionaries.

Credentials are serialized to JSON bytes with ``orjson``, encrypted with
AES-GCM via :func:`encrypt_for_db`, and stored as base64-encoded ASCII
strings in DocumentDB.  Decryption reverses the process.

Encryption format (from navigator_session vault):
    ``[key_id 2B uint16 BE][nonce 12B][encrypted_payload + tag]``
"""
from __future__ import annotations
import base64
import orjson
from navigator_session.vault.crypto import encrypt_for_db, decrypt_for_db


def encrypt_credential(
    credential: dict,
    key_id: int,
    master_key: bytes,
) -> str:
    """Encrypt a credential dict for DocumentDB storage.

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
    """
    plaintext: bytes = orjson.dumps(credential)
    ciphertext: bytes = encrypt_for_db(plaintext, key_id, master_key)
    return base64.b64encode(ciphertext).decode("ascii")


def decrypt_credential(
    encrypted: str,
    master_keys: dict[int, bytes],
) -> dict:
    """Decrypt a credential string retrieved from DocumentDB.

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
    """
    ciphertext: bytes = base64.b64decode(encrypted)
    plaintext: bytes = decrypt_for_db(ciphertext, master_keys)
    return orjson.loads(plaintext)
