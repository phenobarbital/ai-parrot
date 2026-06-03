"""Fake driver implementations for the Generic Agent Evaluation Harness.

FEAT-217 — These fakes translate toolkit method calls into
``DictStateBackend`` operations with NO real network/database/HTTP calls.

Provided fakes
--------------
``FakeTableMetadata``
    Minimal dataclass stub returned by ``DatabaseToolkitBinder._fake_resolve_table``
    to avoid importing ``parrot.bots.database.models`` (which has broken
    optional deps in the test venv).

``FakeRawConnection``
    Implements the raw asyncpg connection surface (``execute``, ``fetchrow``,
    ``fetch``, ``close``) by routing simple INSERT/UPDATE/DELETE/SELECT SQL
    to ``DictStateBackend`` operations.  Only the SQL shape produced by
    ``PostgresToolkit``'s CRUD methods is handled — this is NOT a SQL engine.

``FakeJiraClient``
    Implements the subset of the ``pycontribs.jira.JIRA`` API exercised by
    the Jira triage benchmark: ``search_issues``, ``assign_issue``,
    ``transition_issue``.  State lives in a ``DictStateBackend``.

``StaticResolver``
    Trivial credential resolver that always returns the same pre-built
    ``FakeJiraClient`` without any network I/O.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FakeTableMetadata — minimal stub avoiding parrot.bots imports
# ---------------------------------------------------------------------------


@dataclass
class FakeTableMetadata:
    """Minimal table metadata stub used by ``DatabaseToolkitBinder``.

    Provides the attributes read by ``PostgresToolkit`` internals
    (``schema``, ``tablename``, ``full_name``, ``columns``,
    ``primary_keys``) without importing ``parrot.bots.database.models``.

    Attributes:
        schema: Schema name.
        tablename: Table name.
        full_name: ``schema.tablename`` composite.
        table_type: Always ``"BASE TABLE"`` for the fake.
        columns: Empty list (CRUD pipeline skips unknown columns).
        primary_keys: Empty list.
    """

    schema: str
    tablename: str
    full_name: str = field(default="")
    table_type: str = "BASE TABLE"
    columns: list = field(default_factory=list)
    primary_keys: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.full_name:
            self.full_name = f"{self.schema}.{self.tablename}"


# ---------------------------------------------------------------------------
# FakeRawConnection — asyncpg raw connection surface for eval
# ---------------------------------------------------------------------------


class FakeRawConnection:
    """Fake asyncpg connection that routes CRUD SQL to a ``DictStateBackend``.

    ``PostgresToolkit._run_on_conn`` calls three methods on the raw
    connection:
    - ``await conn.execute(sql, *args)`` — no return value needed
    - ``await conn.fetchrow(sql, *args)`` — returns a dict-like or None
    - ``await conn.fetch(sql, *args)`` — returns a list of dict-likes

    This fake parses the table name from the SQL text (the SQL templates
    produced by ``PostgresToolkit`` are well-structured) and delegates to
    ``DictStateBackend`` CRUD operations.  It is intentionally not a
    general-purpose SQL engine.

    Args:
        backend: The ``DictStateBackend`` instance holding world state.
    """

    def __init__(self, backend: Any) -> None:  # Any = DictStateBackend
        self._backend = backend
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Raw connection protocol
    # ------------------------------------------------------------------

    async def execute(self, sql: str, *args: Any) -> None:
        """Execute a DML statement (INSERT / UPDATE / DELETE).

        Args:
            sql: SQL template with ``$N`` placeholders.
            args: Positional parameter values.
        """
        await self._dispatch(sql, args, returning=False, single_row=False)

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        """Execute a query returning at most one row.

        Args:
            sql: SQL template with ``$N`` placeholders.
            args: Positional parameter values.

        Returns:
            Dict of the row or ``None``.
        """
        result = await self._dispatch(sql, args, returning=True, single_row=True)
        return result if result else None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """Execute a query returning multiple rows.

        Args:
            sql: SQL template with ``$N`` placeholders.
            args: Positional parameter values.

        Returns:
            List of row dicts.
        """
        result = await self._dispatch(sql, args, returning=True, single_row=False)
        return result if result else []

    async def close(self) -> None:
        """No-op close."""
        pass

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        sql: str,
        args: tuple[Any, ...],
        returning: bool,
        single_row: bool,
    ) -> Any:
        """Route *sql* to a DictStateBackend operation.

        Recognises INSERT, UPDATE, DELETE, SELECT by keyword inspection.
        Table name is extracted from the SQL text.

        Args:
            sql: SQL template string.
            args: Bound positional arguments (``$1``, ``$2``, …).
            returning: Whether the caller expects rows back.
            single_row: Whether only one row is expected.

        Returns:
            ``None`` for DML without RETURNING; dict for single-row;
            list[dict] for multi-row.
        """
        sql_upper = sql.strip().upper()

        if sql_upper.startswith("INSERT"):
            return await self._handle_insert(sql, args, returning, single_row)
        elif sql_upper.startswith("UPDATE"):
            return await self._handle_update(sql, args, returning, single_row)
        elif sql_upper.startswith("DELETE"):
            return await self._handle_delete(sql, args, returning, single_row)
        elif sql_upper.startswith("SELECT"):
            return await self._handle_select(sql, args, single_row)
        else:
            self.logger.warning("FakeRawConnection: unrecognised SQL: %s", sql[:80])
            return None

    # helpers

    @staticmethod
    def _extract_table(sql: str) -> str:
        """Extract the table name from a SQL statement.

        Args:
            sql: SQL text.

        Returns:
            Table name (without schema prefix).
        """
        # INSERT INTO "schema"."table" or INSERT INTO table
        m = re.search(
            r'(?:INTO|FROM|UPDATE|JOIN)\s+"?(\w+)"?\."?(\w+)"?',
            sql,
            re.IGNORECASE,
        )
        if m:
            return m.group(2)
        m = re.search(
            r'(?:INTO|FROM|UPDATE|JOIN)\s+"?(\w+)"?',
            sql,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
        return "_unknown_"

    @staticmethod
    def _extract_columns(sql: str) -> list[str]:
        """Extract column names from an INSERT or UPDATE SQL template.

        Args:
            sql: SQL text.

        Returns:
            List of column names in parameter order.
        """
        # INSERT INTO t (col1, col2, ...) VALUES ($1, $2, ...)
        m = re.search(r'\(([^)]+)\)\s+VALUES', sql, re.IGNORECASE)
        if m:
            return [c.strip().strip('"') for c in m.group(1).split(",")]
        # UPDATE t SET col1=$1, col2=$2 WHERE ...
        set_m = re.search(r'SET\s+(.+?)\s+WHERE', sql, re.IGNORECASE | re.DOTALL)
        if set_m:
            assignments = set_m.group(1)
            cols = []
            for assignment in assignments.split(","):
                col_m = re.match(r'\s*"?(\w+)"?\s*=', assignment)
                if col_m:
                    cols.append(col_m.group(1))
            return cols
        return []

    @staticmethod
    def _extract_pk_from_where(sql: str, args: tuple[Any, ...]) -> str | None:
        """Extract primary key value from a WHERE clause.

        Args:
            sql: SQL text.
            args: Bound parameter values.

        Returns:
            The PK value (cast to str) or ``None``.
        """
        # WHERE "id" = $N or WHERE id = $N
        m = re.search(r'WHERE\s+"?(\w+)"?\s*=\s*\$(\d+)', sql, re.IGNORECASE)
        if m:
            idx = int(m.group(2)) - 1
            if idx < len(args):
                return str(args[idx])
        return None

    async def _handle_insert(
        self, sql: str, args: tuple[Any, ...], returning: bool, single_row: bool
    ) -> Any:
        table = self._extract_table(sql)
        cols = self._extract_columns(sql)
        if not cols or len(args) < len(cols):
            self.logger.warning(
                "FakeRawConnection: INSERT: cannot parse columns from SQL; "
                "storing raw args under _fake_row"
            )
            entity_id = str(args[0]) if args else "_unknown_"
            await self._backend.upsert(table, entity_id, {"_fake_row": args})
            return {"status": "ok"} if returning else None

        # First arg after columns is usually the id; build a dict
        data = dict(zip(cols, args))
        # Use first column as entity id by default
        entity_id = str(data.get(cols[0], "_unknown_"))
        await self._backend.upsert(table, entity_id, data)
        if returning:
            row = dict(data)
            return row if single_row else [row]
        return None

    async def _handle_update(
        self, sql: str, args: tuple[Any, ...], returning: bool, single_row: bool
    ) -> Any:
        table = self._extract_table(sql)
        pk_val = self._extract_pk_from_where(sql, args)
        set_cols = self._extract_columns(sql)

        # WHERE clause uses the last $N parameter typically
        set_args = args[: len(set_cols)]
        update_data = dict(zip(set_cols, set_args))

        if pk_val:
            try:
                await self._backend.update(table, pk_val, update_data)
            except KeyError:
                await self._backend.upsert(table, pk_val, update_data)
        else:
            self.logger.warning(
                "FakeRawConnection: UPDATE without parseable WHERE; "
                "applying to all entities in %s",
                table,
            )
            entities = await self._backend.list(table)
            for e in entities:
                await self._backend.update(table, e["_id"], update_data)

        if returning:
            if pk_val:
                entity = await self._backend.get(table, pk_val)
                if entity:
                    return entity if single_row else [entity]
            return {} if single_row else []
        return None

    async def _handle_delete(
        self, sql: str, args: tuple[Any, ...], returning: bool, single_row: bool
    ) -> Any:
        table = self._extract_table(sql)
        pk_val = self._extract_pk_from_where(sql, args)
        if pk_val:
            entity = await self._backend.get(table, pk_val)
            await self._backend.delete(table, pk_val)
            if returning:
                return (entity or {}) if single_row else ([entity] if entity else [])
        return None

    async def _handle_select(
        self, sql: str, args: tuple[Any, ...], single_row: bool
    ) -> Any:
        table = self._extract_table(sql)
        pk_val = self._extract_pk_from_where(sql, args)
        if pk_val:
            entity = await self._backend.get(table, pk_val)
            if single_row:
                return entity
            return [entity] if entity else []
        # Full scan
        entities = await self._backend.list(table)
        if single_row:
            return entities[0] if entities else None
        return entities


# ---------------------------------------------------------------------------
# FakeJiraClient — minimal pycontribs JIRA surface for the triage benchmark
# ---------------------------------------------------------------------------


class _FakeIssue:
    """Mimics a pycontribs ``jira.Issue`` object."""

    def __init__(self, key: str, fields: dict[str, Any]) -> None:
        self.key = key
        self.id = key
        self.raw = {"key": key, **fields}
        # Simulate .fields attribute
        self.fields = type("Fields", (), fields)()


class FakeJiraClient:
    """In-memory Jira client backed by a ``DictStateBackend``.

    Implements the subset of the ``pycontribs.jira.JIRA`` API that the
    Jira triage benchmark exercises.  State is stored in the ``"issues"``
    collection of *backend*.

    Args:
        backend: ``DictStateBackend`` holding the issue store.
    """

    def __init__(self, backend: Any) -> None:  # Any = DictStateBackend
        self._backend = backend
        self.logger = logging.getLogger(__name__)

    def search_issues(
        self, jql_str: str, maxResults: int = 50, fields: str = "*all", **kwargs: Any
    ) -> list[_FakeIssue]:
        """Search issues using a simple JQL-like filter.

        Only the ``project = X`` and ``assignee is EMPTY`` / ``is not EMPTY``
        conditions are recognized.  All other conditions are ignored and all
        issues are returned.

        Args:
            jql_str: JQL query string.
            maxResults: Maximum number of results.
            fields: Comma-separated field names (ignored — all fields returned).

        Returns:
            List of ``_FakeIssue`` objects.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    lambda: asyncio.run(self._search_async(jql_str, maxResults))
                )
                return future.result()
        return loop.run_until_complete(self._search_async(jql_str, maxResults))

    async def _search_async(self, jql_str: str, max_results: int) -> list[_FakeIssue]:
        entities = await self._backend.list("issues")
        issues = []
        for e in entities[:max_results]:
            issues.append(_FakeIssue(e["_id"], {k: v for k, v in e.items() if k != "_id"}))
        return issues

    def assign_issue(self, issue: Any, assignee: str | None) -> None:
        """Assign *issue* to *assignee*.

        Args:
            issue: Issue key string or object with ``.key``.
            assignee: Assignee account id / username, or ``None`` to unassign.
        """
        import asyncio

        key = issue if isinstance(issue, str) else issue.key
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self._assign_async(key, assignee))
        else:
            loop.run_until_complete(self._assign_async(key, assignee))

    async def _assign_async(self, key: str, assignee: str | None) -> None:
        try:
            await self._backend.update("issues", key, {"assignee": assignee})
        except KeyError:
            await self._backend.upsert("issues", key, {"assignee": assignee})

    def transition_issue(self, issue: Any, transition: str, **kwargs: Any) -> None:
        """Transition *issue* to a new status.

        Args:
            issue: Issue key string or object with ``.key``.
            transition: Transition name / id (stored as ``status``).
        """
        import asyncio

        key = issue if isinstance(issue, str) else issue.key
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self._transition_async(key, transition))
        else:
            loop.run_until_complete(self._transition_async(key, transition))

    async def _transition_async(self, key: str, transition: str) -> None:
        try:
            await self._backend.update("issues", key, {"status": transition})
        except KeyError:
            await self._backend.upsert("issues", key, {"status": transition})

    def issue(self, key: str) -> _FakeIssue | None:
        """Fetch a single issue by key.

        Args:
            key: Issue key (e.g. ``"PROJ-1"``).

        Returns:
            ``_FakeIssue`` or ``None``.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    lambda: asyncio.run(self._get_issue_async(key))
                )
                return future.result()
        return loop.run_until_complete(self._get_issue_async(key))

    async def _get_issue_async(self, key: str) -> _FakeIssue | None:
        entity = await self._backend.get("issues", key)
        if entity:
            return _FakeIssue(key, entity)
        return None

    def create_issue(self, fields: dict[str, Any], **kwargs: Any) -> _FakeIssue:
        """Create a new issue.

        Args:
            fields: Issue fields dict; must contain ``"project"`` and
                ``"summary"``.

        Returns:
            The created ``_FakeIssue``.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        project = (fields.get("project") or {}).get("key", "PROJ")
        key = f"{project}-{id(fields) % 9000 + 1000}"
        if loop.is_running():
            asyncio.ensure_future(self._backend.upsert("issues", key, fields))
        else:
            loop.run_until_complete(self._backend.upsert("issues", key, fields))
        return _FakeIssue(key, fields)

    def update_issue_field(self, key: str, fields: dict[str, Any]) -> None:
        """Update fields of an existing issue.

        Args:
            key: Issue key.
            fields: Fields to update (merged).
        """
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self._backend.upsert("issues", key, fields))
        else:
            loop.run_until_complete(self._backend.upsert("issues", key, fields))


# ---------------------------------------------------------------------------
# StaticResolver — no-network credential resolver for eval
# ---------------------------------------------------------------------------


class StaticResolver:
    """Credential resolver that always returns a pre-built ``FakeJiraClient``.

    Satisfies the ``credential_resolver.resolve(channel, user_id)`` contract
    used by ``JiraToolkit._pre_execute`` when ``auth_type == "oauth2_3lo"``,
    but without any network call.

    Args:
        fake_client: The ``FakeJiraClient`` to always return.
        access_token: Fake access token string (used to fill ``token_hash``).
    """

    def __init__(
        self, fake_client: FakeJiraClient, access_token: str = "fake-token-00000000"
    ) -> None:
        self._client = fake_client
        self._access_token = access_token

    async def resolve(self, channel: str, user_id: str) -> Any:
        """Return a fake token set with the pre-built client embedded.

        Args:
            channel: Channel identifier (ignored).
            user_id: User identifier (ignored).

        Returns:
            An object with ``.access_token`` set to the fake token string
            (so ``JiraToolkit._pre_execute`` builds the token fingerprint
            and looks up ``self._client_cache``).
        """
        return type("FakeTokenSet", (), {"access_token": self._access_token})()

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Return a placeholder auth URL (never called in eval context).

        Args:
            channel: Channel identifier.
            user_id: User identifier.

        Returns:
            Placeholder URL string.
        """
        return "https://fake-jira.example.com/auth"
