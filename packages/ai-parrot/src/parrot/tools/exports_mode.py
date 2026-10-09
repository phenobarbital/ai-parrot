"""Host switch of the export tools' store-only mode (PA-11).

Off by default: the export tools (excel, csv, word, powerpoint, pdf, df_to_html, power_bi, chart) keep their previous
arguments, behaviour and return values. A host (Agent Studio) turns it on with ``app[STUDIO_EXPORTS_STORE_ONLY] = True``
(``parrot.handlers.studio`` copies it to this process on startup). While it is on:

* the arguments a tool lists in ``studio_hidden_args`` (output directory / file name / overwrite / template path /
  stylesheets ...) are not in its LLM schema and are dropped from a call: the LLM chooses CONTENT, never where it goes;
* a template is a file NAME inside the server's templates directory, never a path;
* the ``artifact_store`` constructor parameter is server-managed (filled from ``app["artifact_store"]``), exports are
  published under the caller's tenant partition and the tool returns ``{url, filename, bytes}``;
* a Studio-scoped call with no store is refused and never writes a local file.
"""

from __future__ import annotations

STUDIO_EXPORTS_STORE_ONLY = "studio_exports_store_only"
FEATURES = frozenset({"exports_store_only"})

_ENABLED = False


def configure(enabled: bool) -> None:
    """Turn the store-only mode on or off for this process (the host's ``app[STUDIO_EXPORTS_STORE_ONLY]``)."""
    global _ENABLED
    _ENABLED = bool(enabled)


def is_enabled() -> bool:
    """Whether the export tools run in store-only mode."""
    return _ENABLED


__all__ = ["FEATURES", "STUDIO_EXPORTS_STORE_ONLY", "configure", "is_enabled"]
