"""Credential Pydantic data models.

This module defines the data models used for:
- Validating incoming credential payloads (POST/PUT requests)
- Representing DocumentDB storage documents
- Serializing API responses
"""
from __future__ import annotations
from typing import Any
from datetime import datetime
from pydantic import BaseModel, Field


class CredentialPayload(BaseModel):
    """Input model for creating/updating a user database credential.

    Validates the structure of a credential payload submitted via POST or PUT.
    Credential names are unique per user (not globally).

    Attributes:
        name: Unique credential name within the user's scope (1-128 chars).
        driver: asyncdb driver identifier (e.g., 'pg', 'mysql', 'bigquery').
        params: Connection parameters dict (host, port, user, password, database, etc.).
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique credential name per user",
    )
    driver: str = Field(
        ...,
        min_length=1,
        description="asyncdb driver name (e.g., 'pg', 'mysql', 'bigquery')",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Connection parameters (host, port, user, password, database, etc.)",
    )


class CredentialDocument(BaseModel):
    """DocumentDB storage model for a user credential.

    The ``credential`` field stores an encrypted JSON string produced by
    :func:`parrot.handlers.credentials_utils.encrypt_credential`.

    Attributes:
        user_id: Identifier of the owning user.
        name: Credential name (unique per user).
        credential: Encrypted JSON string of ``driver`` + ``params``.
        created_at: Timestamp when the credential was first created.
        updated_at: Timestamp of the most recent update.
    """

    user_id: str
    name: str
    credential: str = Field(
        ...,
        description="Encrypted JSON string of driver + params",
    )
    created_at: datetime
    updated_at: datetime


class CredentialResponse(BaseModel):
    """Response model for a single credential returned by the API.

    Sensitive parameters are returned as-is (decrypted) only to the
    authenticated owner of the credential.

    Attributes:
        name: Credential name.
        driver: asyncdb driver identifier.
        params: Decrypted connection parameters.
    """

    name: str
    driver: str
    params: dict[str, Any]
