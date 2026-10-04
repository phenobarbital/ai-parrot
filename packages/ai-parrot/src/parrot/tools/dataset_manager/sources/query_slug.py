"""
QuerySlugSource and MultiQuerySlugSource implementations.

Wraps the QuerySource (QS) and MultiQS patterns as proper DataSource
implementations, replacing the inline _call_qs() / _call_multiquery()
logic that previously lived in DatasetManager.
"""

from __future__ import annotations
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from .base import DataSource
from parrot._imports import lazy_import

if TYPE_CHECKING:  # pragma: no cover
    from querysource.auth.principal import QSPrincipal
    from querysource.tenants import LoadedDefinition
    from parrot.auth.permission import PermissionContext

# Module-level variable so names are patchable in tests.
QS = None  # type: ignore[assignment,misc]
MultiQS = None  # type: ignore[assignment,misc]


def _get_qs():
    """Lazily import QS from querysource. Returns None if not installed."""
    global QS
    if QS is not None:
        return QS
    try:
        _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
        QS = _qs_mod.QS
        return QS
    except ImportError:
        return None


def _get_multiqs():
    """Lazily import MultiQS from querysource. Returns None if not installed."""
    global MultiQS
    if MultiQS is not None:
        return MultiQS
    try:
        _mq_mod = lazy_import("querysource.queries.multi", package_name="querysource", extra="db")
        MultiQS = _mq_mod.MultiQS
        return MultiQS
    except ImportError:
        return None


class QuerySlugSource(DataSource):
    """DataSource backed by a single QuerySource slug.

    Wraps QS(slug=..., conditions=params) and exposes it as a lazy DataSource.
    Schema prefetch performs a 1-row query to infer column names and dtypes.

    Args:
        slug: The QuerySource slug identifier.
        prefetch_schema_enabled: When True, prefetch_schema() will call QS with
            querylimit=1 to infer the schema. Defaults to True.
        permanent_filter: Optional dict of conditions that are always merged
            into every fetch() call. Permanent filter keys take precedence
            over runtime params (cannot be overridden by the caller).
        tenant: Optional QuerySource tenant selector, forwarded to QS/MultiQS
            so the slug is resolved against the right tenant schema instead
            of silently falling back to ``public.queries`` (spec AC4).
        is_multiquery: When True, ``fetch()`` dispatches ``MultiQS`` instead
            of ``QS`` and normalises its ``DataFrame | dict[str, DataFrame]``
            output to a single frame (spec S4).
        multi_output: When ``is_multiquery`` is True, the name of the output
            frame to select from a MultiQS dict result. Falls back to
            ``"result"``, then to the single frame when there is only one.
        principal: Optional FEAT-150 ``QSPrincipal`` forwarded to QS/MultiQS
            for in-process slug PBAC enforcement. Never part of ``cache_key``.
        definition: Optional pre-resolved QuerySource ``LoadedDefinition``,
            forwarded to QS/MultiQS.
    """

    def __init__(
        self,
        slug: str,
        prefetch_schema_enabled: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        *,
        tenant: Optional[str] = None,
        is_multiquery: bool = False,
        multi_output: Optional[str] = None,
        principal: Optional["QSPrincipal"] = None,
        definition: Optional["LoadedDefinition"] = None,
    ) -> None:
        self.slug = slug
        self.prefetch_schema_enabled = prefetch_schema_enabled
        self._permanent_filter: Dict[str, Any] = permanent_filter or {}
        self.tenant = tenant
        self.is_multiquery = is_multiquery
        self.multi_output = multi_output
        self._principal = principal
        self._definition = definition
        self.logger = logging.getLogger(__name__)

    def _qs_kwargs(self) -> Dict[str, Any]:
        """Keyword-only QS/MultiQS kwargs (tenant/principal/definition); ``None`` values are omitted."""
        kwargs = {"tenant": self.tenant, "principal": self._principal, "definition": self._definition}
        return {k: v for k, v in kwargs.items() if v is not None}

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this source.

        Returns:
            Cache key in the format ``qs:{slug}``, ``qs:{slug}:f={hash}`` when
            a permanent filter is set, with a ``:t={tenant}`` suffix appended
            when a tenant is set. The principal is NEVER part of the key.
        """
        base = f"qs:{self.slug}"
        if self._permanent_filter:
            suffix = hashlib.md5(json.dumps(self._permanent_filter, sort_keys=True).encode()).hexdigest()[:8]
            base = f"{base}:f={suffix}"
        if self.tenant:
            base = f"{base}:t={self.tenant}"
        return base

    def describe(self) -> str:
        """Human-readable description for the LLM.

        Returns:
            Description string identifying the QuerySource slug.
        """
        desc = f"QuerySource slug '{self.slug}'"
        if self._permanent_filter:
            desc += f" [permanent filter: {self._permanent_filter}]"
        return desc

    async def prefetch_schema(self) -> Dict[str, str]:
        """Fetch one row to infer column names and dtypes.

        Calls QS with ``querylimit=1``. Returns an empty dict silently if the
        call fails or schema prefetch is disabled.

        Returns:
            Dictionary mapping column names to their dtype strings.
        """
        if not self.prefetch_schema_enabled:
            return {}
        if self.is_multiquery:
            return {}  # schema comes from the real fetch; a MultiQuery probe is too costly

        try:
            qs_cls = _get_qs()
            if qs_cls is None:
                return {}
            conditions = {"querylimit": 1, **self._permanent_filter}
            qy = qs_cls(slug=self.slug, conditions=conditions, **self._qs_kwargs())
            try:
                df, error = await qy.query(output_format="pandas")
            finally:
                try:
                    await qy.close()
                except Exception as exc:  # noqa: BLE001 — close must never mask the query outcome
                    self.logger.debug("QS close failed for slug '%s': %s", self.slug, exc)

            if error or not isinstance(df, pd.DataFrame) or df.empty:
                return {}

            return {col: str(dtype) for col, dtype in df.dtypes.items()}

        except Exception as e:
            self.logger.debug("prefetch_schema failed for slug '%s': %s", self.slug, e)
            return {}

    async def fetch(self, **params) -> pd.DataFrame:
        """Execute the QuerySource (or MultiQS) and return a DataFrame.

        Pops ``force_refresh`` from params (not a QS condition) and, when
        True, injects ``refresh=True`` into the QS conditions so that QS
        bypasses its own cache. When ``is_multiquery`` is True, dispatches
        MultiQS instead and normalises its output to a single frame (S4).
        The underlying QS/MultiQS instance is always closed, even on
        failure (S8).

        Args:
            **params: Passed as the ``conditions`` dict to QS/MultiQS.
                force_refresh (bool): If True, tell QS to skip its cache.

        Returns:
            DataFrame with the query results.

        Raises:
            RuntimeError: If QS/MultiQS fails or returns no DataFrame.
        """
        force_refresh = params.pop("force_refresh", False)
        if force_refresh:
            params["refresh"] = True
        # Merge: permanent filter overwrites runtime params
        merged = {**params, **self._permanent_filter}
        self.logger.info("EXECUTING QUERY SOURCE: %s", self.slug)
        if self.is_multiquery:
            qs_cls = _get_multiqs()
        else:
            qs_cls = _get_qs()
        if qs_cls is None:
            raise RuntimeError(
                "querysource package is required for QuerySlugSource. " "Install it with: pip install querysource"
            )
        qy = qs_cls(slug=self.slug, conditions=merged, **self._qs_kwargs())
        try:
            if self.is_multiquery:
                result, _options = await qy.query()
                df = self._select_multi_frame(result)
                error = None
            else:
                df, error = await qy.query(output_format="pandas")
        finally:
            try:
                await qy.close()
            except Exception as exc:  # noqa: BLE001 — close must never mask the query outcome
                self.logger.debug("QS close failed for slug '%s': %s", self.slug, exc)

        if error:
            if isinstance(error, BaseException):
                raise RuntimeError(f"QuerySource slug '{self.slug}' failed: {error}") from error
            raise RuntimeError(f"QuerySource slug '{self.slug}' failed: {error}")

        if not isinstance(df, pd.DataFrame):
            raise RuntimeError(f"QuerySource slug '{self.slug}' did not return a DataFrame")

        return df

    def _select_multi_frame(self, result: Any) -> pd.DataFrame:
        """Normalise MultiQS output to ONE frame: multi_output, else 'result', else the single frame (S4).

        Args:
            result: The ``DataFrame | dict[str, DataFrame] | None`` returned by ``MultiQS.query()``.

        Returns:
            A single ``pd.DataFrame``. An empty/missing result yields an empty ``pd.DataFrame()``.

        Raises:
            RuntimeError: When ``multi_output`` names a frame that is not present, or when the
                result has multiple frames and no ``multi_output`` was specified to disambiguate.
        """
        if result is None:
            return pd.DataFrame()

        frames = result if isinstance(result, dict) else {"result": result}
        if not frames:
            return pd.DataFrame()

        if self.multi_output is not None:
            try:
                frame = frames[self.multi_output]
            except KeyError as exc:
                available = ", ".join(sorted(frames.keys()))
                raise RuntimeError(
                    f"QuerySource multi-query slug '{self.slug}' has no output named "
                    f"'{self.multi_output}' (available: {available})"
                ) from exc
        elif "result" in frames:
            frame = frames["result"]
        elif len(frames) == 1:
            frame = next(iter(frames.values()))
        else:
            available = ", ".join(sorted(frames.keys()))
            raise RuntimeError(
                f"QuerySource multi-query slug '{self.slug}' returned multiple outputs "
                f"({available}); specify multi_output to select one"
            )

        if not isinstance(frame, pd.DataFrame):
            return pd.DataFrame()
        return frame


class MultiQuerySlugSource(DataSource):
    """DataSource backed by multiple QuerySource slugs whose results are merged.

    Fetches each slug independently and concatenates the resulting DataFrames.
    Schema prefetch performs a 1-row fetch per slug and merges the schema dicts.

    Args:
        slugs: List of QuerySource slug identifiers to merge.
    """

    def __init__(self, slugs: List[str]) -> None:
        self.slugs = slugs
        self.logger = logging.getLogger(__name__)

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this multi-slug source.

        Returns:
            Cache key in the format ``multiqs:{slug1}:{slug2}:...`` (slugs sorted).
        """
        return f"multiqs:{':'.join(sorted(self.slugs))}"

    def describe(self) -> str:
        """Human-readable description for the LLM.

        Returns:
            Description string listing all QuerySource slugs.
        """
        return f"Multi-QuerySource slugs: {', '.join(self.slugs)}"

    async def prefetch_schema(self) -> Dict[str, str]:
        """Fetch one row per slug and merge the inferred schemas.

        Returns an empty dict silently for any slug that fails.

        Returns:
            Merged dictionary mapping column names to their dtype strings.
        """
        schema: Dict[str, str] = {}

        for slug in self.slugs:
            try:
                qs_cls = _get_qs()
                if qs_cls is None:
                    continue
                qy = qs_cls(slug=slug, conditions={"querylimit": 1})
                df, error = await qy.query(output_format="pandas")

                if error or not isinstance(df, pd.DataFrame) or df.empty:
                    continue

                schema.update({col: str(dtype) for col, dtype in df.dtypes.items()})

            except Exception as e:
                self.logger.debug("prefetch_schema failed for slug '%s': %s", slug, e)

        return schema

    async def fetch(self, **params) -> pd.DataFrame:
        """Execute all slugs and concatenate the resulting DataFrames.

        Pops ``force_refresh`` from params and, when True, injects
        ``refresh=True`` into each QS conditions dict so that QS bypasses
        its own cache for every slug.

        Args:
            **params: Passed as the ``conditions`` dict to each QS call.
                force_refresh (bool): If True, tell QS to skip its cache.

        Returns:
            Concatenated DataFrame from all slugs.

        Raises:
            RuntimeError: If no slug returns a valid DataFrame.
        """
        force_refresh = params.pop("force_refresh", False)
        if force_refresh:
            params["refresh"] = True
        frames: List[pd.DataFrame] = []

        for slug in self.slugs:
            self.logger.info("EXECUTING QUERY SOURCE: %s", slug)
            try:
                qs_cls = _get_qs()
                if qs_cls is None:
                    raise RuntimeError(
                        "querysource package is required for MultiQuerySlugSource. "
                        "Install it with: pip install querysource"
                    )
                qy = qs_cls(slug=slug, conditions=params)
                df, error = await qy.query(output_format="pandas")

                if error:
                    self.logger.error("QuerySource slug '%s' failed: %s", slug, error)
                    continue

                if not isinstance(df, pd.DataFrame):
                    self.logger.error("QuerySource slug '%s' did not return a DataFrame", slug)
                    continue

                frames.append(df)

            except Exception as e:
                self.logger.error("Failed to load query slug '%s': %s", slug, e)

        if not frames:
            raise RuntimeError(f"MultiQuerySlugSource: no slug returned data for slugs: {self.slugs}")

        return pd.concat(frames, ignore_index=True)


def to_qs_principal(pctx: "PermissionContext", *, channel: str = "ui_surfaces") -> "QSPrincipal":
    """Map a parrot ``PermissionContext`` to a QuerySource ``QSPrincipal`` (FEAT-150).

    Mirrors ``parrot.auth.permission.to_eval_context``: identity from the session, ``groups``/``programs``/
    ``superuser`` from ``session.metadata``. ``tenant_id`` is informational only — it never selects a
    QuerySource store (the descriptor's ``tenant`` does, spec AC4).

    Args:
        pctx: The acting user's permission context (the surface OWNER on ui_surfaces lanes).
        channel: Log-only channel label carried by the principal.

    Returns:
        A frozen ``QSPrincipal``.

    Raises:
        ImportError: When querysource is not installed.
        ValueError: When the context carries a blank user id (QSPrincipal.__post_init__).
    """
    from querysource.auth.principal import QSPrincipal  # lazy: optional extra "db"

    session = pctx.session
    metadata = session.metadata or {}
    return QSPrincipal(
        user_id=session.user_id,
        username=metadata.get("username") or session.user_id,
        groups=tuple(metadata.get("groups", ())),
        roles=tuple(sorted(session.roles)),
        programs=tuple(metadata.get("programs", ())),
        superuser=bool(metadata.get("superuser", False)),
        tenant_id=session.tenant_id,
        channel=channel,
    )
