"""`GoogleSheetSink` — a Google Sheets worksheet owned by a single form.

The cloud counterpart of :class:`~parrot_formdesigner.services.sinks.
csv_file.CsvFileSink`. Unlike CSV, the Sheets API *can* append a column,
so this sink declares ``EXTEND``.

This is the only v1 sink needing a new dependency
(``google-api-python-client``, the ``[gsheet]`` optional extra), so it
must degrade cleanly: with the extra uninstalled, importing this module
(and `parrot-formdesigner` as a whole) must still succeed — only USING
the sink raises an actionable error.

``googleapiclient`` is synchronous; every call to it is offloaded via
``asyncio.to_thread`` — never called directly on the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from parrot_formdesigner.core.persistence import GoogleSheetTarget, SinkCapability
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.mapper import column_names_for
from parrot_formdesigner.services.submissions import FormSubmission

try:
    from googleapiclient.discovery import build  # google-api-python-client
except ImportError:  # pragma: no cover — exercised via monkeypatch in tests
    build = None


class _SheetsClient:
    """Thin synchronous wrapper over a `googleapiclient` Sheets v4 service.

    Every method here is a blocking network call — the sink is
    responsible for offloading each one via ``asyncio.to_thread``.
    """

    def __init__(self, service: Any, spreadsheet_id: str, worksheet: str) -> None:
        self._service = service
        self._spreadsheet_id = spreadsheet_id
        self._worksheet = worksheet

    def get_header(self) -> list[str] | None:
        """Return the worksheet's current header row, or ``None`` if empty."""
        result = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=f"{self._worksheet}!1:1")
            .execute()
        )
        values = result.get("values", [])
        return values[0] if values else None

    def write_header(self, header: list[str]) -> None:
        """Write ``header`` as the worksheet's row 1 (create or overwrite)."""
        (
            self._service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._worksheet}!1:1",
                valueInputOption="RAW",
                body={"values": [header]},
            )
            .execute()
        )

    def append_row(self, row: list[Any]) -> None:
        """Append one data row to the worksheet."""
        (
            self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._worksheet}!A:A",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            )
            .execute()
        )

    def append_column(self, name: str) -> None:
        """Append one column to the header, leaving existing columns in place."""
        header = self.get_header() or []
        header = [*header, name]
        self.write_header(header)


class GoogleSheetSink(AbstractSubmissionSink):
    """A Google Sheets worksheet owned by a single form.

    Capabilities are ``{WRITE, PROVISION, EXTEND}`` — no ``READ``, no
    ``LIST`` (write-only by declaration).

    Args:
        target: The validated :class:`GoogleSheetTarget` this sink writes to.
        alias_registry: Resolves ``target.connection`` to service-account
            credentials.
        tenant: Tenant scope used to resolve the connection alias.
        client: An existing client implementing ``get_header``/
            ``write_header``/``append_row``/``append_column``. When
            provided, this sink skips building its own — primarily for
            tests (a fake client).
    """

    def __init__(
        self,
        target: GoogleSheetTarget,
        *,
        alias_registry: SinkAliasRegistry,
        tenant: str,
        client: Any | None = None,
    ) -> None:
        self._target = target
        self._alias_registry = alias_registry
        self._tenant = tenant
        self._client: Any | None = client
        self._header: list[str] | None = None
        self.logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[SinkCapability]:
        """``{WRITE, PROVISION, EXTEND}`` — no READ, no LIST."""
        return frozenset(
            {SinkCapability.WRITE, SinkCapability.PROVISION, SinkCapability.EXTEND}
        )

    def _build_service_sync(self, creds_blob: str) -> Any:
        """Build a raw `googleapiclient` Sheets v4 service (blocking).

        Args:
            creds_blob: A service-account credentials source resolved via
                :meth:`SinkAliasRegistry.resolve_credentials` — either a
                JSON blob string or a path to a service-account JSON file.
        """
        from google.oauth2 import service_account  # lazy runtime import

        try:
            info = json.loads(creds_blob)
            credentials = service_account.Credentials.from_service_account_info(info)
        except (ValueError, TypeError):
            credentials = service_account.Credentials.from_service_account_file(
                creds_blob
            )
        return build("sheets", "v4", credentials=credentials)

    async def _ensure_client(self) -> Any:
        """Return the cached client, building one if needed.

        Raises:
            SinkUnavailableError: If the ``[gsheet]`` extra is not
                installed (names the extra + install command), or if
                credential resolution / client construction fails.
        """
        if self._client is None:
            if build is None:
                raise SinkUnavailableError(
                    "Google Sheets sink requires the 'gsheet' extra: "
                    "pip install parrot-formdesigner[gsheet]"
                )
            try:
                creds_blob = self._alias_registry.resolve_credentials(
                    self._target.connection, tenant=self._tenant
                )
                service = await asyncio.to_thread(
                    self._build_service_sync, creds_blob
                )
                self._client = _SheetsClient(
                    service, self._target.spreadsheet_id, self._target.worksheet
                )
            except SinkUnavailableError:
                raise
            except Exception as exc:
                raise SinkUnavailableError(
                    f"Cannot build Google Sheets client for "
                    f"{self._target.connection!r}: {exc}"
                ) from exc
        return self._client

    async def ensure_target(self, form: FormSchema) -> None:
        """Create the worksheet's header when absent; append new columns.

        Existing columns are never reordered or deleted — a new form
        field appends a column at the trailing position.

        Raises:
            SinkUnavailableError: On extra-absent, auth, rate-limit
                (``429``), or transport failure. No retry is attempted.
        """
        client = await self._ensure_client()
        form_header = column_names_for(form)
        try:
            existing = await asyncio.to_thread(client.get_header)
            if not existing:
                await asyncio.to_thread(client.write_header, form_header)
                self._header = list(form_header)
            else:
                missing = [c for c in form_header if c not in existing]
                for column in missing:
                    await asyncio.to_thread(client.append_column, column)
                self._header = [*existing, *missing]
        except SinkUnavailableError:
            raise
        except Exception as exc:
            raise SinkUnavailableError(
                f"Google Sheets sink {self._target.connection!r} "
                f"unavailable during ensure_target: {exc}"
            ) from exc

    async def write(self, submission: FormSubmission, payload: Any) -> str:
        """Append one row. No retry on failure (including ``429``).

        Args:
            submission: The submission being persisted.
            payload: The flattened row dict for this submission.

        Returns:
            The persisted ``submission_id``.

        Raises:
            SinkUnavailableError: On rate-limit (``429``), auth, or
                transport failure.
        """
        client = await self._ensure_client()
        header = self._header if self._header is not None else list(payload.keys())
        row = [payload.get(col, "") for col in header]
        try:
            await asyncio.to_thread(client.append_row, row)
        except SinkUnavailableError:
            raise
        except Exception as exc:
            raise SinkUnavailableError(
                f"Google Sheets sink {self._target.connection!r} "
                f"unavailable during write: {exc}"
            ) from exc
        return submission.submission_id
