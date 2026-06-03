"""State-based sandbox components for the Generic Agent Evaluation Harness.

FEAT-217 — Module 4.

TASK-1418: ``StateBackend`` + ``DictStateBackend``
TASK-1419: ``ToolkitBinder``, ``InMemoryStateSandbox``,
           ``InMemoryStateSandboxProvider``, ``DatabaseToolkitBinder``
TASK-1420: ``JiraToolkitBinder`` (added later)

``DictStateBackend`` is the resettable, in-memory world state owned by the
sandbox.  It is keyed as ``{collection: {entity_id: {field: value}}}``
and produces deterministic snapshots (sorted collections and entity keys)
so diffs and baselines are stable.
"""
from __future__ import annotations

import copy
import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    pass  # TYPE_CHECKING only — no runtime imports needed here

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StateBackend ABC
# ---------------------------------------------------------------------------


class StateBackend(ABC):
    """Abstract resettable world-state store.

    Sandboxes own one ``StateBackend`` and delegate ``reset``/``snapshot``
    to it.  The backend is also the injection point that ``ToolkitBinder``
    implementations wire into toolkit internals.
    """

    @abstractmethod
    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """Reset the store to *seed_state* (or empty if ``None``).

        Args:
            seed_state: Initial state keyed as
                ``{collection: {entity_id: {field: value}}}``.
                A deep copy is taken so the caller's dict is not aliased.
        """
        ...

    @abstractmethod
    async def snapshot(self) -> dict[str, Any]:
        """Return a deterministic deep copy of the current state.

        Collections and entity keys are sorted so that two snapshots taken
        after the same mutations are byte-equal (stable for diffs and
        baselines).

        Returns:
            ``{collection: {entity_id: {field: value}}}`` with all keys
            sorted.
        """
        ...


# ---------------------------------------------------------------------------
# DictStateBackend
# ---------------------------------------------------------------------------


class DictStateBackend(StateBackend):
    """In-memory ``{collection: {entity_id: {field: value}}}`` store.

    Provides CRUD-ish helpers used by fake database / Jira drivers:
    ``create``, ``get``, ``update``, ``delete``, ``list``, ``query``.

    Snapshots are:
    - **deep copies** — callers cannot mutate internal state.
    - **deterministic** — collections and entity keys are sorted.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # StateBackend protocol
    # ------------------------------------------------------------------

    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """Reset the store.

        Args:
            seed_state: New initial state.  Deep-copied so the caller's
                dict is not aliased.  Pass ``None`` to empty the store.
        """
        if seed_state is None:
            self._data = {}
            self.logger.debug("DictStateBackend reset to empty state")
        else:
            self._data = copy.deepcopy(seed_state)
            self.logger.debug(
                "DictStateBackend seeded with %d collection(s)",
                len(self._data),
            )

    async def snapshot(self) -> dict[str, Any]:
        """Return a sorted, deep-copied snapshot of the current state.

        Returns:
            ``{collection: {entity_id: {field: value}}}`` with all
            collection names and entity ids sorted lexicographically.
        """
        return {
            c: {
                eid: copy.deepcopy(self._data[c][eid])
                for eid in sorted(self._data[c])
            }
            for c in sorted(self._data)
        }

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    async def create(
        self, collection: str, entity_id: str, fields: dict[str, Any]
    ) -> None:
        """Insert a new entity.

        Args:
            collection: Collection (table) name.
            entity_id: Unique identifier for the entity.
            fields: Initial field values.

        Raises:
            KeyError: If *entity_id* already exists in *collection*.
        """
        col = self._data.setdefault(collection, {})
        if entity_id in col:
            raise KeyError(
                f"Entity '{entity_id}' already exists in collection "
                f"'{collection}'. Use update() to modify it."
            )
        col[entity_id] = copy.deepcopy(fields)

    async def get(
        self, collection: str, entity_id: str
    ) -> dict[str, Any] | None:
        """Fetch a single entity by id.

        Args:
            collection: Collection name.
            entity_id: Entity identifier.

        Returns:
            A deep copy of the entity's fields, or ``None`` if not found.
        """
        col = self._data.get(collection, {})
        entity = col.get(entity_id)
        return copy.deepcopy(entity) if entity is not None else None

    async def update(
        self, collection: str, entity_id: str, fields: dict[str, Any]
    ) -> None:
        """Merge *fields* into an existing entity (partial update).

        Args:
            collection: Collection name.
            entity_id: Entity identifier.
            fields: Fields to merge (values set to ``None`` are removed).

        Raises:
            KeyError: If *entity_id* does not exist in *collection*.
        """
        col = self._data.get(collection, {})
        if entity_id not in col:
            raise KeyError(
                f"Entity '{entity_id}' not found in collection '{collection}'."
            )
        col[entity_id].update(fields)

    async def delete(self, collection: str, entity_id: str) -> bool:
        """Remove an entity.

        Args:
            collection: Collection name.
            entity_id: Entity identifier.

        Returns:
            ``True`` if the entity was removed; ``False`` if it did not
            exist.
        """
        col = self._data.get(collection, {})
        if entity_id in col:
            del col[entity_id]
            return True
        return False

    async def list(self, collection: str) -> list[dict[str, Any]]:
        """Return all entities in a collection as a list of dicts.

        Each dict contains the entity's fields plus the key ``"_id"``
        carrying the entity identifier.

        Args:
            collection: Collection name.

        Returns:
            List of ``{_id: entity_id, **fields}`` dicts (sorted by id).
        """
        col = self._data.get(collection, {})
        return [
            {"_id": eid, **copy.deepcopy(col[eid])} for eid in sorted(col)
        ]

    async def query(
        self,
        collection: str,
        predicate: Callable[[dict[str, Any]], bool],
    ) -> list[dict[str, Any]]:
        """Return entities in *collection* where *predicate* returns ``True``.

        Args:
            collection: Collection name.
            predicate: A callable that receives a field dict (without the
                ``_id`` key) and returns ``True`` to include the entity.

        Returns:
            Matching entities as ``{_id: entity_id, **fields}`` dicts,
            sorted by entity id.
        """
        col = self._data.get(collection, {})
        result = []
        for eid in sorted(col):
            entity = copy.deepcopy(col[eid])
            if predicate(entity):
                result.append({"_id": eid, **entity})
        return result

    async def upsert(
        self, collection: str, entity_id: str, fields: dict[str, Any]
    ) -> None:
        """Insert or update an entity.

        Args:
            collection: Collection name.
            entity_id: Entity identifier.
            fields: Field values to set (merged with existing on update).
        """
        col = self._data.setdefault(collection, {})
        if entity_id in col:
            col[entity_id].update(copy.deepcopy(fields))
        else:
            col[entity_id] = copy.deepcopy(fields)


# ---------------------------------------------------------------------------
# ToolkitBinder ABC (TASK-1419)
# ---------------------------------------------------------------------------


class ToolkitBinder(ABC):
    """Abstract binder that wires a StateBackend into a concrete toolkit.

    Each toolkit family (Database, Jira, …) has its own ``ToolkitBinder``
    subclass that knows the toolkit's internal injection points.  This keeps
    all toolkit-specific code out of the generic sandbox classes.
    """

    @abstractmethod
    def bind(self, toolkit: Any, backend: "DictStateBackend") -> None:
        """Inject *backend* into *toolkit* so tool calls mutate the backend.

        Args:
            toolkit: The toolkit instance to bind (e.g. ``PostgresToolkit``).
            backend: The ``DictStateBackend`` that acts as the world store.
        """
        ...


# ---------------------------------------------------------------------------
# InMemoryStateSandbox (TASK-1419)
# ---------------------------------------------------------------------------


class InMemoryStateSandbox:
    """State-based sandbox that owns a ``DictStateBackend``.

    Implements the ``Sandbox`` protocol without inheriting to avoid the
    abstract-method requirement — imported at runtime to avoid a circular
    dependency with ``base.py``.

    Args:
        backend: The ``DictStateBackend`` holding world state.
        binder: The ``ToolkitBinder`` used to wire toolkits into the backend.
    """

    def __init__(self, backend: "DictStateBackend", binder: ToolkitBinder) -> None:
        self._backend = backend
        self._binder = binder
        self.logger = logging.getLogger(__name__)

    async def __aenter__(self) -> "InMemoryStateSandbox":
        """Enter the sandbox context.

        Returns:
            Self.
        """
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit the sandbox context (no-op — state is GC'd with the object).

        Args:
            exc: Exception info (ignored).
        """
        pass

    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """Reset the backend to *seed_state*.

        Args:
            seed_state: Initial state, or ``None`` to empty.
        """
        await self._backend.reset(seed_state)

    async def health_check(self) -> bool:
        """Always healthy (in-memory, no external dependency).

        Returns:
            ``True``.
        """
        return True

    async def snapshot(self) -> dict[str, Any]:
        """Return a sorted, deep-copied snapshot of the backend state.

        Returns:
            Snapshot dict from the backend.
        """
        return await self._backend.snapshot()

    async def exec(self, cmd: list[str]) -> Any:
        """Not supported — raises ``NotImplementedError``.

        Args:
            cmd: Command list.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "InMemoryStateSandbox does not support exec(); "
            "use DockerSandbox for code-execution tasks."
        )

    def bind(self, toolkit: Any) -> None:
        """Bind *toolkit* to the sandbox's backend.

        This is called by ``AgentFactory`` before the agent starts its
        rollout so tool calls mutate the in-memory backend.

        Args:
            toolkit: The toolkit instance to wire.
        """
        self._binder.bind(toolkit, self._backend)


# ---------------------------------------------------------------------------
# InMemoryStateSandboxProvider (TASK-1419)
# ---------------------------------------------------------------------------


class InMemoryStateSandboxProvider:
    """Provider that provisions a fresh ``InMemoryStateSandbox`` per attempt.

    No pooling — each ``acquire()`` returns a brand-new backend so attempts
    are fully independent.

    Args:
        binder: The ``ToolkitBinder`` shared across all sandboxes produced by
            this provider.
    """

    def __init__(self, binder: ToolkitBinder) -> None:
        self._binder = binder

    async def acquire(self, spec: Any = None) -> InMemoryStateSandbox:
        """Return a fresh ``InMemoryStateSandbox`` with an empty backend.

        Args:
            spec: ``SandboxSpec`` (seed_state is applied during ``reset``).

        Returns:
            A new ``InMemoryStateSandbox``.
        """
        backend = DictStateBackend()
        return InMemoryStateSandbox(backend, self._binder)

    async def release(self, sandbox: InMemoryStateSandbox) -> None:
        """GC the sandbox (no pool).

        Args:
            sandbox: Ignored.
        """
        pass


# ---------------------------------------------------------------------------
# DatabaseToolkitBinder (TASK-1419)
# ---------------------------------------------------------------------------


class DatabaseToolkitBinder(ToolkitBinder):
    """Binder for ``DatabaseToolkit`` (``PostgresToolkit``) subclasses.

    Sets ``toolkit._connected = True`` to bypass ``start()`` and patches
    ``toolkit._acquire_asyncdb_connection`` to yield a ``FakeRawConnection``
    backed by the ``DictStateBackend``.  Also patches ``toolkit._resolve_table``
    to return a minimal ``TableMetadata`` stub so CRUD method internals work
    without a warm metadata cache.

    The net effect: CRUD tool calls (``insert_row``, ``update_row``, …) go
    through the full ``PostgresToolkit`` parameter-binding pipeline but the
    final SQL is routed to ``FakeRawConnection`` → ``DictStateBackend`` with
    NO real database connection.
    """

    def bind(self, toolkit: Any, backend: "DictStateBackend") -> None:
        """Inject *backend* into *toolkit*.

        Args:
            toolkit: A ``DatabaseToolkit`` subclass instance.
            backend: The ``DictStateBackend`` to use as the world store.
        """
        from parrot.eval.sandbox.fakes import FakeRawConnection

        # 1. Mark as connected so start() is never called.
        toolkit._connected = True

        # 2. Build the fake raw connection once and share it.
        fake_conn = FakeRawConnection(backend)

        # 3. Patch _acquire_asyncdb_connection to yield the fake connection.
        @asynccontextmanager
        async def _fake_acquire():
            yield fake_conn

        toolkit._acquire_asyncdb_connection = _fake_acquire

        # 4. Patch _resolve_table to return a minimal stub for any table.
        def _fake_resolve_table(table: str) -> tuple:
            from parrot.eval.sandbox.fakes import FakeTableMetadata

            if "." in table:
                parts = table.split(".", 1)
                schema = parts[0].strip().strip('"').lower()
                table_name = parts[1].strip().strip('"').lower()
            else:
                schema = getattr(toolkit, "primary_schema", None) or "public"
                table_name = table.strip().strip('"').lower()

            meta = FakeTableMetadata(
                schema=schema,
                tablename=table_name,
            )
            return schema, table_name, meta

        toolkit._resolve_table = _fake_resolve_table

        logger.debug(
            "DatabaseToolkitBinder: bound %r to DictStateBackend",
            type(toolkit).__name__,
        )
