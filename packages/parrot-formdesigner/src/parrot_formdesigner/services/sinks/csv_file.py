"""`CsvFileSink` — lock-free single-line append to a local CSV file.

The Microsoft-Forms-style use case that motivated this feature: a survey
whose responses land as one appended row in a local file, inside an
allowlisted base directory.

Two decisions constrain this sink tightly (spec section 8, resolved):

- **No lock.** One write emits exactly one ``\\n``-terminated line in a
  single write call. Concurrent workers can still interleave a long row;
  that is a documented, accepted limitation — never coordinate via a
  file lock.
- **``.xlsx`` is out of scope.** A workbook cannot be appended — it must
  be rewritten — which is irreconcilable with the above. This sink is
  CSV only.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from pathlib import Path
from typing import Any

from parrot_formdesigner.core.persistence import CsvFileTarget, SinkCapability
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.mapper import column_names_for
from parrot_formdesigner.services.submissions import FormSubmission


class CsvFileSink(AbstractSubmissionSink):
    """One appended line per submission, inside an allowlisted base dir.

    Capabilities are exactly ``{WRITE, PROVISION}`` — deliberately NOT
    ``EXTEND`` (an existing file's header is never rewritten) and NOT
    ``READ``/``LIST`` (write-only by declaration; the ABC's defaults
    raise ``SinkNotCapableError`` for those).

    Args:
        target: The validated :class:`CsvFileTarget` this sink writes to.
        alias_registry: Resolves ``target.connection`` to a base
            directory and contains ``target.path`` within it.
        tenant: Tenant scope used to resolve the connection alias.
    """

    def __init__(
        self,
        target: CsvFileTarget,
        *,
        alias_registry: SinkAliasRegistry,
        tenant: str,
    ) -> None:
        self._target = target
        self._alias_registry = alias_registry
        self._tenant = tenant
        # Populated by ensure_target(): the file's REAL on-disk header
        # (never rewritten), plus any form columns not present in it
        # ("extra"/trailing columns — see ensure_target's docstring).
        self._header: list[str] | None = None
        self._extra_columns: list[str] = []
        self.logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[SinkCapability]:
        """Write-only: ``{WRITE, PROVISION}``. No READ, no LIST, no EXTEND."""
        return frozenset({SinkCapability.WRITE, SinkCapability.PROVISION})

    def _resolve_path(self) -> Path:
        """Resolve ``target.path`` against the alias's base dir, safely.

        Raises:
            ValueError: If the resolved path escapes the alias's base dir
                (propagates from :meth:`SinkAliasRegistry.contain`).
        """
        return self._alias_registry.contain(
            self._target.connection,
            tenant=self._tenant,
            relative_path=self._target.path,
        )

    def _render_line(self, row: dict[str, Any], columns: list[str]) -> str:
        """Serialize one row into a single, newline-terminated CSV line.

        Args:
            row: The flattened payload for one submission.
            columns: The column order to emit values in.

        Returns:
            The rendered line, already ``\\n``-terminated by ``csv.writer``.
        """
        buf = io.StringIO()
        csv.writer(buf, delimiter=self._target.delimiter).writerow(
            [row.get(col, "") for col in columns]
        )
        return buf.getvalue()

    def _append(self, line: str) -> None:
        """Append ``line`` to the target file in a single write call.

        Exactly one ``fh.write()`` per submission — never use
        ``csv.writer`` directly on the file handle, which may emit
        multiple writes.
        """
        path = self._resolve_path()
        with open(path, "a", newline="", encoding="utf-8") as fh:
            fh.write(line)

    def _read_header(self, path: Path) -> list[str] | None:
        """Return the file's current header row, or ``None`` if absent/empty."""
        if not path.exists():
            return None
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter=self._target.delimiter)
            for row in reader:
                return row
        return None

    def _create_with_header(self, path: Path, header: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        csv.writer(buf, delimiter=self._target.delimiter).writerow(header)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            fh.write(buf.getvalue())

    async def ensure_target(self, form: FormSchema) -> None:
        """Create the file with a header row when absent.

        When the file already exists, its header is left byte-identical —
        this sink deliberately does NOT declare ``EXTEND``. If the form
        now produces columns the existing header lacks, a warning is
        logged (never a rewrite): those columns are cached as
        ``_extra_columns`` and their values are appended as TRAILING
        fields (beyond the existing header's column count) on every
        subsequent :meth:`write`.

        Raises:
            SinkUnavailableError: If the file cannot be created/read
                (permission error, missing/unwritable directory, etc.).
        """
        form_header = column_names_for(form)
        try:
            path = await asyncio.to_thread(self._resolve_path)
            existing_header = await asyncio.to_thread(self._read_header, path)
            if existing_header is None:
                await asyncio.to_thread(self._create_with_header, path, form_header)
                self._header = form_header
                self._extra_columns = []
            else:
                missing = [c for c in form_header if c not in existing_header]
                if missing:
                    self.logger.warning(
                        "CsvFileSink: form %s produces columns not in the "
                        "existing CSV header %s — header left untouched; "
                        "%s will be appended as trailing columns.",
                        form.form_uid,
                        existing_header,
                        missing,
                    )
                self._header = existing_header
                self._extra_columns = missing
        except ValueError:
            raise
        except OSError as exc:
            raise SinkUnavailableError(
                f"CSV sink {self._target.connection!r} unavailable during "
                f"ensure_target: {exc}"
            ) from exc

    async def write(self, submission: FormSubmission, payload: Any) -> str:
        """Append one row: exactly one ``fh.write()`` syscall.

        Column order is the cached header from the most recent
        :meth:`ensure_target` call, plus any drifted "extra" columns as
        trailing fields. If ``ensure_target`` has never run, falls back
        to ``payload``'s own key order.

        Args:
            submission: The submission being persisted.
            payload: The flattened row dict for this submission.

        Returns:
            The persisted ``submission_id``.

        Raises:
            SinkUnavailableError: If the append fails.
        """
        columns = (
            [*self._header, *self._extra_columns]
            if self._header is not None
            else list(payload.keys())
        )
        line = self._render_line(payload, columns)
        try:
            await asyncio.to_thread(self._append, line)
        except ValueError:
            raise
        except OSError as exc:
            raise SinkUnavailableError(
                f"CSV sink {self._target.connection!r} unavailable during "
                f"write: {exc}"
            ) from exc
        return submission.submission_id
