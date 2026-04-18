"""
NavigatorToolkit for AI-Parrot - Manage Navigator Programs, Modules, Dashboards & Widgets.

This toolkit provides tools for:
- Creating and updating Programs (auth.programs)
- Creating and updating Modules with menu hierarchy (navigator.modules)
- Creating, updating, and cloning Dashboards (navigator.dashboards)
- Creating and updating Widgets with template inheritance (navigator.widgets)
- Managing permissions (client_modules, modules_groups, program_clients, program_groups)
- Listing widget types, categories, clients, and groups
- Searching across all Navigator entities
- Retrieving full program structure (program → modules → dashboards → widgets)

Refactored (FEAT-106 / TASK-744): inherits PostgresToolkit instead of AbstractToolkit.
DB plumbing delegated to parent (asyncdb pool via _acquire_asyncdb_connection).
"""
import json
import os
import uuid as _uuid
from typing import Any, Dict, List, Optional
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.tools.decorators import tool_schema
from .schemas import (
    ProgramCreateInput,
    ProgramUpdateInput,
    ModuleCreateInput,
    ModuleUpdateInput,
    DashboardCreateInput,
    DashboardUpdateInput,
    WidgetCreateInput,
    WidgetUpdateInput,
    CloneDashboardInput,
    AssignModuleClientInput,
    AssignModuleGroupInput,
    EntityLookupInput,
    SearchInput,
)


class NavigatorToolkit(PostgresToolkit):
    """Toolkit for managing the Navigator platform.

    Provides tools for full lifecycle management of Programs, Modules,
    Dashboards and Widgets, including permissions and search.

    Inherits PostgresToolkit (FEAT-106) — DB connection managed by parent
    via asyncdb pool.  All write tools require ``read_only=False``
    (default for NavigatorToolkit: always False).

    Example usage::

        toolkit = NavigatorToolkit(dsn="postgres://user:pw@host/db")
        tools = toolkit.get_tools()  # nav_create_program, nav_get_program, …
    """

    tool_prefix: str = "nav"

    # The 13 tables used by Navigator tools (whitelist for CRUD methods)
    _NAVIGATOR_TABLES: List[str] = [
        "auth.programs",
        "auth.program_clients",
        "auth.program_groups",
        "auth.clients",
        "auth.groups",
        "auth.user_groups",
        "navigator.modules",
        "navigator.client_modules",
        "navigator.modules_groups",
        "navigator.dashboards",
        "navigator.widgets",
        "navigator.widgets_templates",
        "navigator.widget_types",
    ]

    def __init__(
        self,
        dsn: str = "",
        default_client_id: int = 1,
        user_id: Optional[int] = None,
        confirm_execution: bool = False,
        page_index: Optional[Any] = None,
        builder_groups: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        # Reject the removed parameter early with a helpful error
        if "connection_params" in kwargs:
            raise TypeError(
                "NavigatorToolkit: connection_params= was removed; "
                "pass dsn='postgres://…' instead. "
                "See FEAT-106 migration notes."
            )

        # Block raw CRUD + schema tools inherited from PostgresToolkit/SQLToolkit.
        # NavigatorToolkit intentionally exposes only its own business-logic tools
        # (nav_create_program, nav_get_module, …) — not bare database primitives.
        # Exposing nav_insert_row / nav_execute_query etc. to the LLM would bypass
        # authorization guardrails (_check_program_access, _require_superuser, …).
        # CRITICAL: must be set before super().__init__ which calls _generate_tools().
        _raw_inherited: tuple[str, ...] = (
            "insert_row", "upsert_row", "update_row", "delete_row", "select_rows",
            "execute_query", "search_schema", "explain_query", "generate_query",
            "validate_query", "reload_metadata",
        )
        self.exclude_tools = (
            *getattr(type(self), "exclude_tools", ()),
            *_raw_inherited,
        )

        # Navigator-specific state (before super().__init__)
        self.default_client_id = default_client_id
        self.user_id = user_id
        self._page_index = page_index
        self._is_superuser: Optional[bool] = None
        self._user_programs: Optional[set] = None
        self._user_groups: Optional[set] = None
        self._user_modules: Optional[set] = None
        self._user_clients: Optional[set] = None
        self._builder_group_names: set = set(
            builder_groups
            or json.loads(os.environ.get("NAVIGATOR_BUILDER_GROUPS", "[]"))
        )
        self._is_builder: bool = False
        self._builder_programs: set = set()

        super().__init__(
            dsn=dsn,
            allowed_schemas=["public", "auth", "navigator"],
            primary_schema="navigator",
            tables=self._NAVIGATOR_TABLES,
            read_only=False,
            **kwargs,
        )

    async def stop(self) -> None:
        """Close the underlying DB connection and clear permissions cache."""
        await super().stop()
        self._invalidate_permissions()

    def _invalidate_permissions(self) -> None:
        """Clear cached permissions (call when user groups may have changed)."""
        self._is_superuser = None
        self._user_programs = None
        self._user_groups = None
        self._user_modules = None
        self._user_clients = None
        self._is_builder = False
        self._builder_programs = set()

    # =========================================================================
    # DATABASE HELPERS (private - not exposed as tools)
    # Uses parent's _acquire_asyncdb_connection() for all I/O.
    # NOTE: The old names _get_db, _connection, _query, _query_one, _exec
    #       were removed in FEAT-106/TASK-744.  These replacements share the
    #       same semantics but are prefixed with _nav_ to avoid name collisions.
    # =========================================================================

    async def _nav_run_query(
        self, sql: str, params: Optional[list] = None, conn: Optional[Any] = None
    ) -> list:
        """Execute parameterised *sql* and return a list of row dicts.

        Routes through :meth:`PostgresToolkit.execute_sql` so that the call
        honours an existing *conn* (e.g., one yielded by :meth:`transaction`)
        instead of acquiring a fresh pool connection.

        Args:
            sql: Parameterised SQL with ``$1``, ``$2``, … placeholders.
            params: Positional parameters list.
            conn: Optional existing connection for transaction reuse.

        Returns:
            List of row dicts (empty list on no results).
        """
        result = await self.execute_sql(
            sql, tuple(params or []), conn=conn, returning=True, single_row=False
        )
        return result if isinstance(result, list) else []

    async def _nav_run_one(
        self, sql: str, params: Optional[list] = None, conn: Optional[Any] = None
    ) -> Optional[dict]:
        """Execute parameterised *sql* and return the first row dict, or ``None``.

        Routes through :meth:`PostgresToolkit.execute_sql`.

        Args:
            sql: Parameterised SQL with ``$1``, ``$2``, … placeholders.
            params: Positional parameters list.
            conn: Optional existing connection for transaction reuse.

        Returns:
            First row as a dict, or ``None`` when no row matched.
        """
        result = await self.execute_sql(
            sql, tuple(params or []), conn=conn, returning=True, single_row=True
        )
        return result if isinstance(result, dict) and result else None

    async def _nav_execute(
        self, sql: str, params: Optional[list] = None, conn: Optional[Any] = None
    ) -> Any:
        """Execute a DML statement and return ``{"status": "ok"}``.

        Routes through :meth:`PostgresToolkit.execute_sql`.  Unlike the
        former implementation (which used the asyncdb ``conn.execute``
        interface directly), this path shares *conn* when one is provided,
        enabling true transactional atomicity across multiple DML calls.

        Args:
            sql: Parameterised DML SQL with ``$1``, ``$2``, … placeholders.
            params: Positional parameters list.
            conn: Optional existing connection for transaction reuse.

        Returns:
            ``{"status": "ok"}``
        """
        return await self.execute_sql(
            sql, tuple(params or []), conn=conn, returning=False
        )

    def _jsonb(self, value: Any) -> Optional[str]:
        """Serialize a value to JSON string for JSONB columns."""
        if value is None:
            return None
        return json.dumps(value) if isinstance(value, (dict, list)) else str(value)

    @staticmethod
    def _is_uuid(value: Any) -> bool:
        """Check if a value is a valid UUID."""
        try:
            _uuid.UUID(str(value))
            return True
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _to_uuid(value: Any) -> Optional[_uuid.UUID]:
        """Convert a string to a uuid.UUID object for asyncpg.

        asyncpg requires native uuid.UUID objects for UUID columns,
        not strings with  cast.
        """
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(str(value))

    # ── Name/slug resolvers ─────────────────────────────────────

    async def _resolve_program_id(self, program_id: Optional[int] = None, program_slug: Optional[str] = None) -> int:
        """Resolve a program by ID or slug. Raises ValueError if not found."""
        if program_id:
            return program_id
        if not program_slug:
            raise ValueError("Provide program_id or program_slug")
        row = await self._nav_run_one(
            "SELECT program_id FROM auth.programs WHERE program_slug = $1", [program_slug]
        )
        if not row:
            raise ValueError(f"Program not found: slug='{program_slug}'")
        return row["program_id"]

    async def _resolve_module_id(
        self, module_id: Optional[int] = None, module_slug: Optional[str] = None, program_id: Optional[int] = None
    ) -> int:
        """Resolve a module by ID or slug. Raises ValueError if not found."""
        if module_id:
            return module_id
        if not module_slug:
            raise ValueError("Provide module_id or module_slug")
        conds, params = ["module_slug = $1"], [module_slug]
        if program_id:
            conds.append("program_id = $2")
            params.append(program_id)
        row = await self._nav_run_one(
            f"SELECT module_id FROM navigator.modules WHERE {' AND '.join(conds)}", params
        )
        if not row:
            raise ValueError(f"Module not found: slug='{module_slug}'")
        return row["module_id"]

    async def _resolve_dashboard_id(
        self, dashboard_id: Optional[str] = None, dashboard_name: Optional[str] = None, program_id: Optional[int] = None
    ) -> str:
        """Resolve a dashboard by UUID or name. Raises ValueError if not found."""
        if dashboard_id:
            return dashboard_id
        if not dashboard_name:
            raise ValueError("Provide dashboard_id or dashboard_name")
        conds, params = ["name = $1"], [dashboard_name]
        if program_id:
            conds.append("program_id = $2")
            params.append(program_id)
        row = await self._nav_run_one(
            f"SELECT dashboard_id FROM navigator.dashboards WHERE {' AND '.join(conds)} ORDER BY enabled DESC LIMIT 1",
            params
        )
        if not row:
            raise ValueError(f"Dashboard not found: name='{dashboard_name}'")
        return str(row["dashboard_id"])

    async def _resolve_client_ids(
        self,
        client_ids: Optional[List[int]] = None,
        client_slugs: Optional[List[str]] = None,
        program_id: Optional[int] = None,
    ) -> List[int]:
        """Resolve client IDs from IDs, slugs, or program assignment.

        Resolution order:
        1. Explicit client_ids (if provided)
        2. client_slugs → lookup auth.clients
        3. program_id → lookup auth.program_clients (all active clients for the program)
        4. Fallback to self.default_client_id
        """
        if client_ids:
            return client_ids
        if client_slugs:
            rows = await self._nav_run_query(
                "SELECT client_id FROM auth.clients WHERE client_slug = ANY($1::varchar[])",
                [client_slugs]
            )
            if not rows:
                raise ValueError(f"No clients found for slugs: {client_slugs}")
            return [r["client_id"] for r in rows]
        if program_id is not None:
            rows = await self._nav_run_query(
                "SELECT client_id FROM auth.program_clients "
                "WHERE program_id = $1 AND active = true",
                [program_id]
            )
            if rows:
                return [r["client_id"] for r in rows]
        return [self.default_client_id]

    async def _nav_build_update(
        self,
        table: str,
        pk_col: str,
        pk_val: Any,
        data: dict,
        confirm_execution: bool = False,
        include_updated_at: bool = False,
    ) -> dict:
        """Build and optionally execute a dynamic UPDATE from non-None fields.

        Delegates execution to :meth:`update_row` so that identifier
        validation, Pydantic input validation, and
        ``QueryValidator.validate_sql_ast(require_pk_in_where=True)`` are
        all applied automatically.

        Args:
            table: Fully-qualified table, e.g. ``"auth.programs"``.
            pk_col: Primary-key column used in the WHERE clause.
            pk_val: Value for ``pk_col``; UUID strings are coerced via
                :meth:`_to_uuid`.
            data: Column→value mapping; ``None`` values are skipped.
            confirm_execution: When ``False``, return a plan dict for user
                approval without executing.  When ``True``, execute and
                return a success dict.
            include_updated_at: When ``True``, include
                ``updated_at = <now>`` in the SET clause by injecting a
                Python ``datetime`` value that asyncpg binds natively.

        Returns:
            ``{"status": "confirm_execution", "query": …, …}`` when
            *confirm_execution* is ``False``, or
            ``{"status": "success", "result": {…}}`` after execution.
        """
        import datetime as _dt

        # Strip None-valued fields (matches old _build_update semantics)
        clean: dict = {k: v for k, v in data.items() if v is not None}
        if include_updated_at:
            clean["updated_at"] = _dt.datetime.utcnow()
        if not clean:
            return {"status": "warning", "result": "No fields to update"}

        # Coerce PK value to uuid.UUID for asyncpg when applicable
        where = {
            pk_col: self._to_uuid(pk_val) if self._is_uuid(pk_val) else pk_val
        }

        if not confirm_execution:
            # Build the parameterized template for the user-approval plan.
            # _resolve_table requires warm metadata (i.e. start() must have run).
            try:
                schema, tbl, meta = self._resolve_table(table)
                sql, _ = self._get_or_build_template(
                    "update", schema, tbl, meta,
                    set_columns=tuple(clean.keys()),
                    where_columns=(pk_col,),
                    returning=None,
                )
            except (ValueError, RuntimeError):
                # Fallback: metadata not warm yet — show a readable placeholder
                set_clause = ", ".join(f"{k} = ?" for k in clean)
                sql = f"UPDATE {table} SET {set_clause} WHERE {pk_col} = ?"

            return {
                "status": "confirm_execution",
                "message": (
                    "PLAN GENERATED: Show this plan to the user for approval. "
                    "Do not proceed until the user explicitly confirms."
                ),
                "query": sql,
                "params": [str(v) for v in list(clean.values()) + [pk_val]],
                "action_required": (
                    "Call this tool again with confirm_execution=True "
                    "only if the user approves."
                ),
            }

        # Execute via update_row — benefits from PK-in-WHERE enforcement,
        # template caching, and Pydantic validation.
        await self.update_row(table, data=clean, where=where)
        return {
            "status": "success",
            "result": {pk_col: pk_val, "updated_fields": list(data.keys())},
        }

    # =========================================================================
    # AUTHORIZATION GUARDRAILS (private)
    #
    # Access chain in production:
    #   User → auth.user_groups → Group
    #     Group → auth.program_groups → Program
    #     Group → navigator.modules_groups(group, module, program, client) → Module
    #     Module → Dashboard → Widget
    #
    # Key: modules_groups is scoped by (group_id, module_id, program_id, client_id)
    # A user can only access a module if their group is assigned to that module
    # within a specific client and program context.
    # =========================================================================

    async def _load_user_permissions(self) -> None:
        """Load and cache the current user's groups, programs, and accessible modules.

        Resolves the full access chain:
          user → user_groups → groups
          groups → program_groups → programs
          groups → modules_groups → (module, program, client) tuples
        """
        if self.user_id is None:
            raise PermissionError(
                "No user_id configured. NavigatorToolkit requires a user_id "
                "to enforce authorization guardrails."
            )
        if self._user_groups is not None:
            return  # already loaded

        # Step 1: Load user's groups (with names for builder resolution)
        groups = await self._nav_run_query(
            "SELECT g.group_id, g.group_name "
            "FROM auth.user_groups ug "
            "JOIN auth.groups g ON ug.group_id = g.group_id "
            "WHERE ug.user_id = $1",
            [self.user_id],
        )
        self._user_groups = {r["group_id"] for r in groups}
        self._is_superuser = 1 in self._user_groups

        if self._is_superuser:
            self._user_programs = None
            self._user_modules = None
            self._user_clients = None
            return

        # Step 1b: Resolve builder programs from group membership
        # Convention: {program_slug}_builder group → write access to program
        self._builder_programs = set()
        self._is_builder = False
        if self._builder_group_names:
            user_group_names = {r["group_name"] for r in groups}
            matched = user_group_names & self._builder_group_names
            for gname in matched:
                if gname.endswith("_builder"):
                    slug = gname[: -len("_builder")]
                    row = await self._nav_run_one(
                        "SELECT program_id FROM auth.programs "
                        "WHERE program_slug = $1",
                        [slug],
                    )
                    if row:
                        self._builder_programs.add(row["program_id"])
            self._is_builder = len(self._builder_programs) > 0

        # Step 2: Load accessible programs (group → program_groups → program)
        programs = await self._nav_run_query(
            """SELECT DISTINCT pg.program_id
               FROM auth.program_groups pg
               WHERE pg.group_id = ANY($1::bigint[])""",
            [list(self._user_groups)]
        )
        self._user_programs = {r["program_id"] for r in programs}

        # Step 3: Load accessible (module, program, client) tuples
        # This is the most granular level - modules_groups has the 4-column key
        module_access = await self._nav_run_query(
            """SELECT DISTINCT module_id, program_id, client_id
               FROM navigator.modules_groups
               WHERE group_id = ANY($1::bigint[]) AND active = true""",
            [list(self._user_groups)]
        )
        # Store as set of tuples for fast lookup
        self._user_modules = {
            (r["module_id"], r["program_id"], r["client_id"])
            for r in module_access
        }
        # Also derive accessible clients
        self._user_clients = {r["client_id"] for r in module_access}

    async def _check_program_access(self, program_id: int) -> None:
        """Verify user has access to the program via program_groups.

        Chain: user → user_groups → group → program_groups → program
        """
        await self._load_user_permissions()
        if self._is_superuser:
            return
        if program_id not in self._user_programs:
            raise PermissionError(
                f"Access denied: user {self.user_id} is not assigned to "
                f"program_id={program_id}. "
                f"Accessible programs: {sorted(self._user_programs)}"
            )

    async def _check_client_access(self, client_id: int) -> None:
        """Verify user has access to the client via modules_groups.

        A user has client access if any of their modules_groups entries
        reference that client_id.
        """
        await self._load_user_permissions()
        if self._is_superuser:
            return
        if client_id not in self._user_clients:
            raise PermissionError(
                f"Access denied: user {self.user_id} has no modules assigned "
                f"in client_id={client_id}. "
                f"Accessible clients: {sorted(self._user_clients)}"
            )

    async def _check_module_access(self, module_id: int, program_id: int = None, client_id: int = None) -> None:
        """Verify user has access to the module within the given program/client context.

        Chain: user → user_groups → group → modules_groups(group, module, program, client)

        If program_id/client_id are not provided, checks if the user has access
        to the module in ANY program/client context.
        """
        await self._load_user_permissions()
        if self._is_superuser:
            return

        if program_id is not None and client_id is not None:
            # Exact match: (module, program, client)
            if (module_id, program_id, client_id) not in self._user_modules:
                raise PermissionError(
                    f"Access denied: user {self.user_id} is not assigned to "
                    f"module_id={module_id} in program_id={program_id}, client_id={client_id}"
                )
        else:
            # Check if module is accessible in any context
            accessible = any(
                m_id == module_id and
                (program_id is None or p_id == program_id) and
                (client_id is None or c_id == client_id)
                for m_id, p_id, c_id in self._user_modules
            )
            if not accessible:
                raise PermissionError(
                    f"Access denied: user {self.user_id} "
                    f"(groups={sorted(self._user_groups)}) "
                    f"is not assigned to module_id={module_id}"
                    + (f" in program_id={program_id}" if program_id else "")
                )

    async def _check_dashboard_access(self, dashboard_id: str) -> None:
        """Verify user has access to the dashboard via its module and program.

        Resolves dashboard → (program_id, module_id) then checks module access.
        """
        await self._load_user_permissions()
        if self._is_superuser:
            return
        row = await self._nav_run_one(
            "SELECT program_id, module_id FROM navigator.dashboards "
            "WHERE dashboard_id = $1",
            [self._to_uuid(dashboard_id)]
        )
        if not row:
            raise PermissionError(f"Dashboard {dashboard_id} not found")
        await self._check_program_access(row["program_id"])
        if row.get("module_id"):
            await self._check_module_access(row["module_id"], program_id=row["program_id"])

    async def _check_widget_access(self, widget_id: str) -> None:
        """Verify user has access to the widget via its dashboard, module, and program.

        Resolves widget → dashboard → (program_id, module_id) then checks access.
        """
        await self._load_user_permissions()
        if self._is_superuser:
            return
        row = await self._nav_run_one(
            "SELECT program_id, dashboard_id, module_id FROM navigator.widgets "
            "WHERE widget_id = $1",
            [self._to_uuid(widget_id)]
        )
        if not row:
            raise PermissionError(f"Widget {widget_id} not found")
        await self._check_program_access(row["program_id"])
        if row.get("dashboard_id"):
            await self._check_dashboard_access(str(row["dashboard_id"]))
        elif row.get("module_id"):
            await self._check_module_access(row["module_id"], program_id=row["program_id"])

    async def _require_superuser(self) -> None:
        """Require superuser access (group_id=1).

        Used for global operations: create_program, assign_module_to_client,
        assign_module_to_group.
        """
        await self._load_user_permissions()
        if not self._is_superuser:
            raise PermissionError(
                f"Access denied: user {self.user_id} is not a superuser (group_id=1). "
                f"Only superusers can perform this operation."
            )

    async def _check_write_access(self, program_id: int) -> None:
        """Verify user can write (create/update/deactivate) entities in a program.

        Requires superuser OR membership in a builder group for this program.
        Builder group convention: {program_slug}_builder listed in
        NAVIGATOR_BUILDER_GROUPS env var.
        """
        await self._load_user_permissions()
        if self._is_superuser:
            return
        if self._is_builder and program_id in self._builder_programs:
            return
        raise PermissionError(
            f"Write access denied: user {self.user_id} is not a superuser "
            f"and does not belong to a builder group for program_id={program_id}. "
            f"Builder programs: {sorted(self._builder_programs)}"
        )

    def _get_accessible_program_ids(self) -> Optional[List[int]]:
        """Return list of accessible program IDs, or None for superuser (unlimited)."""
        if self._is_superuser:
            return None
        return sorted(self._user_programs) if self._user_programs else []

    def _get_accessible_module_ids(self) -> Optional[List[int]]:
        """Return list of accessible module IDs, or None for superuser (unlimited)."""
        if self._is_superuser:
            return None
        return sorted({m for m, _, _ in self._user_modules}) if self._user_modules else []

    def _apply_scope_filter(
        self, conds: list, params: list, idx: int, entity: str = "program"
    ) -> int:
        """Append parameterized scope filter to query conditions.

        Returns the next parameter index.
        """
        if entity == "program":
            ids = self._get_accessible_program_ids()
            if ids is None:
                return idx  # superuser
            if not ids:
                conds.append("false")
                return idx
            conds.append(f"program_id = ANY(${idx}::bigint[])")
            params.append(ids)
            return idx + 1
        elif entity == "module":
            ids = self._get_accessible_module_ids()
            if ids is None:
                return idx
            if not ids:
                conds.append("false")
                return idx
            conds.append(f"module_id = ANY(${idx}::bigint[])")
            params.append(ids)
            return idx + 1
        return idx

    # =========================================================================
    # PROGRAMS
    # =========================================================================

    @tool_schema(ProgramCreateInput)
    async def create_program(
        self,
        program_name: str,
        program_slug: str,
        description: Optional[str] = None,
        abbrv: Optional[str] = None,
        is_active: bool = True,
        attributes: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        visible: Optional[bool] = True,
        allow_filtering: Optional[bool] = None,
        filtering_show: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        client_ids: Optional[List[int]] = None,
        client_slugs: Optional[List[str]] = None,
        group_ids: List[int] = None,
        confirm_execution: bool = False,
    ) -> Dict[str, Any]:
        """Create a new Navigator program with client and group assignments.

        Clients can be specified by IDs or slugs (e.g., 'navigator_new', 'navigator_dev').
        Group ID 1 (superuser) is always included automatically.
        Requires superuser access.
        """
        await self._require_superuser()
        client_ids = await self._resolve_client_ids(client_ids, client_slugs)
        group_ids = group_ids or [1]
        if 1 not in group_ids:
            group_ids.insert(0, 1)

        # fetch client_slug map — uses ANY($1::int[]) so stays on _nav_run_query
        # (select_rows supports equality-only WHERE; list-in-array requires execute_query)
        client_slugs_map = {}
        if client_ids:
            rows = await self._nav_run_query(
                "SELECT client_id, client_slug FROM auth.clients WHERE client_id = ANY($1::int[])",
                [client_ids]
            )
            client_slugs_map = {r["client_id"]: r["client_slug"] for r in rows}

        if not confirm_execution:
            return {
                "status": "confirm_execution",
                "message": "PLAN GENERADO: Muestra este plan al usuario para su aprobación. No procedas sin confirmación 100% explícita.",
                "action": f"CREAR PROGRAMA '{program_name}' (slug: {program_slug}) Asignando clientes: {client_ids}",
                "action_required": "Si el usuario aprueba, llama de nuevo pasando confirm_execution=True."
            }

        # Idempotent: if program with same slug already exists, return it
        existing_rows = await self.select_rows(
            "auth.programs",
            where={"program_slug": program_slug},
            columns=["program_id", "program_slug"],
            limit=1,
        )
        if existing_rows:
            existing = existing_rows[0]
            pid = existing["program_id"]

            # Fetch all existing modules to cascade assignments
            module_rows = await self.select_rows(
                "navigator.modules",
                where={"program_id": pid},
                columns=["module_id"],
            )
            mod_ids = [m["module_id"] for m in module_rows] if module_rows else []

            async with self.transaction() as tx:
                # Ensure assignments are up to date
                for cid in client_ids:
                    c_slug = client_slugs_map.get(cid, program_slug)
                    # program_clients: DO NOTHING semantic — stays on execute_sql (Q1)
                    await self.execute_sql(
                        "INSERT INTO auth.program_clients (program_id, client_id, program_slug, client_slug, active) "
                        "VALUES ($1,$2,$3,$4,true)",
                        (pid, cid, program_slug, c_slug),
                        conn=tx,
                        returning=False,
                    )
                    for mid in mod_ids:
                        # client_modules: true UPSERT (DO UPDATE SET active) — uses upsert_row
                        await self.upsert_row(
                            "navigator.client_modules",
                            data={"client_id": cid, "program_id": pid, "module_id": mid, "active": True},
                            conflict_cols=["client_id", "program_id", "module_id"],
                            update_cols=["active"],
                            conn=tx,
                        )

                for gid in group_ids:
                    # program_groups: gprogram_id subquery cannot be expressed via upsert_row.data
                    # stays on execute_sql (Q1 + documented exception)
                    await self.execute_sql(
                        "INSERT INTO auth.program_groups (gprogram_id, program_id, group_id, created_by, created_at) "
                        "VALUES ((SELECT COALESCE(MAX(gprogram_id), 0) + 1 FROM auth.program_groups),$1,$2,$3,now())",
                        (pid, gid, str(self.user_id)),
                        conn=tx,
                        returning=False,
                    )
                    for cid in client_ids:
                        for mid in mod_ids:
                            # modules_groups: true UPSERT (DO UPDATE SET active) — uses upsert_row
                            await self.upsert_row(
                                "navigator.modules_groups",
                                data={"group_id": gid, "module_id": mid, "program_id": pid, "client_id": cid, "active": True},
                                conflict_cols=["group_id", "module_id", "client_id", "program_id"],
                                update_cols=["active"],
                                conn=tx,
                            )

            return {
                "status": "success",
                "result": {"program_id": pid, "program_slug": program_slug, "already_existed": True},
                "metadata": {"clients": client_ids, "groups": group_ids}
            }

        async with self.transaction() as tx:
            # Fix sequence if out of sync (Q3 — defensive sequence repair; stays on execute_sql)
            await self.execute_sql(
                "SELECT setval(pg_get_serial_sequence('auth.programs', 'program_id'), "
                "COALESCE((SELECT MAX(program_id) FROM auth.programs), 0) + 1, false)",
                (),
                conn=tx,
                returning=False,
            )
            # Insert the new program row
            row = await self.insert_row(
                "auth.programs",
                data={
                    "program_name": program_name,
                    "program_slug": program_slug,
                    "description": description,
                    "abbrv": abbrv,
                    "is_active": is_active,
                    "attributes": attributes,
                    "image_url": image_url,
                    "visible": visible,
                    "allow_filtering": allow_filtering,
                    "filtering_show": filtering_show,
                    "conditions": conditions,
                    "program_cat_id": 1,
                    "created_by": "navigator_toolkit",
                },
                returning=["program_id", "program_slug"],
                conn=tx,
            )
            pid = row["program_id"]

            for cid in client_ids:
                c_slug = client_slugs_map.get(cid, program_slug)
                # program_clients: DO NOTHING semantic — stays on execute_sql (Q1)
                await self.execute_sql(
                    "INSERT INTO auth.program_clients (program_id, client_id, program_slug, client_slug, active) "
                    "VALUES ($1,$2,$3,$4,true)",
                    (pid, cid, program_slug, c_slug),
                    conn=tx,
                    returning=False,
                )
            for gid in group_ids:
                # program_groups: gprogram_id subquery cannot be expressed via upsert_row.data
                # stays on execute_sql (Q1 + documented exception)
                await self.execute_sql(
                    "INSERT INTO auth.program_groups (gprogram_id, program_id, group_id, created_by, created_at) "
                    "VALUES ((SELECT COALESCE(MAX(gprogram_id), 0) + 1 FROM auth.program_groups),$1,$2,$3,now())",
                    (pid, gid, str(self.user_id)),
                    conn=tx,
                    returning=False,
                )

        return {
            "status": "success",
            "result": {"program_id": pid, "program_slug": program_slug},
            "metadata": {"clients": client_ids, "groups": group_ids}
        }

    @tool_schema(ProgramUpdateInput)
    async def update_program(
        self, program_id: int, **kwargs
    ) -> Dict[str, Any]:
        """Update an existing Navigator program. Only provided fields are changed.
        Requires access to the program.
        """
        await self._check_program_access(program_id)
        fields = {k: v for k, v in kwargs.items() if v is not None and k != "program_id"}
        return await self._nav_build_update("auth.programs", "program_id", program_id, fields)

    @tool_schema(EntityLookupInput)
    async def get_program(
        self,
        entity_id: Optional[int] = None,
        entity_slug: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Get a program by ID or slug. Requires access to the program."""
        if entity_id is not None:
            row = await self._nav_run_one("SELECT * FROM auth.programs WHERE program_id = $1", [entity_id])
            if row:
                await self._check_program_access(row["program_id"])
        elif entity_slug:
            row = await self._nav_run_one("SELECT * FROM auth.programs WHERE program_slug = $1", [entity_slug])
            if row:
                await self._check_program_access(row["program_id"])
        else:
            return {"status": "error", "error": "Provide entity_id or entity_slug"}
        return {"status": "success", "result": row}

    @tool_schema(EntityLookupInput)
    async def list_programs(
        self,
        active_only: bool = True,
        limit: int = 50,
        **kwargs
    ) -> Dict[str, Any]:
        """List Navigator programs the current user has access to."""
        await self._load_user_permissions()
        conds, params, idx = [], [], 1
        if active_only:
            conds.append("is_active = true")
        idx = self._apply_scope_filter(conds, params, idx, "program")
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        params.append(limit)
        rows = await self._nav_run_query(
            f"SELECT program_id, program_name, program_slug, abbrv, is_active "
            f"FROM auth.programs {where} ORDER BY program_name LIMIT ${idx}",
            params
        )
        return {"status": "success", "result": rows}

    # =========================================================================
    # MODULES
    # =========================================================================

    @tool_schema(ModuleCreateInput)
    async def create_module(
        self,
        module_name: str,
        module_slug: str,
        program_id: Optional[int] = None,
        program_slug: Optional[str] = None,
        classname: Optional[str] = None,
        description: Optional[str] = None,
        active: bool = True,
        parent_module_id: Optional[int] = None,
        attributes: Optional[Dict[str, Any]] = None,
        allow_filtering: Optional[bool] = None,
        filtering_show: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        client_ids: Optional[List[int]] = None,
        client_slugs: Optional[List[str]] = None,
        group_ids: List[int] = None,
        confirm_execution: bool = False,
    ) -> Dict[str, Any]:
        """Create a Navigator module with optional menu hierarchy and permissions.

        Program can be specified by ID or slug (e.g., 'google360').
        Clients can be specified by IDs or slugs (e.g., 'navigator_new').

        Modules support parent-child hierarchy via the attributes JSON:
        - Set menu_type='parent' with parent_img and parent_menu for parent modules
        - Set menu_type='child' with menu_id=[parent_ids] for child modules
        """
        program_id = await self._resolve_program_id(program_id, program_slug)
        # Resolve confirmed program_slug via select_rows
        pg_rows = await self.select_rows(
            "auth.programs",
            where={"program_id": program_id},
            columns=["program_slug"],
            limit=1,
        )
        if not pg_rows:
            raise ValueError(f"Program {program_id} not found")
        program_slug = pg_rows[0]["program_slug"]

        await self._check_program_access(program_id)
        await self._check_write_access(program_id)

        # Apply module slug/name logic — business rules preserved byte-for-byte
        if module_name.strip().lower() == "home":
            description = description or "Home"
            module_name = program_slug
            module_slug = program_slug
            classname = classname or program_slug
        else:
            if not module_slug.startswith(f"{program_slug}_"):
                module_slug = f"{program_slug}_{module_slug}"
            description = description or module_name.title()

        client_ids = await self._resolve_client_ids(client_ids, client_slugs, program_id=program_id)

        # fetch client_slug map — uses ANY($1::int[]) so stays on _nav_run_query
        # (select_rows supports equality-only WHERE; list-in-array requires execute_query)
        client_slugs_map = {}
        if client_ids:
            rows = await self._nav_run_query(
                "SELECT client_id, client_slug FROM auth.clients WHERE client_id = ANY($1::int[])",
                [client_ids]
            )
            client_slugs_map = {r["client_id"]: r["client_slug"] for r in rows}

        attrs = attributes or {
            "icon": "mdi:chart-bar", "color": "#1E90FF",
            "order": "1", "quick": "true", "layout_style": "min"
        }
        group_ids = group_ids or [1]

        if not confirm_execution:
            return {
                "status": "confirm_execution",
                "message": "PLAN GENERADO: Muestra este plan al usuario para su aprobación. No procedas sin confirmación 100% explícita.",
                "action": f"CREAR MÓDULO '{module_name}' (slug: {module_slug}) en Programa {program_id}. Asignando a clientes: {client_ids}",
                "action_required": "Si el usuario aprueba, llama de nuevo pasando confirm_execution=True."
            }

        # Idempotent: if module with same slug+program already exists, return it
        existing_rows = await self.select_rows(
            "navigator.modules",
            where={"module_slug": module_slug, "program_id": program_id},
            columns=["module_id", "module_slug"],
            limit=1,
        )
        if existing_rows:
            existing = existing_rows[0]
            mid = existing["module_id"]
            # Still ensure assignments are up to date
            async with self.transaction() as tx:
                for cid in client_ids:
                    c_slug = client_slugs_map.get(cid, program_slug)
                    # program_clients: DO NOTHING semantic — stays on execute_sql (Q1)
                    await self.execute_sql(
                        "INSERT INTO auth.program_clients (program_id, client_id, program_slug, client_slug, active) "
                        "VALUES ($1,$2,$3,$4,true)",
                        (program_id, cid, program_slug, c_slug),
                        conn=tx,
                        returning=False,
                    )
                    # client_modules: true UPSERT (DO UPDATE SET active) — uses upsert_row
                    await self.upsert_row(
                        "navigator.client_modules",
                        data={"client_id": cid, "program_id": program_id, "module_id": mid, "active": True},
                        conflict_cols=["client_id", "program_id", "module_id"],
                        update_cols=["active"],
                        conn=tx,
                    )
                for gid in group_ids:
                    # program_groups: gprogram_id subquery stays on execute_sql (Q1 + documented exception)
                    await self.execute_sql(
                        "INSERT INTO auth.program_groups (gprogram_id, program_id, group_id, created_by, created_at) "
                        "VALUES ((SELECT COALESCE(MAX(gprogram_id), 0) + 1 FROM auth.program_groups),$1,$2,$3,now())",
                        (program_id, gid, str(self.user_id)),
                        conn=tx,
                        returning=False,
                    )
                    for cid in client_ids:
                        # modules_groups: true UPSERT (DO UPDATE SET active) — uses upsert_row
                        await self.upsert_row(
                            "navigator.modules_groups",
                            data={"group_id": gid, "module_id": mid, "program_id": program_id, "client_id": cid, "active": True},
                            conflict_cols=["group_id", "module_id", "client_id", "program_id"],
                            update_cols=["active"],
                            conn=tx,
                        )
            return {
                "status": "success",
                "result": {"module_id": mid, "module_slug": existing["module_slug"], "already_existed": True},
                "metadata": {"program_id": program_id}
            }

        async with self.transaction() as tx:
            # Fix sequence if out of sync (Q3 — defensive sequence repair; stays on execute_sql)
            await self.execute_sql(
                "SELECT setval(pg_get_serial_sequence('navigator.modules', 'module_id'), "
                "COALESCE((SELECT MAX(module_id) FROM navigator.modules), 0) + 1, false)",
                (),
                conn=tx,
                returning=False,
            )
            # Insert the new module row
            row = await self.insert_row(
                "navigator.modules",
                data={
                    "module_name": module_name,
                    "module_slug": module_slug,
                    "classname": classname,
                    "active": active,
                    "description": description,
                    "program_id": program_id,
                    "parent_module_id": parent_module_id,
                    "attributes": attrs,
                    "allow_filtering": allow_filtering,
                    "filtering_show": filtering_show,
                    "conditions": conditions,
                },
                returning=["module_id", "module_slug"],
                conn=tx,
            )
            mid = row["module_id"]

            for cid in client_ids:
                # Ensure program_clients entry exists (FK requirement)
                # program_clients: DO NOTHING semantic — stays on execute_sql (Q1)
                c_slug = client_slugs_map.get(cid, program_slug)
                await self.execute_sql(
                    "INSERT INTO auth.program_clients (program_id, client_id, program_slug, client_slug, active) "
                    "VALUES ($1,$2,$3,$4,true)",
                    (program_id, cid, program_slug, c_slug),
                    conn=tx,
                    returning=False,
                )
                # client_modules: true UPSERT (DO UPDATE SET active) — uses upsert_row
                await self.upsert_row(
                    "navigator.client_modules",
                    data={"client_id": cid, "program_id": program_id, "module_id": mid, "active": True},
                    conflict_cols=["client_id", "program_id", "module_id"],
                    update_cols=["active"],
                    conn=tx,
                )
            for gid in group_ids:
                # program_groups: gprogram_id subquery stays on execute_sql (Q1 + documented exception)
                await self.execute_sql(
                    "INSERT INTO auth.program_groups (gprogram_id, program_id, group_id, created_by, created_at) "
                    "VALUES ((SELECT COALESCE(MAX(gprogram_id), 0) + 1 FROM auth.program_groups),$1,$2,$3,now())",
                    (program_id, gid, str(self.user_id)),
                    conn=tx,
                    returning=False,
                )
                for cid in client_ids:
                    # modules_groups: true UPSERT (DO UPDATE SET active) — uses upsert_row
                    await self.upsert_row(
                        "navigator.modules_groups",
                        data={"group_id": gid, "module_id": mid, "program_id": program_id, "client_id": cid, "active": True},
                        conflict_cols=["group_id", "module_id", "client_id", "program_id"],
                        update_cols=["active"],
                        conn=tx,
                    )

        return {
            "status": "success",
            "result": {"module_id": mid, "module_slug": row["module_slug"]},
            "metadata": {"program_id": program_id, "clients": client_ids, "groups": group_ids}
        }

    @tool_schema(ModuleUpdateInput)
    async def update_module(self, module_id: int, **kwargs) -> Dict[str, Any]:
        """Update an existing Navigator module. Requires write access."""
        mod = await self._nav_run_one(
            "SELECT program_id FROM navigator.modules WHERE module_id = $1",
            [module_id],
        )
        if not mod:
            return {"status": "error", "error": f"Module {module_id} not found"}
        await self._check_module_access(module_id, program_id=mod["program_id"])
        await self._check_write_access(mod["program_id"])
        fields = {k: v for k, v in kwargs.items() if v is not None and k != "module_id"}
        return await self._nav_build_update("navigator.modules", "module_id", module_id, fields)

    @tool_schema(EntityLookupInput)
    async def get_module(
        self, 
        entity_id: Optional[int] = None, 
        entity_slug: Optional[str] = None, 
        **kwargs
    ) -> Dict[str, Any]:
        """Get a module by ID or Slug. Requires access to the module."""
        mid = entity_id or kwargs.get("module_id")
        mslug = entity_slug or kwargs.get("module_slug")

        try:
            mid = await self._resolve_module_id(module_id=mid, module_slug=mslug)
        except ValueError as e:
            return {"status": "error", "error": str(e)}

        row = await self._nav_run_one("SELECT * FROM navigator.modules WHERE module_id = $1", [mid])
        if row:
            await self._check_module_access(mid, program_id=row.get("program_id"))
            return {"status": "success", "result": row}
        return {"status": "error", "error": f"Module {mid} not found"}

    @tool_schema(EntityLookupInput)
    async def list_modules(
        self,
        program_id: Optional[int] = None,
        active_only: bool = True,
        limit: int = 50,
        sort_by_newest: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """List Navigator modules the current user has access to."""
        await self._load_user_permissions()
        conds, params, idx = [], [], 1
        if program_id:
            conds.append(f"program_id = ${idx}"); params.append(program_id); idx += 1
        if active_only:
            conds.append("active = true")
        idx = self._apply_scope_filter(conds, params, idx, "module")
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        
        order_clause = "ORDER BY inserted_at DESC" if sort_by_newest else "ORDER BY program_id, (attributes->>'order')::numeric NULLS LAST"
        
        params.append(limit)
        rows = await self._nav_run_query(
            f"SELECT module_id, module_name, module_slug, classname, description, "
            f"program_id, parent_module_id, active, attributes, "
            f"inserted_at::text, updated_at::text "
            f"FROM navigator.modules {where} "
            f"{order_clause} LIMIT ${idx}",
            params
        )
        return {"status": "success", "result": rows}

    # =========================================================================
    # DASHBOARDS
    # =========================================================================

    @tool_schema(DashboardCreateInput)
    async def create_dashboard(
        self,
        name: str,
        module_id: Optional[int] = None,
        module_slug: Optional[str] = None,
        program_id: Optional[int] = None,
        program_slug: Optional[str] = None,
        description: Optional[str] = None,
        dashboard_type: str = "3",
        position: int = 1,
        enabled: bool = True,
        shared: bool = False,
        published: bool = True,
        allow_filtering: bool = True,
        allow_widgets: bool = True,
        is_system: bool = True,
        params: Optional[Dict[str, Any]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        save_filtering: bool = True,
        slug: Optional[str] = None,
        cond_definition: Optional[Dict[str, Any]] = None,
        filtering_show: Optional[Dict[str, Any]] = None,
        confirm_execution: bool = False,
    ) -> Dict[str, Any]:
        """Create a new Navigator dashboard inside a module.

        Program and module can be specified by ID or slug/name.
        """
        program_id = await self._resolve_program_id(program_id, program_slug)
        module_id = await self._resolve_module_id(module_id, module_slug, program_id)
        await self._check_program_access(program_id)
        await self._check_module_access(module_id)
        await self._check_write_access(program_id)
        # Fallback to toolkit's user_id if not provided
        user_id = user_id or self.user_id

        if not confirm_execution:
            return {
                "status": "confirm_execution",
                "message": "PLAN GENERADO: Muestra este plan al usuario para su aprobación.",
                "action": f"CREAR DASHBOARD '{name}' en module_id {module_id} (program_id {program_id})",
                "action_required": "Si el usuario aprueba, llama de nuevo pasando confirm_execution=True."
            }

        # Idempotent: if dashboard with same name+module+program exists, return it
        # note: select_rows WHERE is equality-only; name+module_id+program_id are all scalars
        existing_rows = await self.select_rows(
            "navigator.dashboards",
            where={"name": name, "module_id": module_id, "program_id": program_id},
            columns=["dashboard_id", "name", "slug"],
            limit=1,
        )
        if existing_rows:
            existing = existing_rows[0]
            return {
                "status": "success",
                "result": {
                    "dashboard_id": str(existing["dashboard_id"]),
                    "name": existing["name"],
                    "slug": existing.get("slug"),
                    "already_existed": True,
                },
                "metadata": {"module_id": module_id, "program_id": program_id}
            }

        params = params or {"closable": False, "sortable": False, "showSettingsBtn": True}
        attributes = attributes or {
            "cols": "12", "icon": "mdi:view-dashboard",
            "color": "#1E90FF", "explorer": "v3", "widget_location": {}
        }

        async with self.transaction() as tx:
            # Pass plain dicts for JSON columns — parent's _prepare_args handles
            # the ::text::jsonb casts automatically (no self._jsonb() calls needed).
            row = await self.insert_row(
                "navigator.dashboards",
                data={
                    "name": name,
                    "description": description,
                    "module_id": module_id,
                    "program_id": program_id,
                    "user_id": user_id,
                    "dashboard_type": dashboard_type,
                    "position": position,
                    "enabled": enabled,
                    "shared": shared,
                    "published": published,
                    "allow_filtering": allow_filtering,
                    "allow_widgets": allow_widgets,
                    "render_partials": False,
                    "save_filtering": save_filtering,
                    "is_system": is_system,
                    "params": params,
                    "attributes": attributes,
                    "conditions": conditions,
                    "slug": slug,
                    "cond_definition": cond_definition,
                    "filtering_show": filtering_show,
                },
                returning=["dashboard_id", "name", "slug"],
                conn=tx,
            )

        return {
            "status": "success",
            "result": {
                "dashboard_id": str(row["dashboard_id"]),
                "name": row["name"], "slug": row.get("slug")
            },
            "metadata": {"module_id": module_id, "program_id": program_id}
        }

    @tool_schema(DashboardUpdateInput)
    async def update_dashboard(self, dashboard_id: str, confirm_execution: bool = False, **kwargs) -> Dict[str, Any]:
        """Update an existing Navigator dashboard. Requires write access."""
        await self._check_dashboard_access(dashboard_id)
        dash = await self._nav_run_one(
            "SELECT program_id FROM navigator.dashboards WHERE dashboard_id = $1",
            [self._to_uuid(dashboard_id)],
        )
        if dash:
            await self._check_write_access(dash["program_id"])
        fields = {k: v for k, v in kwargs.items() if v is not None and k not in ("dashboard_id", "confirm_execution")}
        return await self._nav_build_update("navigator.dashboards", "dashboard_id", dashboard_id, fields, confirm_execution=confirm_execution)

    @tool_schema(EntityLookupInput)
    async def get_dashboard(self, entity_uuid: Optional[str] = None, entity_slug: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Get a dashboard by UUID or Name. Requires access to the dashboard."""
        did = entity_uuid or kwargs.get("dashboard_id")
        dname = entity_slug or kwargs.get("dashboard_name")
        
        try:
            did = await self._resolve_dashboard_id(dashboard_id=did, dashboard_name=dname)
        except ValueError as e:
            return {"status": "error", "error": str(e)}

        await self._check_dashboard_access(did)
        row = await self._nav_run_one(
            "SELECT * FROM navigator.dashboards WHERE dashboard_id = $1", [self._to_uuid(did)]
        )
        return {"status": "success", "result": row}

    @tool_schema(EntityLookupInput)
    async def list_dashboards(
        self,
        program_id: Optional[int] = None,
        module_id: Optional[int] = None,
        active_only: bool = True,
        limit: int = 50,
        **kwargs
    ) -> Dict[str, Any]:
        """List dashboards the current user has access to."""
        await self._load_user_permissions()
        conds, params, idx = [], [], 1
        if program_id:
            conds.append(f"program_id = ${idx}"); params.append(program_id); idx += 1
        if module_id:
            conds.append(f"module_id = ${idx}"); params.append(module_id); idx += 1
        if active_only:
            conds.append("enabled = true")
        idx = self._apply_scope_filter(conds, params, idx, "program")
        idx = self._apply_scope_filter(conds, params, idx, "module")
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        params.append(limit)
        rows = await self._nav_run_query(
            f"SELECT dashboard_id, name, slug, module_id, program_id, "
            f"dashboard_type, position, enabled, published, is_system "
            f"FROM navigator.dashboards {where} ORDER BY module_id, position LIMIT ${idx}",
            params
        )
        return {"status": "success", "result": rows}

    @tool_schema(CloneDashboardInput)
    async def clone_dashboard(
        self,
        source_dashboard_id: str,
        new_name: str,
        target_module_id: Optional[int] = None,
        target_program_id: Optional[int] = None,
        user_id: Optional[int] = None,
        confirm_execution: bool = False,
    ) -> Dict[str, Any]:
        """Clone a dashboard and all its active widgets to a new dashboard.

        If target_module_id or target_program_id are not provided,
        the cloned dashboard stays in the same module/program.
        Requires access to the source dashboard. If targeting a different program,
        also requires access to the target program.
        """
        await self._check_dashboard_access(source_dashboard_id)
        if target_program_id:
            await self._check_program_access(target_program_id)
            await self._check_write_access(target_program_id)
        else:
            # Fetch source program_id to check write access
            src_rows = await self.select_rows(
                "navigator.dashboards",
                where={"dashboard_id": self._to_uuid(source_dashboard_id)},
                columns=["program_id"],
                limit=1,
            )
            if src_rows:
                await self._check_write_access(src_rows[0]["program_id"])
        if target_module_id:
            await self._check_module_access(target_module_id)

        if not confirm_execution:
            return {
                "status": "confirm_execution",
                "message": "PLAN GENERADO: Muestra este plan al usuario para su aprobación.",
                "action": f"CLONAR DASHBOARD source_id {source_dashboard_id} a nuevo target '{new_name}' (target_module: {target_module_id})",
                "action_required": "Si el usuario aprueba, llama de nuevo pasando confirm_execution=True."
            }

        # Fetch the source dashboard to copy its columns
        src_dash_rows = await self.select_rows(
            "navigator.dashboards",
            where={"dashboard_id": self._to_uuid(source_dashboard_id)},
            columns=[
                "description", "module_id", "program_id",
                "enabled", "shared", "allow_filtering", "allow_widgets",
                "dashboard_type", "position", "params", "attributes",
                "conditions", "render_partials", "save_filtering",
            ],
            limit=1,
        )
        if not src_dash_rows:
            return {"status": "error", "error": f"Source dashboard {source_dashboard_id} not found"}
        src = src_dash_rows[0]

        # Fetch all active source widgets to clone
        src_widget_rows = await self.select_rows(
            "navigator.widgets",
            where={"dashboard_id": self._to_uuid(source_dashboard_id), "active": True},
            columns=[
                "widget_name", "title", "description", "url", "params", "embed",
                "attributes", "conditions", "cond_definition", "where_definition",
                "format_definition", "query_slug", "save_filtering", "master_filtering",
                "allow_filtering", "module_id", "program_id", "widgetcat_id",
                "widget_type_id", "active", "published", "template_id",
            ],
        )

        async with self.transaction() as tx:
            # Insert the new dashboard (published=False for clones, is_system=False)
            new_dash = await self.insert_row(
                "navigator.dashboards",
                data={
                    "name": new_name,
                    "description": src.get("description"),
                    "module_id": target_module_id if target_module_id is not None else src["module_id"],
                    "program_id": target_program_id if target_program_id is not None else src["program_id"],
                    "user_id": user_id,
                    "enabled": src.get("enabled"),
                    "shared": src.get("shared"),
                    "published": False,
                    "allow_filtering": src.get("allow_filtering"),
                    "allow_widgets": src.get("allow_widgets"),
                    "dashboard_type": src.get("dashboard_type"),
                    "position": src.get("position"),
                    "params": src.get("params"),
                    "attributes": src.get("attributes"),
                    "conditions": src.get("conditions"),
                    "render_partials": src.get("render_partials"),
                    "save_filtering": src.get("save_filtering"),
                    "is_system": False,
                },
                returning=["dashboard_id", "name"],
                conn=tx,
            )
            new_id = str(new_dash["dashboard_id"])

            # Fan-out: clone each active widget into the new dashboard
            # Each insert_row must receive conn=tx to be part of the same transaction.
            # A failure on any widget insert rolls back the dashboard insert too.
            cloned_count = 0
            for w in src_widget_rows:
                await self.insert_row(
                    "navigator.widgets",
                    data={
                        "widget_name": w.get("widget_name"),
                        "title": w.get("title"),
                        "description": w.get("description"),
                        "url": w.get("url"),
                        "params": w.get("params"),
                        "embed": w.get("embed"),
                        "attributes": w.get("attributes"),
                        "conditions": w.get("conditions"),
                        "cond_definition": w.get("cond_definition"),
                        "where_definition": w.get("where_definition"),
                        "format_definition": w.get("format_definition"),
                        "query_slug": w.get("query_slug"),
                        "save_filtering": w.get("save_filtering"),
                        "master_filtering": w.get("master_filtering"),
                        "allow_filtering": w.get("allow_filtering"),
                        "module_id": target_module_id if target_module_id is not None else w.get("module_id"),
                        "program_id": target_program_id if target_program_id is not None else w.get("program_id"),
                        "widgetcat_id": w.get("widgetcat_id"),
                        "widget_type_id": w.get("widget_type_id"),
                        "active": w.get("active"),
                        "published": w.get("published"),
                        "template_id": w.get("template_id"),
                        "dashboard_id": self._to_uuid(new_id),
                    },
                    conn=tx,
                )
                cloned_count += 1

        return {
            "status": "success",
            "result": {
                "dashboard_id": new_id,
                "source_id": source_dashboard_id,
                "name": new_name,
                "widgets_cloned": cloned_count,
            }
        }

    # =========================================================================
    # WIDGETS
    # =========================================================================

    @tool_schema(WidgetCreateInput)
    async def create_widget(
        self,
        dashboard_id: Optional[str] = None,
        dashboard_name: Optional[str] = None,
        program_id: Optional[int] = None,
        program_slug: Optional[str] = None,
        widget_type_id: str = "api-echarts",
        template_id: Optional[str] = None,
        widget_name: Optional[str] = None,
        title: Optional[str] = None,
        widgetcat_id: int = 3,
        module_id: Optional[int] = None,
        url: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        format_definition: Optional[Dict[str, Any]] = None,
        query_slug: Optional[Dict[str, Any]] = None,
        grid_position: Optional[Dict[str, int]] = None,
        user_id: Optional[int] = None,
        description: Optional[str] = None,
        cond_definition: Optional[Dict[str, Any]] = None,
        where_definition: Optional[Dict[str, Any]] = None,
        embed: Optional[str] = None,
        confirm_execution: bool = False,
    ) -> Dict[str, Any]:
        """Create a widget inside a dashboard.

        Dashboard can be specified by UUID or name.
        Program can be specified by ID or slug.
        """
        user_id = user_id or self.user_id
        if not program_id and not program_slug:
            dashboard_id = await self._resolve_dashboard_id(dashboard_id, dashboard_name)
            # Deduce program_id from the dashboard via select_rows
            did_rows = await self.select_rows(
                "navigator.dashboards",
                where={"dashboard_id": self._to_uuid(dashboard_id)},
                columns=["program_id"],
                limit=1,
            )
            if not did_rows:
                raise ValueError(f"Dashboard {dashboard_id} not found to deduce program_id")
            program_id = did_rows[0]["program_id"]
        else:
            program_id = await self._resolve_program_id(program_id, program_slug)
            dashboard_id = await self._resolve_dashboard_id(dashboard_id, dashboard_name, program_id)

        await self._check_dashboard_access(dashboard_id)
        await self._check_program_access(program_id)
        await self._check_write_access(program_id)

        if not confirm_execution:
            return {
                "status": "confirm_execution",
                "message": "PLAN GENERADO: Muestra este plan al usuario para su aprobación.",
                "action": f"CREAR WIDGET '{widget_name}' ({widget_type_id}) en dashboard {dashboard_id}. Grid Pos: {grid_position}",
                "action_required": "Si el usuario aprueba, llama de nuevo pasando confirm_execution=True."
            }

        async with self.transaction() as tx:
            # Insert the new widget row — pass plain Python values.
            # Parent's _prepare_args handles ::text::jsonb casts for dict columns.
            # The ::varchar and ::text casts are dropped — asyncpg binds natively.
            widget_row = await self.insert_row(
                "navigator.widgets",
                data={
                    "widget_name": widget_name,
                    "title": title,
                    "dashboard_id": self._to_uuid(dashboard_id),
                    "template_id": self._to_uuid(template_id),
                    "program_id": program_id,
                    "widget_type_id": widget_type_id,
                    "widgetcat_id": widgetcat_id,
                    "module_id": module_id,
                    "url": url,
                    "active": True,
                    "published": True,
                    "save_filtering": False,
                    "master_filtering": True,
                    "params": params,
                    "attributes": attributes,
                    "conditions": conditions,
                    "format_definition": format_definition,
                    "query_slug": query_slug,
                    "user_id": user_id,
                    "description": description,
                    "cond_definition": cond_definition,
                    "where_definition": where_definition,
                    "embed": embed,
                },
                returning=["widget_id", "widget_type"],
                conn=tx,
            )
            wid = str(widget_row["widget_id"])

            if grid_position:
                label = title or widget_name or str(wid)
                # Read current dashboard attributes, merge widget_location, write back.
                # Uses select_rows for read and update_row for write — both in the same tx.
                dash_rows = await self.select_rows(
                    "navigator.dashboards",
                    where={"dashboard_id": self._to_uuid(dashboard_id)},
                    columns=["attributes"],
                    limit=1,
                    conn=tx,
                )
                attrs = (dash_rows[0] if dash_rows else {}).get("attributes") or {}
                if not isinstance(attrs, dict):
                    attrs = {}
                wl = attrs.get("widget_location") or {}
                if not isinstance(wl, dict):
                    wl = {}
                wl[str(label)] = grid_position
                attrs["widget_location"] = wl
                await self.update_row(
                    "navigator.dashboards",
                    data={"attributes": attrs},
                    where={"dashboard_id": self._to_uuid(dashboard_id)},
                    conn=tx,
                )

        return {
            "status": "success",
            "result": {
                "widget_id": wid,
                "widget_slug": widget_row.get("widget_slug"),
                "dashboard_id": dashboard_id,
            },
            "metadata": {"widget_type": widget_type_id, "has_template": template_id is not None}
        }

    @tool_schema(WidgetUpdateInput)
    async def update_widget(self, widget_id: str, confirm_execution: bool = False, **kwargs) -> Dict[str, Any]:
        """Update an existing widget. Only provided fields are changed.
        Requires write access to the widget's program.
        """
        await self._check_widget_access(widget_id)
        wgt = await self._nav_run_one(
            "SELECT program_id FROM navigator.widgets WHERE widget_id = $1",
            [self._to_uuid(widget_id)],
        )
        if wgt:
            await self._check_write_access(wgt["program_id"])
        grid_pos = kwargs.pop("grid_position", None)
        fields = {k: v for k, v in kwargs.items() if v is not None and k not in ("widget_id", "confirm_execution")}
        result = await self._nav_build_update("navigator.widgets", "widget_id", widget_id, fields, confirm_execution=confirm_execution)

        if not confirm_execution:
            if grid_pos:
                result["message"] += " \n[+] También actualizará param 'widget_location' en el Dashboard contenedor."
            return result

        if grid_pos:
            widget = await self._nav_run_one(
                "SELECT title, widget_name, dashboard_id FROM navigator.widgets WHERE widget_id = $1",
                [self._to_uuid(widget_id)]
            )
            if widget and widget.get("dashboard_id"):
                label = widget.get("title") or widget.get("widget_name") or widget_id
                await self._nav_execute(
                    """UPDATE navigator.dashboards
                       SET attributes = jsonb_set(
                           COALESCE(attributes, '{}'::jsonb),
                           '{widget_location}',
                           COALESCE(attributes->'widget_location', '{}'::jsonb) ||
                           jsonb_build_object($1, $2::text::jsonb)
                       )
                       WHERE dashboard_id = $3""",
                    [label, json.dumps(grid_pos), str(widget["dashboard_id"])]
                )
        return result

    @tool_schema(EntityLookupInput)
    async def get_widget(self, entity_uuid: Optional[str] = None, entity_slug: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Get a widget by UUID or Name. Requires access to the widget."""
        wid = entity_uuid or kwargs.get("entity_id") or kwargs.get("widget_id")
        
        if not wid and entity_slug:
            row = await self._nav_run_one(
                "SELECT widget_id FROM navigator.widgets WHERE widget_name = $1 OR title = $1 LIMIT 1",
                [str(entity_slug)]
            )
            if row:
                wid = row["widget_id"]

        if not wid:
            return {"status": "error", "error": "Provide entity_uuid (widget_id) or entity_slug (widget_name/title)"}
            
        await self._check_widget_access(str(wid))
        row = await self._nav_run_one(
            "SELECT * FROM navigator.widgets WHERE widget_id = $1", [self._to_uuid(wid)]
        )
        return {"status": "success", "result": row}

    @tool_schema(EntityLookupInput)
    async def list_widgets(
        self,
        dashboard_id: Optional[str] = None,
        program_id: Optional[int] = None,
        active_only: bool = True,
        limit: int = 50,
        **kwargs
    ) -> Dict[str, Any]:
        """List widgets the current user has access to."""
        await self._load_user_permissions()
        conds, params, idx = [], [], 1
        if dashboard_id:
            conds.append(f"dashboard_id = ${idx}"); params.append(self._to_uuid(dashboard_id)); idx += 1
        if program_id:
            conds.append(f"program_id = ${idx}"); params.append(program_id); idx += 1
        if active_only:
            conds.append("active = true")
        idx = self._apply_scope_filter(conds, params, idx, "program")
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        params.append(limit)
        rows = await self._nav_run_query(
            f"SELECT widget_id, widget_name, title, widget_type_id, "
            f"dashboard_id, template_id, program_id, active "
            f"FROM navigator.widgets {where} ORDER BY inserted_at DESC LIMIT ${idx}",
            params
        )
        return {"status": "success", "result": rows}

    # =========================================================================
    # ASSIGNMENTS (permissions)
    # =========================================================================

    @tool_schema(AssignModuleClientInput)
    async def assign_module_to_client(
        self,
        client_id: int,
        program_id: int,
        module_id: int,
        active: bool = True,
        confirm_execution: bool = False,
    ) -> Dict[str, Any]:
        """Activate a module for a specific client within a program.
        Requires superuser access.
        """
        await self._require_superuser()

        if not confirm_execution:
            return {
                "status": "confirm_execution",
                "message": "PLAN GENERADO: Muestra este plan al usuario para su aprobación.",
                "action": (
                    f"ASIGNAR módulo {module_id} al cliente {client_id} "
                    f"en programa {program_id} (active={active})."
                ),
                "action_required": "Si el usuario aprueba, llama de nuevo pasando confirm_execution=True.",
            }

        row = await self.upsert_row(
            "navigator.client_modules",
            data={"client_id": client_id, "program_id": program_id, "module_id": module_id, "active": active},
            conflict_cols=["client_id", "program_id", "module_id"],
            update_cols=["active"],
        )
        return {
            "status": "success",
            "result": row if row else {"client_id": client_id, "module_id": module_id},
            "metadata": {"program_id": program_id, "active": active},
        }

    @tool_schema(AssignModuleGroupInput)
    async def assign_module_to_group(
        self,
        group_id: int,
        module_id: int,
        program_id: int,
        client_id: int,
        active: bool = True,
        confirm_execution: bool = False,
    ) -> Dict[str, Any]:
        """Grant a group access to a module within a specific client context.
        Requires superuser access.
        """
        await self._require_superuser()

        if not confirm_execution:
            return {
                "status": "confirm_execution",
                "message": "PLAN GENERADO: Muestra este plan al usuario para su aprobación.",
                "action": (
                    f"ASIGNAR módulo {module_id} al grupo {group_id} "
                    f"(cliente {client_id}, programa {program_id}, active={active})."
                ),
                "action_required": "Si el usuario aprueba, llama de nuevo pasando confirm_execution=True.",
            }

        row = await self.upsert_row(
            "navigator.modules_groups",
            data={"group_id": group_id, "module_id": module_id, "program_id": program_id, "client_id": client_id, "active": active},
            conflict_cols=["group_id", "module_id", "client_id", "program_id"],
            update_cols=["active"],
        )
        return {
            "status": "success",
            "result": row if row else {"group_id": group_id, "module_id": module_id},
            "metadata": {"program_id": program_id, "client_id": client_id, "active": active},
        }

    # =========================================================================
    # LOOKUPS
    # =========================================================================

    async def list_widget_types(self) -> Dict[str, Any]:
        """List all available widget types in the platform (108 types)."""
        rows = await self._nav_run_query(
            "SELECT widget_type, description, classbase, enabled "
            "FROM navigator.widget_types WHERE enabled = true ORDER BY widget_type"
        )
        return {"status": "success", "result": rows}

    async def list_widget_categories(self) -> Dict[str, Any]:
        """List all widget categories (6 categories: generic, walmart, utility, mso, blank, loreal)."""
        rows = await self._nav_run_query(
            "SELECT widgetcat_id, category, color FROM navigator.widgets_categories ORDER BY widgetcat_id"
        )
        return {"status": "success", "result": rows}

    @tool_schema(EntityLookupInput)
    async def list_clients(self, active_only: bool = True, limit: int = 500, **kwargs) -> Dict[str, Any]:
        """List Navigator clients (tenants). Returns up to 500 by default."""
        where = "WHERE is_active = true" if active_only else ""
        rows = await self._nav_run_query(
            f"SELECT client_id, client, client_slug, subdomain_prefix, is_active "
            f"FROM auth.clients {where} ORDER BY client_id LIMIT $1",
            [limit]
        )
        return {"status": "success", "result": rows}

    @tool_schema(EntityLookupInput)
    async def list_groups(
        self, client_id: Optional[int] = None, active_only: bool = True, limit: int = 50, **kwargs
    ) -> Dict[str, Any]:
        """List auth groups, optionally filtered by client."""
        conds, params, idx = [], [], 1
        if active_only:
            conds.append("is_active = true")
        if client_id:
            conds.append(f"client_id = ${idx}"); params.append(client_id); idx += 1
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        params.append(limit)
        rows = await self._nav_run_query(
            f"SELECT group_id, group_name, client_id, is_active "
            f"FROM auth.groups {where} ORDER BY group_name LIMIT ${idx}",
            params
        )
        return {"status": "success", "result": rows}

    # =========================================================================
    # WIDGET SCHEMA CATALOG (Layer 3 - on-demand detailed lookup)
    # =========================================================================

    async def get_widget_schema(self, widget_type_id: str) -> Dict[str, Any]:
        """Get the full JSON configuration schema for a specific widget type.

        Returns the widget_type definition, a real production template example
        with its complete params/conditions/format_definition/query_slug JSON,
        and usage notes. Use this when you need the exact JSON structure to
        create a widget of this type.

        Args:
            widget_type_id: The widget type (e.g., 'api-echarts', 'api-card', 'media-editor-wysiwyg')
        """
        # Get widget type definition
        wtype = await self._nav_run_one(
            "SELECT widget_type, description, classbase, enabled "
            "FROM navigator.widget_types WHERE widget_type = $1",
            [widget_type_id]
        )
        if not wtype:
            return {"status": "error", "error": f"Widget type '{widget_type_id}' not found"}

        # Get a real template example with full JSON config
        template = await self._nav_run_one(
            """SELECT template_id, widget_name, widget_slug, title, url,
                      params, attributes, conditions, format_definition,
                      query_slug, where_definition, allow_filtering,
                      master_filtering, widgetcat_id, program_id
               FROM navigator.widgets_templates
               WHERE widget_type_id = $1 AND active = true
               ORDER BY inserted_at DESC LIMIT 1""",
            [widget_type_id]
        )

        # Get a real widget instance that overrides template values
        widget_example = await self._nav_run_one(
            """SELECT widget_id, widget_name, title, params, attributes,
                      conditions, format_definition, query_slug,
                      template_id, dashboard_id, program_id
               FROM navigator.widgets
               WHERE widget_type_id = $1 AND active = true
                 AND params IS NOT NULL
               ORDER BY inserted_at DESC LIMIT 1""",
            [widget_type_id]
        )

        # Count usage
        usage = await self._nav_run_one(
            "SELECT count(*) as total FROM navigator.widgets WHERE widget_type_id = $1 AND active = true",
            [widget_type_id]
        )

        return {
            "status": "success",
            "result": {
                "widget_type": wtype,
                "template_example": template,
                "widget_example": widget_example,
                "usage_count": usage["total"] if usage else 0,
                "notes": (
                    f"Base loader: {'API (fetches data from query_slug)' if widget_type_id.startswith('api-') else 'Media (static data from format_definition/params)' if widget_type_id.startswith('media-') else 'Check classbase'}. "
                    f"99.9% of widgets use a template_id. Only override fields that differ from the template."
                )
            }
        }

    async def find_widget_templates(
        self, widget_type_id: str, program_id: Optional[int] = None, limit: int = 10
    ) -> Dict[str, Any]:
        """Find available widget templates for a given widget type.

        Templates are reusable base configurations. When creating a widget,
        reference a template_id and only override the fields you need to change
        (typically query_slug, conditions, and sometimes params).

        Args:
            widget_type_id: Filter by widget type (e.g., 'api-echarts')
            program_id: Optionally filter by program
            limit: Max results (default 10)
        """
        conds = ["widget_type_id = $1", "active = true"]
        params = [widget_type_id]
        idx = 2
        if program_id:
            conds.append(f"(program_id = ${idx} OR program_id IS NULL)")
            params.append(program_id)
            idx += 1
        params.append(limit)
        where = f"WHERE {' AND '.join(conds)}"
        rows = await self._nav_run_query(
            f"""SELECT template_id, widget_name, widget_slug, title,
                       widget_type_id, widgetcat_id, program_id,
                       params, attributes, conditions, format_definition, query_slug
                FROM navigator.widgets_templates {where}
                ORDER BY inserted_at DESC LIMIT ${idx}""",
            params
        )
        return {"status": "success", "result": rows}

    async def search_widget_docs(self, query: str) -> Dict[str, Any]:
        """Search the Navigator widget documentation using PageIndex tree-search.

        Uses LLM reasoning over a hierarchical document tree to find the most
        relevant sections. Returns detailed configuration docs, JSON examples,
        and the LLM's reasoning about why those sections match.

        This is the Layer 2 retrieval — use it when you need detailed
        configuration docs for a specific widget type or feature. For the
        exact DB schema of a widget type, use get_widget_schema() instead.

        Args:
            query: Natural language search (e.g., "How to configure drilldowns in api-card?")
        """
        if not self._page_index or not self._page_index.is_built:
            return {
                "status": "error",
                "error": "PageIndex not initialized. Pass page_index to NavigatorToolkit constructor.",
            }
        result = await self._page_index.retrieve(query)
        return {
            "status": "success",
            "result": {
                "thinking": result.get("thinking", ""),
                "node_list": result.get("node_list", []),
                "context": result.get("context", ""),
            },
            "metadata": {"source": "pageindex", "query": query},
        }

    # =========================================================================
    # COMPLEX OPERATIONS
    # =========================================================================

    @tool_schema(EntityLookupInput)
    async def get_full_program_structure(
        self,
        entity_id: Optional[int] = None,
        entity_slug: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Get the complete structure of a program: modules, dashboards, and widget count.

        Useful for understanding the full layout of a program before making changes.
        Requires access to the program.
        """
        pid = entity_id
        if entity_slug and not pid:
            prog = await self._nav_run_one(
                "SELECT program_id FROM auth.programs WHERE program_slug = $1", [entity_slug]
            )
            pid = prog["program_id"] if prog else None
        if not pid:
            return {"status": "error", "error": "Provide entity_id (program_id) or entity_slug (program_slug)"}
        await self._check_program_access(pid)

        program = await self._nav_run_one("SELECT * FROM auth.programs WHERE program_id = $1", [pid])
        modules = await self._nav_run_query(
            "SELECT module_id, module_name, module_slug, description, attributes, active "
            "FROM navigator.modules WHERE program_id = $1 AND active = true "
            "ORDER BY (attributes->>'order')::numeric NULLS LAST", [pid]
        )
        dashboards = await self._nav_run_query(
            "SELECT dashboard_id, name, slug, module_id, dashboard_type, position, enabled "
            "FROM navigator.dashboards WHERE program_id = $1 AND enabled = true "
            "ORDER BY module_id, position", [pid]
        )
        wcount = await self._nav_run_one(
            "SELECT count(*) as total FROM navigator.widgets "
            "WHERE program_id = $1 AND active = true", [pid]
        )

        return {
            "status": "success",
            "result": {
                "program": program,
                "modules": modules,
                "dashboards": dashboards,
                "widget_count": wcount["total"] if wcount else 0
            }
        }

    @tool_schema(SearchInput)
    async def search(self, query: str, entity_type: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """Search across Navigator entities by name, slug, or title.

        Results are scoped to entities the current user has access to.
        If entity_type is not specified, searches programs, modules, dashboards, and widgets.
        """
        await self._load_user_permissions()
        pattern = f"%{query}%"
        results = {}
        prog_ids = self._get_accessible_program_ids()
        mod_ids = self._get_accessible_module_ids()

        # Build scope clause for each entity type
        def _scope_sql(col: str, ids: Optional[List[int]], idx: int) -> tuple:
            """Returns (sql_fragment, params, next_idx)."""
            if ids is None:  # superuser
                return "", [], idx
            if not ids:
                return "AND false", [], idx
            return f"AND {col} = ANY(${idx}::bigint[])", [ids], idx + 1

        if not entity_type or entity_type == "program":
            scope, sp, si = _scope_sql("program_id", prog_ids, 3)
            results["programs"] = await self._nav_run_query(
                f"SELECT program_id, program_name, program_slug FROM auth.programs "
                f"WHERE (program_name ILIKE $1 OR program_slug ILIKE $1) {scope} LIMIT $2",
                [pattern, limit] + sp
            )
        if not entity_type or entity_type == "module":
            scope, sp, si = _scope_sql("module_id", mod_ids, 3)
            results["modules"] = await self._nav_run_query(
                f"SELECT module_id, module_name, module_slug, program_id FROM navigator.modules "
                f"WHERE (module_name ILIKE $1 OR module_slug ILIKE $1) {scope} LIMIT $2",
                [pattern, limit] + sp
            )
        if not entity_type or entity_type == "dashboard":
            scope, sp, si = _scope_sql("program_id", prog_ids, 3)
            results["dashboards"] = await self._nav_run_query(
                f"SELECT dashboard_id, name, slug, program_id, module_id FROM navigator.dashboards "
                f"WHERE (name ILIKE $1 OR slug ILIKE $1) {scope} LIMIT $2",
                [pattern, limit] + sp
            )
        if not entity_type or entity_type == "widget":
            scope, sp, si = _scope_sql("program_id", prog_ids, 3)
            results["widgets"] = await self._nav_run_query(
                f"SELECT widget_id, widget_name, title, widget_type_id, program_id FROM navigator.widgets "
                f"WHERE (widget_name ILIKE $1 OR title ILIKE $1) {scope} LIMIT $2",
                [pattern, limit] + sp
            )

        return {"status": "success", "result": results}
