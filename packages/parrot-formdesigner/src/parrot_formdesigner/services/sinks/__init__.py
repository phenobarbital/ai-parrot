"""Submission sink family — destinations a `FormSchema` may declare.

This package is the single owner of the sink dispatch table: the four
sink backends (`postgres_table.py`, `asyncdb_store.py`, `csv_file.py`,
`gsheet.py`) each create their own module and none registers itself, so
they share no file. `SinkFactory` (`factory.py`) is the single place that
builds and caches sink instances, and enforces coordinate immutability.

Dispatch follows the string-keyed, lazy-import pattern established at
`packages/ai-parrot/src/parrot/stores/__init__.py:6` — an uninstalled
optional extra (`[gsheet]`) never breaks importing the other three sinks.
"""

from __future__ import annotations

import importlib

from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkError,
    SinkNotCapableError,
    SinkTargetMismatchError,
    SinkUnavailableError,
)

# type -> concrete sink class name. Resolved lazily via `_load()` — an
# absent optional extra (e.g. `[gsheet]`) never breaks importing the
# other three sinks or this package itself.
SUPPORTED_SINKS: dict[str, str] = {
    "postgres_table": "PostgresTableSink",
    "asyncdb": "AsyncDBSink",
    "csv_file": "CsvFileSink",
    "gsheet": "GoogleSheetSink",
}

# type -> the submodule (within this package) that defines its class.
_MODULES: dict[str, str] = {
    "postgres_table": "postgres_table",
    "asyncdb": "asyncdb_store",
    "csv_file": "csv_file",
    "gsheet": "gsheet",
}


def _load(type_: str) -> type[AbstractSubmissionSink]:
    """Lazily import and return the sink class registered for ``type_``.

    Args:
        type_: A key of :data:`SUPPORTED_SINKS` (e.g. ``"postgres_table"``).

    Returns:
        The concrete :class:`AbstractSubmissionSink` subclass.

    Raises:
        KeyError: If ``type_`` is not a supported sink type.
        ImportError: If the sink's module cannot be imported (e.g. the
            ``[gsheet]`` extra is not installed — the module itself still
            imports; only actually using an ungaurded symbol would fail,
            and each sink guards its own optional client import).
    """
    module = importlib.import_module(f".{_MODULES[type_]}", __name__)
    return getattr(module, SUPPORTED_SINKS[type_])


# Imported after SUPPORTED_SINKS/_MODULES/_load are defined above: `factory.py`
# defers its own `from parrot_formdesigner.services.sinks import _load` to
# call time, but this ordering keeps the dependency direction easy to reason
# about (dispatch table first, factory second).
from parrot_formdesigner.services.sinks.factory import SinkFactory

__all__ = [
    "SUPPORTED_SINKS",
    "AbstractSubmissionSink",
    "SinkError",
    "SinkFactory",
    "SinkNotCapableError",
    "SinkTargetMismatchError",
    "SinkUnavailableError",
]
