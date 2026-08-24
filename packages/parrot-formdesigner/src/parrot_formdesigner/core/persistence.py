"""Per-form persistence configuration models.

This module defines the declarative, credential-free description of
*where* a form's data (submissions) and definition (schema body) are
stored. It mirrors the pattern already proven by
:mod:`parrot_formdesigner.core.auth`: a Pydantic **discriminated union**
whose members carry only the *name* of a credential source — here, a
connection **alias** — never a secret, DSN, password or key.

No sink, storage, or aiohttp code is imported here. Resolution of a
``connection`` alias against an allowlist of credential sources happens
server-side, in ``services/sink_aliases.py`` (a separate module).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from parrot_formdesigner.services._identifiers import validate_identifier


def _reject_path_traversal(value: str) -> str:
    """Reject an absolute path or any path containing a traversal segment.

    Args:
        value: Candidate relative path (e.g. ``"nps_2026.csv"``).

    Returns:
        The validated path, unchanged.

    Raises:
        ValueError: If ``value`` is absolute or contains a ``..`` segment.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("path must be a non-empty string")
    if value.startswith(("/", "\\")):
        raise ValueError(f"path must be relative, got absolute path: {value!r}")
    # Normalize separators before splitting into segments.
    segments = value.replace("\\", "/").split("/")
    if ".." in segments:
        raise ValueError(f"path traversal segment ('..') rejected: {value!r}")
    return value


class SinkCapability(str, Enum):
    """Operations a submission sink may support.

    Attributes:
        WRITE: The sink can persist a new submission.
        READ: The sink can retrieve a single submission by id.
        LIST: The sink can list submission revisions.
        PROVISION: The sink can create its own destination on first use.
        EXTEND: The sink can additively extend its destination (new columns
            or headers) as a form gains fields.
    """

    WRITE = "write"
    READ = "read"
    LIST = "list"
    PROVISION = "provision"
    EXTEND = "extend"


class PostgresTableTarget(BaseModel):
    """Arbitrary Postgres table owned by this form.

    Attributes:
        type: Discriminator literal, always ``"postgres_table"``.
        connection: Alias resolved server-side to a DSN — NEVER a raw DSN.
        schema_name: Postgres schema name (named ``schema_name`` because
            ``schema`` shadows :meth:`pydantic.BaseModel.schema`).
        table: Postgres table name.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["postgres_table"] = "postgres_table"
    connection: str = Field(..., description="Alias resolved server-side, never a DSN")
    schema_name: str
    table: str

    @field_validator("schema_name")
    @classmethod
    def _validate_schema_name(cls, value: str) -> str:
        return validate_identifier(value, kind="schema_name")

    @field_validator("table")
    @classmethod
    def _validate_table(cls, value: str) -> str:
        return validate_identifier(value, kind="table")


class AsyncDBTarget(BaseModel):
    """Any other ``asyncdb``-backed store (Mongo / BigQuery / Arango).

    Attributes:
        type: Discriminator literal, always ``"asyncdb"``.
        connection: Alias resolved server-side to credentials — NEVER a raw DSN.
        driver: The asyncdb driver name, e.g. ``"mongo"``, ``"bigquery"``,
            ``"arango"``.
        collection: Collection / dataset.table / document collection name.
            Document drivers (``mongo``, ``arango``) store ``data`` NESTED,
            unflattened — see the submission mapper.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["asyncdb"] = "asyncdb"
    connection: str = Field(..., description="Alias resolved server-side, never a DSN")
    driver: str
    collection: str

    @field_validator("collection")
    @classmethod
    def _validate_collection(cls, value: str) -> str:
        return validate_identifier(value, kind="collection")


class CsvFileTarget(BaseModel):
    """One appended line per submission, inside an allowlisted base dir.

    Attributes:
        type: Discriminator literal, always ``"csv_file"``.
        connection: Alias resolved server-side to an allowed base directory.
        path: Relative path (inside the alias's base dir). Traversal segments
            (``..``) and absolute paths are rejected at construction.
        delimiter: CSV field delimiter, defaults to ``","``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["csv_file"] = "csv_file"
    connection: str = Field(..., description="Alias resolved server-side to a base dir")
    path: str
    delimiter: str = ","

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _reject_path_traversal(value)


class GoogleSheetTarget(BaseModel):
    """A Google Sheets worksheet owned by this form.

    Attributes:
        type: Discriminator literal, always ``"gsheet"``.
        connection: Alias resolved server-side to service-account credentials.
        spreadsheet_id: The target spreadsheet's id.
        worksheet: The target worksheet name, defaults to ``"Sheet1"``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["gsheet"] = "gsheet"
    connection: str = Field(
        ..., description="Alias resolved server-side to service-account credentials"
    )
    spreadsheet_id: str
    worksheet: str = "Sheet1"


SubmissionTarget = Annotated[
    PostgresTableTarget | AsyncDBTarget | CsvFileTarget | GoogleSheetTarget,
    Field(discriminator="type"),
]


class FileDefinitionTarget(BaseModel):
    """A form definition body stored as a file, inside an allowlisted base dir.

    Attributes:
        type: Discriminator literal, always ``"file"``.
        connection: Alias resolved server-side to an allowed base directory.
        path: Relative path (inside the alias's base dir), e.g.
            ``"nps_2026.form.yaml"``. Traversal segments (``..``) and
            absolute paths are rejected at construction.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["file"] = "file"
    connection: str = Field(..., description="Alias resolved server-side to a base dir")
    path: str

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _reject_path_traversal(value)


DefinitionTarget = Annotated[FileDefinitionTarget, Field(discriminator="type")]


class FormPersistenceConfig(BaseModel):
    """Per-form persistence declaration. Absent on ``FormSchema`` -> today's behaviour.

    Attributes:
        data: Where this form's submission data is written.
        definition: Where this form's definition body is stored, if the
            registry's pointer-indexing decorator is in use. ``None`` means
            the definition body lives directly in the registry's own storage.
    """

    model_config = ConfigDict(extra="forbid")

    data: SubmissionTarget
    definition: DefinitionTarget | None = None
