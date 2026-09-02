from __future__ import annotations
import contextlib
from typing import Optional, Dict, Any, List, TYPE_CHECKING
import pandas as pd
from parrot._imports import lazy_import
from .abstract import AbstractTool
from .pythonrepl import PythonREPLTool, PythonREPLArgs, brace_escape
from .repl_worker import NamespaceTimeoutError, WorkerBootstrapError

if TYPE_CHECKING:
    from .dataset_manager import DatasetManager


def _get_talib_or_none():
    """Return the talib module if available (finance extra), or None."""
    try:
        return lazy_import("talib", package_name="TA-Lib", extra="finance")
    except ImportError:
        return None


class PythonPandasTool(PythonREPLTool):
    """
    Python Pandas Tool with pre-loaded DataFrames and enhanced data science capabilities.

    Extends PythonREPLTool to provide:
    - Automatic DataFrame binding with ORIGINAL names as primary identifiers
    - Standardized aliases (df1, df2, etc.) as convenience references
    - Integration with DatasetManager for catalog/metadata operations
    - Enhanced data exploration utilities
    - Safe DataFrame operations

    All metadata, EDA, column categorization, and data quality
    responsibilities are delegated to DatasetManager when available.
    """

    name = "python_repl_pandas"
    description = "Execute Python code with pre-loaded DataFrames and enhanced pandas capabilities"
    args_schema = PythonREPLArgs

    # Available plotting libraries configuration
    # NOTE (FEAT-423): matplotlib/seaborn are NOT available — they are
    # blocked in the sandbox. Standard charts should be returned as
    # structured data (the system renders them automatically via
    # structured-chart/A2UI); altair is the sole fallback for complex
    # visualizations (heatmaps, correlation matrices, network graphs).
    PLOTTING_LIBRARIES = {
        "plotly": {
            "import_as": "px, go, pio",
            "import_statement": "import plotly.express as px\nimport plotly.graph_objects as go\nimport plotly.io as pio",
            "description": "Interactive web-based plotting library",
            "best_for": ["interactive plots", "dashboards", "web applications"],
            "examples": [
                'fig = px.scatter(df1, x="column1", y="column2", color="category")',
                'fig = px.histogram(df1, x="numeric_column")',
                'fig = go.Figure(data=go.Bar(x=df1["category"], y=df1["value"]))',
                'fig.show()  # Note: may not display in REPL, use fig.write_html("plot.html")',
            ],
        },
        "altair": {
            "import_as": "alt",
            "import_statement": "import altair as alt",
            "description": "Declarative statistical visualization (Grammar of Graphics)",
            "best_for": ["exploratory analysis", "statistical plots", "clean syntax"],
            "examples": [
                'chart = alt.Chart(df1).mark_circle().encode(x="column1", y="column2")',
                'chart = alt.Chart(df1).mark_bar().encode(x="category", y="count()")',
                'chart.show()  # or chart.save("plot.html")',
            ],
        },
    }

    def __init__(
        self,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        dataset_manager: Optional["DatasetManager"] = None,
        df_prefix: str = "df",
        include_sample_data: bool = False,
        sample_rows: int = 3,
        **kwargs,
    ):
        """
        Initialize the Python Pandas tool with DataFrame management.

        Args:
            dataframes: Dictionary of DataFrames to bind {name: DataFrame}.
                        Ignored if dataset_manager is provided (use manager's catalog instead).
            dataset_manager: DatasetManager instance for catalog/metadata operations.
                             When provided, all metadata and catalog management is delegated.
            df_prefix: Prefix for auto-generated DataFrame aliases (default: "df")
            include_sample_data: Include sample data in guide
            sample_rows: Number of sample rows to show
            **kwargs: Additional arguments for PythonREPLTool
        """
        # Configuration
        self.df_prefix = df_prefix
        self.include_sample_data = include_sample_data
        self.sample_rows = sample_rows

        # DatasetManager integration
        self._dataset_manager = dataset_manager
        self._df_guide_cache = ""

        # DataFrame storage - populated from manager or direct input
        if dataset_manager is not None:
            self.dataframes = dataset_manager.get_active_dataframes()
        else:
            self.dataframes = dataframes or {}

        # Execution environment bindings
        self.df_locals = {}

        # Process DataFrames before initializing parent
        self._process_dataframes()

        # Set up locals with DataFrames
        df_locals = kwargs.get("locals_dict", {})
        df_locals.update(self.df_locals)
        kwargs["locals_dict"] = df_locals

        # FEAT-252: pandas agents get the data-analysis execution policy by
        # default (wider pandas/numpy allowlist) instead of the tighter
        # general_profile() the base REPL falls back to.
        if kwargs.get("policy") is None:
            from parrot.security.python_sanitizer import data_analysis_profile

            kwargs["policy"] = data_analysis_profile()

        # Initialize parent class
        super().__init__(**kwargs)

        # Update description with loaded DataFrames
        self._update_description()

    async def _get_worker_handle(self):
        """Acquire this instance's worker, seeding new `df_locals` into it first.

        FEAT-380 (TASK-1944): ports the old ``locals_dict``/``clone()``
        constructor-time merge (`:122, :128-130` in the pre-worker code) to
        worker seeding — the worker's `PythonREPLTool` instance has its own,
        separate namespace (TASK-1943), so `df_locals` entries (DataFrames
        + row/col-count/shape/columns metadata from `_process_dataframes`)
        are pushed in via the namespace API instead of a constructor kwarg.
        Diffs against `_seeded_df_names` so it's a cheap no-op once
        everything currently in `df_locals` has been pushed, while still
        picking up anything added later via `register_dataframes()`/
        `sync_from_manager()`.

        FEAT-380 (TASK-1945): actual DataFrame values go through
        ``inject_dataframe()`` (Arrow IPC/shm, pickle-fallback-with-warning)
        instead of ``set_var()`` (which always pickles, TASK-1940's
        ``encode_value``) — the scalar metadata entries
        (``*_row_count``/``*_col_count``/``*_shape``/``*_columns``) stay on
        ``set_var()`` since they're not DataFrames.

        Code-review fix (post-TASK-1945): ``_seeded_df_names`` is only ever
        ADDED to, never cleared here — but the pool can silently swap in a
        brand-new worker for the same ``session_id`` behind this method's
        back (crash restart, TTL eviction, deadline kill; TASK-1942's
        crash-restart path). The fresh worker's namespace is empty, yet
        every name already marked "seeded" against the now-dead worker
        would be skipped, so the DataFrames would just silently vanish from
        what the LLM sees. Detect the swap by identity (a restarted worker
        is a new ``WorkerHandle`` object) and reseed everything when it
        happens.
        """
        handle = await super()._get_worker_handle()
        if id(handle) != self._seeded_worker_handle_id:
            self._seeded_df_names = set()
            self._seeded_worker_handle_id = id(handle)
        new_names = set(self.df_locals) - self._seeded_df_names
        if new_names:
            for name in new_names:
                value = self.df_locals[name]
                try:
                    if isinstance(value, pd.DataFrame):
                        await handle.inject_dataframe(name, value)
                    else:
                        await handle.set_var(name, value)
                except (NamespaceTimeoutError, WorkerBootstrapError) as exc:
                    # FEAT-500 (G3): seeding is the step that used to fail
                    # first and blankest on a cold worker. Say WHICH variable
                    # failed, and keep the exception type so callers that
                    # branch on TimeoutError still match.
                    raise type(exc)(f"seeding {name!r} into the REPL worker failed: {exc}") from exc
            self._seeded_df_names |= new_names
        return handle

    def reset_environment(self) -> None:
        """Reset the REPL environment — also re-seeds `df_locals` on next use.

        FEAT-380 (TASK-1944): a reset kills and replaces the worker
        (`PythonREPLTool.reset_environment`), so the DataFrames must be
        re-pushed into the fresh worker's empty namespace.
        """
        super().reset_environment()
        self._seeded_df_names = set()
        self._seeded_worker_handle_id = None

    # ─────────────────────────────────────────────────────────────
    # Session Isolation
    # ─────────────────────────────────────────────────────────────

    def create_session_clone(
        self,
        dataset_manager: Optional["DatasetManager"] = None,
    ) -> "PythonPandasTool":
        """Create a lightweight, session-isolated clone of this tool.

        The clone shares the heavy infrastructure (library imports,
        executor) but gets its own ``locals`` / ``globals`` dicts so
        concurrent requests cannot overwrite each other's DataFrames.

        Eagerly-loaded DataFrames from the source tool are **copied**
        into the clone's namespace.  Table-source DataFrames are NOT
        copied (they are query-specific and must be fetched per-turn).

        Args:
            dataset_manager: Session-scoped DatasetManager.  When provided
                the clone will use it for alias maps and sync callbacks.
                When *None*, inherits from the source tool.

        Returns:
            A new PythonPandasTool instance with isolated execution state.
        """
        dm = dataset_manager or self._dataset_manager

        # Build a new instance via __new__ to skip the heavy
        # PythonREPLTool.__init__ (optional-lib imports, _bootstrap). Call
        # AbstractTool.__init__ directly so every base
        # attribute (routing_meta, executor, webhook_callback_url,
        # remote_timeout_seconds, event registry, json codecs, …) stays in
        # sync with the parent class without manual mirroring.
        clone = object.__new__(PythonPandasTool)
        AbstractTool.__init__(
            clone,
            name=self.name,
            description=self.description,
            output_dir=str(self.output_dir) if self.output_dir else None,
            base_url=self.base_url,
            static_dir=str(self.static_dir),
            routing_meta=dict(self.routing_meta),
            executor=getattr(self, "executor", None),
            webhook_callback_url=getattr(self, "webhook_callback_url", None),
            remote_timeout_seconds=getattr(self, "remote_timeout_seconds", 300),
        )

        # ── Copy PythonPandasTool-specific config ──
        clone.args_schema = self.args_schema
        clone.df_prefix = self.df_prefix
        clone.include_sample_data = self.include_sample_data
        clone.sample_rows = self.sample_rows
        clone._dataset_manager = dm
        clone._df_guide_cache = ""

        # ── Share PythonREPLTool infrastructure (read-only / thread-safe) ──
        clone.sanitize_input_enabled = self.sanitize_input_enabled
        # The code sanitizer is a stateless validator; share it so the clone's
        # _execute_code AST gate works. Without this, every sanitized run raised
        # AttributeError: 'PythonPandasTool' object has no attribute
        # '_code_sanitizer' (the clone skips PythonREPLTool.__init__).
        clone._code_sanitizer = self._code_sanitizer
        clone.setup_code = self.setup_code
        clone.debug = self.debug
        clone.BLOCKED_IMPORTS = self.BLOCKED_IMPORTS
        # Code-review fix (post-TASK-1945 AC1 wiring): `_acquire_worker_pool()`
        # now reads `self._repl_executor` unconditionally to route worker I/O
        # through it (Module 1's dedicated, bounded pool) — a clone built via
        # `object.__new__()` skipping `PythonREPLTool.__init__()` never had
        # this attribute, so the first worker touch on any clone raised
        # `AttributeError`. This class's own docstring already promises the
        # clone "shares the heavy infrastructure (... executor)" with the
        # source tool, so share the SAME dedicated pool rather than spawning
        # a fresh one per clone.
        clone._repl_executor = self._repl_executor

        # ── FEAT-380 (TASK-1944): worker identity, NOT shared with source ──
        # The clone is explicitly about session isolation — it must get its
        # OWN worker (own session_id, own lazily-created pool), never the
        # source tool's, or two "isolated" sessions would collide on the same
        # underlying worker process (defeating G7/the whole point of this
        # method). `PythonREPLTool.__init__` normally sets these; this clone
        # bypasses `__init__` entirely (see comment above), so they're set
        # here instead.
        import uuid as _uuid

        clone._session_id = f"pythonrepl-{_uuid.uuid4().hex}"
        clone._worker_config = getattr(self, "_worker_config", None)
        clone._worker_pool = None
        clone._pending_worker_reset = False
        clone._worker_repl_kwargs = dict(getattr(self, "_worker_repl_kwargs", {}) or {})
        clone._seeded_df_names = set()
        clone._seeded_worker_handle_id = None

        # ── Isolated execution state ──
        # Start with a COPY of the source's locals/globals so the clone
        # inherits library imports (pd, np, plt, …) and utility functions.
        clone.locals = dict(self.locals)
        clone.globals = dict(self.globals)

        # Fresh execution_results per session
        clone.locals["execution_results"] = {}
        clone.globals["execution_results"] = {}

        # ── Sync DataFrames from the session DM ──
        clone.dataframes = {}
        # FEAT-380 (TASK-1944): seed `df_locals` with the source's
        # eagerly-loaded DataFrames as the baseline (this is what
        # `_get_worker_handle()`'s worker-seeding diffs against — without
        # this, a clone created with no `dataset_manager` would get an
        # empty worker namespace, contradicting this method's own docstring
        # promise that "eagerly-loaded DataFrames... are copied"). The `dm`
        # branch below fully rebuilds `df_locals` from the DM's active set
        # when present, superseding this baseline (table-source DataFrames
        # are query-specific and must be re-fetched per session, per the
        # docstring).
        clone.df_locals = dict(self.df_locals)
        if dm:
            active_dfs = dm.get_active_dataframes()
            clone.dataframes = active_dfs
            alias_map = dm._get_alias_map()
            clone._process_dataframes(alias_map=alias_map)
            clone.locals.update(clone.df_locals)
            clone.globals.update(clone.df_locals)

        clone._update_description()
        return clone

    # ─────────────────────────────────────────────────────────────
    # DatasetManager Integration
    # ─────────────────────────────────────────────────────────────

    @property
    def dataset_manager(self) -> Optional["DatasetManager"]:
        """Access the DatasetManager instance."""
        return self._dataset_manager

    @dataset_manager.setter
    def dataset_manager(self, manager: "DatasetManager") -> None:
        """Set or replace the DatasetManager and sync dataframes."""
        self._dataset_manager = manager
        self.sync_from_manager()

    @property
    def df_guide(self) -> str:
        """Get the DataFrame guide from DatasetManager or cached value."""
        if self._dataset_manager:
            return self._dataset_manager.get_guide()
        return self._df_guide_cache

    @df_guide.setter
    def df_guide(self, value: str) -> None:
        """Set guide cache for standalone mode."""
        self._df_guide_cache = value

    def sync_from_manager(self) -> None:
        """
        Synchronize execution environment from DatasetManager's active datasets.

        Call this after adding/removing/activating/deactivating datasets
        in the DatasetManager to refresh the execution bindings.
        """
        if not self._dataset_manager:
            return

        # Clear old bindings
        self.clear_dataframes()

        # Get active DataFrames from manager
        self.dataframes = self._dataset_manager.get_active_dataframes()

        if not self.dataframes:
            return

        # Use stable alias map from DatasetManager
        alias_map = self._dataset_manager._get_alias_map()

        # Rebind to execution environment
        self._process_dataframes(alias_map=alias_map)
        self.locals.update(self.df_locals)
        self.globals.update(self.df_locals)

        # Update description
        self._update_description()

    def _rebind_drifted_dataframes(self) -> None:
        """Bind active DatasetManager DataFrames missing from the REPL namespace.

        Fetched/materialized datasets are normally pushed into the REPL by the
        DatasetManager ``on_change`` callback. Session-scoped tool and manager
        swapping (one ``DatasetManager`` instance owns the dataset tools,
        another owns the sync callback) can race, so a just-fetched DataFrame
        is occasionally absent on the next ``python_repl_pandas`` execution and
        surfaces as a ``NameError``.

        This makes the tool self-healing: when a dataset that is active in the
        attached ``DatasetManager`` is missing (by name) from ``self.locals``,
        the full active set is re-registered. ``register_dataframes`` only
        clears the previously-registered dataset bindings (``df_locals``), so
        variables the LLM computed earlier in the session are preserved.
        """
        dm = self._dataset_manager
        if dm is None:
            return
        try:
            active = dm.get_active_dataframes()
        except Exception as exc:  # never break execution over a sync hiccup
            self.logger.debug("Active-dataframe drift check skipped: %s", exc)
            return
        if not active:
            return
        drifted = [name for name in active if name not in self.locals]
        if not drifted:
            return
        self.logger.debug(
            "Re-binding %d drifted DataFrame(s) into REPL namespace: %s",
            len(drifted),
            drifted,
        )
        self.register_dataframes(active, alias_map=dm._get_alias_map())

    # ─────────────────────────────────────────────────────────────
    # Description & Plotting Guide
    # ─────────────────────────────────────────────────────────────

    def _update_description(self) -> None:
        """Update tool description to include available DataFrames."""
        df_summary = (
            ", ".join([f"{df_key}: {df.shape[0]} rows × {df.shape[1]} cols" for df_key, df in self.dataframes.items()])
            if self.dataframes
            else "No DataFrames"
        )

        self.description = (
            f"Execute Python code with pandas DataFrames. "
            f"Available data: {df_summary}. "
            f"Use df1, df2, etc. to access DataFrames."
        )

    def _generate_plotting_guide(self) -> str:
        """Generate comprehensive plotting libraries guide for the LLM."""
        guide_parts = ["# Plotting Libraries Guide", "", "## Available Libraries", ""]

        for lib_name, lib_info in self.PLOTTING_LIBRARIES.items():
            guide_parts.extend(
                [
                    f"### {lib_name.title()}",
                    f"**Import**: `{lib_info['import_statement']}`",
                    f"**Best for**: {', '.join(lib_info['best_for'])}",
                    "",
                    "**Examples**:",
                ]
            )
            guide_parts.extend(f"- `{example}`" for example in lib_info["examples"])
            guide_parts.append("")

        # Add general recommendations
        guide_parts.extend(
            [
                "## General Tips",
                "- matplotlib and seaborn are NOT available — for standard charts,",
                "  return the data as a dict/DataFrame; the system renders it",
                "  automatically via structured-chart/A2UI.",
                "- For interactive plots: Use plotly and save as HTML",
                "- For complex visualizations only (heatmaps, correlation matrices,",
                "  network graphs): use altair and return `.to_dict()`",
                "- For large datasets: Consider aggregation or sampling first",
                "",
            ]
        )

        return "\n".join(guide_parts)

    # ─────────────────────────────────────────────────────────────
    # DataFrame Processing (Execution Environment Binding)
    # ─────────────────────────────────────────────────────────────

    def _process_dataframes(
        self,
        alias_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """Process and bind DataFrames to the local environment.

        IMPORTANT:
        Original names are the PRIMARY identifiers, aliases are CONVENIENCE references.

        This method only handles execution environment binding.
        Metadata and catalog management is handled by DatasetManager.

        Args:
            alias_map: Optional mapping of dataset name → stable alias
                       (e.g. from DatasetManager._get_alias_map()).  When
                       provided, aliases are taken from this map so they stay
                       consistent with what ``list_datasets`` reports.
                       When *None*, a sequential ``df1, df2, …`` is generated
                       from the loaded-only dict (legacy behaviour).
        """
        self.df_locals = {}
        # FEAT-380 (TASK-1944): `df_locals` is being rebuilt from scratch —
        # invalidate the worker-seeding tracker (`_get_worker_handle()`) too,
        # since a name that was already pushed to the worker may now map to
        # a DIFFERENT DataFrame object (a refresh/drift re-sync). Set
        # unconditionally (works whether or not the attribute exists yet —
        # this runs once from `__init__`, before `super().__init__()` has
        # even set up the rest of the worker-related state). Also seeds
        # `_seeded_worker_handle_id` (code-review fix) so `_get_worker_handle()`
        # can compare against it unconditionally, without a `getattr` guard.
        self._seeded_df_names: set = set()
        self._seeded_worker_handle_id: Optional[int] = None

        for i, (df_name, df) in enumerate(self.dataframes.items()):
            # Use stable alias from DatasetManager when available,
            # otherwise fall back to sequential numbering.
            df_alias = alias_map.get(df_name, f"{self.df_prefix}{i + 1}") if alias_map else f"{self.df_prefix}{i + 1}"

            # Bind DataFrame with both original name and standardized key
            self.df_locals[df_name] = df  # PRIMARY: Original name
            self.df_locals[df_alias] = df  # ALIAS: Convenience reference

            for key in [df_name, df_alias]:
                self.df_locals[f"{key}_row_count"] = len(df)
                self.df_locals[f"{key}_col_count"] = len(df.columns)
                self.df_locals[f"{key}_shape"] = df.shape
                self.df_locals[f"{key}_columns"] = df.columns.tolist()

    # ─────────────────────────────────────────────────────────────
    # DataFrame Management (Execution Environment Operations)
    # ─────────────────────────────────────────────────────────────

    def add_dataframe(self, name: str, df: pd.DataFrame) -> str:
        """
        Add a new DataFrame to the execution environment.

        If a DatasetManager is attached, also registers it in the catalog.

        Args:
            name: Name for the DataFrame
            df: The DataFrame to add

        Returns:
            Success message with DataFrame key
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Object must be a pandas DataFrame")

        # Register in DatasetManager if available
        if self._dataset_manager:
            self._dataset_manager.add_dataframe(name, df)
            self.sync_from_manager()
        else:
            # Direct management (no DatasetManager)
            self.dataframes[name] = df
            self._process_dataframes()
            self.locals.update(self.df_locals)
            self.globals.update(self.df_locals)

        # Find the alias for this DataFrame
        if self._dataset_manager:
            am = self._dataset_manager._get_alias_map()
            df_alias = am.get(name)
        else:
            df_alias = next(
                (
                    f"{self.df_prefix}{i + 1}"
                    for i, (df_name, _) in enumerate(self.dataframes.items())
                    if df_name == name
                ),
                None,
            )

        # Update description
        self._update_description()

        return f"DataFrame '{name}' added successfully (alias: '{df_alias}')"

    def remove_dataframe(self, name: str) -> str:
        """
        Remove a DataFrame from the execution environment.

        If a DatasetManager is attached, also removes it from the catalog.

        Args:
            name: Name of the DataFrame to remove

        Returns:
            Success message
        """
        if self._dataset_manager:
            # Resolve alias via manager
            resolved_name = self._dataset_manager._resolve_name(name)
            self._dataset_manager.remove(resolved_name)
            self.sync_from_manager()
        else:
            # Direct management - resolve alias to original name
            resolved_name = next(
                (
                    df_name
                    for i, (df_name, _) in enumerate(self.dataframes.items())
                    if f"{self.df_prefix}{i + 1}" == name
                ),
                name,
            )

            if resolved_name not in self.dataframes:
                raise ValueError(f"DataFrame '{name}' not found")

            del self.dataframes[resolved_name]
            self._process_dataframes()
            self.locals.update(self.df_locals)
            self.globals.update(self.df_locals)

        # Update description
        self._update_description()

        return f"DataFrame '{resolved_name}' removed successfully"

    def register_dataframes(
        self,
        dataframes: Dict[str, pd.DataFrame],
        alias_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Register DataFrames to the tool execution environment.

        Clears any previously registered DataFrames and binds the new ones.
        This is the preferred method for DatasetManager integration.

        Args:
            dataframes: Dictionary mapping names to DataFrames
            alias_map: Optional stable alias mapping from DatasetManager
                       (name → alias like ``df3``).  Ensures aliases in the
                       REPL match what ``list_datasets`` advertises.
        """
        # Clear old DataFrame references from locals
        self.clear_dataframes()

        # Set new dataframes
        self.dataframes = dataframes or {}

        # Skip if no dataframes
        if not self.dataframes:
            return

        # Process and bind to environment
        self._process_dataframes(alias_map=alias_map)
        self.locals.update(self.df_locals)
        self.globals.update(self.df_locals)

        # Update description
        self._update_description()

    def clear_dataframes(self) -> None:
        """
        Clear all registered DataFrames from the execution environment.

        Removes DataFrame references from locals/globals and resets internal state.

        FEAT-380 (TASK-1944) limitation: this only clears the HOST-side
        bookkeeping (`.locals`/`.globals`, kept for backward-compat readers
        per TASK-1943) and the worker-seeding tracker. The namespace API
        (TASK-1943) has no `del_var`/`unset_var` — there is currently no way
        to remove an already-pushed variable from a LIVE worker's namespace
        short of a full `reset_environment()` (which clears everything, not
        just DataFrames). Names cleared here are simply not re-pushed until
        `register_dataframes()`/`sync_from_manager()` runs again; if the
        worker is still alive, it keeps serving the old values in the
        meantime. Extending the namespace API with an unset primitive is a
        candidate follow-up, out of this task's scope.
        """
        # Remove old df_locals entries from locals/globals
        for key in list(self.df_locals.keys()):
            self.locals.pop(key, None)
            self.globals.pop(key, None)

        # Clear internal state
        self.dataframes = {}
        self.df_locals = {}
        self._seeded_df_names = set()
        self._df_guide_cache = ""

    # ─────────────────────────────────────────────────────────────
    # Delegated Methods (use DatasetManager when available)
    # ─────────────────────────────────────────────────────────────

    def get_dataframe_guide(self) -> str:
        """Get the current DataFrame guide."""
        return self.df_guide

    def list_dataframes(self) -> Dict[str, Dict[str, Any]]:
        """
        List all available DataFrames with their info.

        Delegates to DatasetManager if available, otherwise returns basic info.
        """
        if self._dataset_manager:
            return self._dataset_manager.list_dataframes()

        # Fallback: basic info without DatasetManager
        result = {}
        for i, (df_name, df) in enumerate(self.dataframes.items()):
            df_alias = f"{self.df_prefix}{i + 1}"
            result[df_name] = {
                "original_name": df_name,
                "alias": df_alias,
                "shape": df.shape,
                "columns": df.columns.tolist(),
                "memory_usage_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
                "null_count": int(df.isnull().sum().sum()),
            }
        return result

    def get_dataframe_summary(self, df_key: str) -> Dict[str, Any]:
        """
        Get detailed summary for a specific DataFrame.

        Delegates to DatasetManager if available.
        """
        if self._dataset_manager:
            return self._dataset_manager.get_dataframe_summary(df_key)

        # Fallback: resolve alias and return basic info
        resolved = df_key
        if df_key not in self.dataframes:
            # Try resolving as alias
            for i, (name, _) in enumerate(self.dataframes.items()):
                if f"{self.df_prefix}{i + 1}" == df_key:
                    resolved = name
                    break

        if resolved not in self.dataframes:
            available = list(self.dataframes.keys())
            raise ValueError(f"DataFrame '{df_key}' not found. Available: {available}")

        df = self.dataframes[resolved]
        return {
            "shape": df.shape,
            "columns": df.columns.tolist(),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "memory_usage_bytes": df.memory_usage(deep=True).sum(),
            "null_counts": df.isnull().sum().to_dict(),
            "row_count": len(df),
            "column_count": len(df.columns),
        }

    # ─────────────────────────────────────────────────────────────
    # Environment Setup
    # ─────────────────────────────────────────────────────────────

    def _setup_environment(self) -> None:
        """Override to add DataFrame-specific utilities."""
        # Call parent setup first
        super()._setup_environment()

        # Add DataFrame-specific utilities
        def list_available_dataframes():
            """List all available DataFrames."""
            return self.list_dataframes()

        def get_df_guide():
            """Get the DataFrame guide."""
            return self.get_dataframe_guide()

        def get_plotting_guide():
            """Get the plotting libraries guide."""
            return self._generate_plotting_guide()

        def quick_eda(df_key: str):
            """Quick exploratory data analysis for a DataFrame."""
            if self._dataset_manager:
                try:
                    summary = self._dataset_manager.get_dataframe_summary(df_key)
                    print(f"=== Quick EDA for {df_key} ===")
                    print(f"Shape: {summary.get('shape')}")
                    print(f"Columns: {summary.get('columns')}")
                    print(f"\nData Types:")
                    for col, dtype in summary.get("dtypes", {}).items():
                        print(f"  {col}: {dtype}")
                    if "column_types" in summary:
                        print(f"\nColumn Categories:")
                        for col, cat in summary["column_types"].items():
                            print(f"  {col}: {cat}")
                    print(f"\nNull Counts:")
                    for col, count in summary.get("null_counts", {}).items():
                        if count > 0:
                            print(f"  {col}: {count}")
                    return f"EDA completed for {df_key}"
                except ValueError:
                    return f"DataFrame '{df_key}' not found."

            # Fallback without DatasetManager
            if df_key not in self.df_locals:
                return f"DataFrame '{df_key}' not found. Available: {list(self.dataframes.keys())}"

            df = self.df_locals[df_key]

            print(f"=== Quick EDA for {df_key} ===")
            print(f"Shape: {df.shape}")
            print(f"Columns: {df.columns.tolist()}")
            print(f"\nData Types:")
            print(df.dtypes)
            print(f"\nMissing Values:")
            print(df.isnull().sum())
            print(f"\nSample Data:")
            print(df.head())

            return f"EDA completed for {df_key}"

        # Add to locals
        self.locals.update(
            {
                "list_available_dataframes": list_available_dataframes,
                "get_df_guide": get_df_guide,
                "quick_eda": quick_eda,
                "get_plotting_guide": get_plotting_guide,
                "talib": _get_talib_or_none(),
            }
        )

        # Update globals
        self.globals.update(self.locals)

    def _get_default_setup_code(self) -> str:
        """Override to include DataFrame-specific setup."""
        base_setup = super()._get_default_setup_code()

        # Generate the DataFrame info statically since we know the DataFrames at this point
        df_count = len(self.dataframes)
        df_info_lines = []

        if df_count > 0:
            df_info_lines.append("print('📊 Available DataFrames:')")
            for i, (name, df) in enumerate(self.dataframes.items()):
                df_alias = f"{self.df_prefix}{i + 1}"
                shape = df.shape
                df_info_lines.append(
                    f"print('  - {name} (alias: {df_alias}): " f"{shape[0]} rows × {shape[1]} columns')"
                )

        df_info_code = "\n".join(df_info_lines)

        df_setup = f"""
# DataFrame-specific setup
print("📊 DataFrames loaded: {df_count}")
{df_info_code}
print("💡 TIP: Use original names (e.g., 'bi_sales') or aliases (e.g., 'df1')")
print("🔧 Utilities: list_available_dataframes(), get_df_guide(), quick_eda()")
print("📈 TA-Lib: available as 'talib' (requires ai-parrot[finance])")
"""

        return base_setup + df_setup

    # ─────────────────────────────────────────────────────────────
    # Execution State
    # ─────────────────────────────────────────────────────────────

    def get_environment_info(self) -> Dict[str, Any]:
        """Override to include DataFrame information."""
        info = super().get_environment_info()
        info.update(
            {
                "dataframes_count": len(self.dataframes),
                "dataframes": self.list_dataframes(),
                "df_prefix": self.df_prefix,
                "has_dataset_manager": self._dataset_manager is not None,
                "guide_generated": bool(self.df_guide),
            }
        )
        return info

    def get_execution_state(self) -> Dict[str, Any]:
        """
        Extract current execution state for use by formatters.

        Returns:
            Dictionary containing:
            - execution_results: All stored results
            - dataframes: Dict of available DataFrames
            - variables: Other variables from execution
        """
        state = {"execution_results": self.locals.get("execution_results", {}), "dataframes": {}, "variables": {}}

        # Extract DataFrames
        for name, df in self.dataframes.items():
            state["dataframes"][name] = df
            # Also include by alias
            for i, (df_name, _) in enumerate(self.dataframes.items()):
                if df_name == name:
                    alias = f"{self.df_prefix}{i + 1}"
                    state["dataframes"][alias] = df
                    break

        # Extract other relevant variables (excluding functions, modules)
        for key, value in self.locals.items():
            if (
                not key.startswith("_")
                and not callable(value)
                and (key not in ["execution_results"] and not key.endswith("_row_count"))
            ):
                with contextlib.suppress(Exception):
                    # Only include serializable or DataFrame-like objects
                    if isinstance(value, (str, int, float, bool, list, dict, pd.DataFrame, pd.Series)):
                        state["variables"][key] = value

        return state

    def clear_execution_results(self):
        """Clear execution_results dictionary for new queries."""
        if "execution_results" in self.locals:
            self.locals["execution_results"].clear()

    # ─────────────────────────────────────────────────────────────
    # Execution (with data quality checks via DatasetManager)
    # ─────────────────────────────────────────────────────────────

    async def _execute(self, code: str, debug: bool = False, **kwargs) -> Any:
        """
        Execute Python code with DataFrame-specific enhancements.

        Overrides parent to check for NaNs in debug mode via DatasetManager.
        Also appends a preview of any new/modified DataFrames to the output,
        and includes the executed code for audit purposes.
        """
        # Self-heal the REPL namespace before running user code: a dataset
        # fetched/materialized earlier in this turn must be visible here even
        # if the DatasetManager on_change sync raced with session-scoped tool/
        # manager swapping (one DM instance owns the tools, another owns the
        # sync callback). Otherwise a just-fetched DataFrame surfaces as a
        # NameError on the next python_repl_pandas call.
        self._rebind_drifted_dataframes()

        # Snapshot current namespace var names to identify new variables.
        #
        # Code-review fix (post-TASK-1943): `self.locals` on this HOST
        # instance no longer reflects the executed code's actual namespace —
        # since Module 5 (worker-process isolation), code runs in a
        # separate persistent worker process with its own, separate
        # `locals`/`globals` (`PythonREPLTool._execute()`/`WorkerHandle`).
        # Diffing `self.locals` here was permanently a no-op (`pre_keys` and
        # `current_keys` below were always identical, since neither is ever
        # touched by execution anymore) — silently disabling the "B.
        # DataFrame Preview" half of the audit block for every call.
        # `list_vars()`/`get_var()` (the namespace API, TASK-1943/1940) are
        # the only way to see the worker's real namespace from here.
        try:
            pre_keys = set(await self.list_vars())
        except Exception as exc:  # noqa: BLE001 - diagnostics probe, never fatal
            # FEAT-500 (G3/G5): still non-fatal, but no longer silent — this
            # is where a struggling worker first shows up.
            self.logger.debug("python_repl_pandas: namespace probe failed: %s", exc)
            pre_keys = set()

        result = await super()._execute(code, debug=debug, **kwargs)

        # ── NameError recovery: tell the LLM which variables actually exist ──
        if isinstance(result, str) and "NameError" in result:
            available_names = list(self.dataframes.keys())
            available_aliases = [f"{self.df_prefix}{i + 1}" for i in range(len(self.dataframes))]
            all_vars = available_names + available_aliases
            if all_vars:
                result += f"\n\nAvailable DataFrame variables: {all_vars}. " f"Use one of these exact names."
            else:
                result += (
                    "\n\nNo DataFrames are currently loaded in "
                    "python_repl_pandas. You must call "
                    "fetch_dataset(name='<dataset_name>') first, then use "
                    "the python_variable from the response. "
                    "Use get_metadata(name='<dataset_name>') to discover "
                    "available columns before writing queries."
                )

        # 1. Automatic Audit (Code + Data Preview)
        try:
            audit_parts = []

            # A. Executed Code Echo
            # Always informative to see what logic was applied, especially for filters.
            # We format it as a block.
            audit_parts.append(f"\n📝 [AUDIT] Executed Code:\n```python\n{code.strip()}\n```")

            # B. DataFrame Preview
            # Check for new or modified DataFrames to assist debugging
            # (code-review fix: see `pre_keys` comment above — query the
            # worker's real namespace, not the stale host-side `self.locals`).
            try:
                current_keys = set(await self.list_vars())
            except Exception as exc:  # noqa: BLE001 - diagnostics probe, never fatal
                self.logger.debug("python_repl_pandas: namespace probe failed: %s", exc)
                current_keys = set()
            new_keys = current_keys - pre_keys

            for key in new_keys:
                if key.startswith("_"):
                    continue

                try:
                    val = await self.get_var(key)
                except Exception as exc:  # noqa: BLE001 - diagnostics probe, never fatal
                    self.logger.debug(
                        "python_repl_pandas: reading %r for the audit preview failed: %s",
                        key,
                        exc,
                    )
                    continue
                if isinstance(val, pd.DataFrame) and not val.empty:
                    audit_parts.append(f"\n🔍 [AUDIT] Preview of '{key}' (first 3 rows):")
                    try:
                        # Use strict float formatting to avoid scientific notation if possible
                        preview = val.head(3).to_string(index=False)
                    except Exception:
                        preview = str(val.head(3))
                    audit_parts.append(preview)

            if audit_parts:
                # Append to result
                debug_text = "\n".join(audit_parts)
                if isinstance(result, str):
                    result += debug_text

        except Exception as e:
            self.logger.warning(f"Failed to generate DataFrame/Code preview: {e}")

        # 2. Debug Mode NaN Checks
        # If execution was successful and we are in debug mode
        if debug and isinstance(result, str) and not result.startswith("ToolError"):
            try:
                # Check for NaNs via DatasetManager or fallback
                nan_warnings = self._get_nan_warnings()

                if nan_warnings:
                    warnings_text = "\n\n⚠️  [DEBUG] Data Quality Warnings:\n" + "\n".join(nan_warnings)
                    result += warnings_text

            except Exception as e:
                self.logger.error(f"Error checking for NaNs: {e}")
                if debug:
                    result += f"\n\n⚠️  [DEBUG] Error checking data quality: {e}"

        return result

    def _get_nan_warnings(self) -> List[str]:
        """
        Get NaN warnings from DatasetManager or compute directly.

        Returns:
            List of warning messages describing where NaNs were found.
        """
        if self._dataset_manager:
            return self._dataset_manager.check_dataframes_for_nans()

        # Fallback: check directly on self.dataframes
        warnings = []
        for name, df in self.dataframes.items():
            try:
                if df.empty:
                    continue

                null_counts = df.isnull().sum()
                total_rows = len(df)
                cols_with_nulls = null_counts[null_counts > 0]

                if not cols_with_nulls.empty:
                    for col_name, count in cols_with_nulls.items():
                        percentage = (count / total_rows) * 100
                        warnings.append(
                            f"- DataFrame '{name}' (column '{col_name}'): "
                            f"Contains {count} NaNs ({percentage:.1f}% of {total_rows} rows)"
                        )
            except Exception:
                pass

        return warnings
