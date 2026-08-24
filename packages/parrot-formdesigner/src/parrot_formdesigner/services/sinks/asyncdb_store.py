"""`AsyncDBSink` — Mongo / Arango (nested) and BigQuery (tabular) via `asyncdb`.

Reaches every other store the workspace already talks to through the
existing `asyncdb>=2.0` direct dependency
(`packages/parrot-formdesigner/pyproject.toml:36`) — no new dependency.

The mapping mode is driver-dependent (spec section 8, resolved): document
drivers (``mongo``, ``arango``) store ``data`` NESTED via
:func:`~parrot_formdesigner.services.sinks.mapper.nest_submission`;
the tabular driver (``bigquery``) flattens via
:func:`~parrot_formdesigner.services.sinks.mapper.flatten_submission`.

Verified against the installed ``asyncdb`` package (2026-08-24):

- ``asyncdb.AsyncDB(driver=..., dsn=..., **kwargs)`` — factory ``__new__``
  that dynamically loads ``asyncdb.drivers.<driver>`` and returns a
  concrete driver instance (``asyncdb/connections.py:31-44``).
- ``mongo.insert(collection_name, data, **kwargs)``
  (``asyncdb/drivers/mongo.py:1017``), ``mongo.list_collections(...)``
  (``:997``), ``mongo.create_collection(database, collection, ...)``
  (``:921``), ``mongo.fetch_one(collection_name, query)`` (``:602``).
- ``arangodb.insert_document(collection, document, return_new=True)``
  (``asyncdb/drivers/arangodb.py:608``),
  ``arangodb.collection_exists(name) -> bool`` (``:275``),
  ``arangodb.create_collection(name, edge=False, **kwargs)`` (``:233``),
  ``arangodb.query(sentence, bind_vars=None, **kwargs)`` (``:341``).
- ``bigquery.write(data, table_id=None, dataset_id=None, ...)``
  (``asyncdb/drivers/bigquery.py:297``),
  ``bigquery.create_table(dataset_id, table_id, schema)`` (``:145``),
  ``bigquery.query(sentence, ...)`` (``:225``).
- Every concrete driver's ``connection()`` is awaitable
  (``asyncdb/interfaces/abstract.py:37``) and ``close()`` is awaitable
  (``:46``).

``AsyncDBTarget.collection`` is validated by ``validate_identifier()`` at
construction (TASK-2417) and so cannot contain a ``.`` — the
``"<dataset_id>.<table_id>"`` convention floated in the spec's docstring
sketch is therefore not representable as a single field. For the
``bigquery`` driver this sink instead uses the tenant as the dataset id
(``dataset_id = tenant``, mirroring how tenant already scopes the
Postgres schema elsewhere in this package) and ``collection`` as the
table id.
"""

from __future__ import annotations

import logging
from typing import Any

from parrot_formdesigner.core.persistence import AsyncDBTarget, SinkCapability
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.mapper import (
    column_names_for,
    flatten_submission,
    nest_submission,
)
from parrot_formdesigner.services.submissions import FormSubmission

# Document drivers store `data` nested; tabular drivers flatten.
DOCUMENT_DRIVERS = frozenset({"mongo", "arango"})
TABULAR_DRIVERS = frozenset({"bigquery"})


class AsyncDBSink(AbstractSubmissionSink):
    """Any other `asyncdb`-backed store (Mongo / Arango / BigQuery).

    Args:
        target: The validated :class:`AsyncDBTarget` this sink writes to.
        alias_registry: Resolves ``target.connection`` to a DSN.
        tenant: Tenant scope used to resolve the connection alias.
        driver: An existing ``asyncdb`` driver instance. When provided,
            this sink does NOT own it and will not close it. Primarily
            for tests (a fake driver) or externally managed connections.
        form: Optional cached form, used by :meth:`write` to compute the
            payload when the caller passes ``payload=None``. Also set
            (overwritten) by every :meth:`ensure_target` call.
    """

    def __init__(
        self,
        target: AsyncDBTarget,
        *,
        alias_registry: SinkAliasRegistry,
        tenant: str,
        driver: Any | None = None,
        form: FormSchema | None = None,
    ) -> None:
        self._target = target
        self._alias_registry = alias_registry
        self._tenant = tenant
        self._driver: Any | None = driver
        self._owns_driver: bool = driver is None
        self._form = form
        self.logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[SinkCapability]:
        """Document drivers: WRITE/READ/LIST/PROVISION.

        The tabular driver (``bigquery``) additionally declares EXTEND —
        BigQuery genuinely supports additive schema change
        (``ALTER TABLE ... ADD COLUMN``-equivalent via load jobs).
        """
        base = {
            SinkCapability.WRITE,
            SinkCapability.READ,
            SinkCapability.LIST,
            SinkCapability.PROVISION,
        }
        if self._target.driver in TABULAR_DRIVERS:
            base.add(SinkCapability.EXTEND)
        return frozenset(base)

    @property
    def family(self) -> str:
        """``"document"`` for mongo/arango, ``"tabular"`` for bigquery."""
        return "document" if self._is_document() else "tabular"

    def _is_document(self) -> bool:
        return self._target.driver in DOCUMENT_DRIVERS

    def _payload_for(self, form: FormSchema, submission: FormSubmission) -> dict[str, Any]:
        if self._is_document():
            return nest_submission(form, submission)
        return flatten_submission(form, submission)

    def _split_bigquery_collection(self) -> tuple[str, str]:
        """Return ``(dataset_id, table_id)`` for the BigQuery driver.

        ``AsyncDBTarget.collection`` is validated by `validate_identifier()`
        at construction (TASK-2417) and therefore CANNOT contain a ``.`` —
        a ``"<dataset>.<table>"`` convention (as originally sketched in the
        spec's docstring) is not representable. Instead, the tenant scopes
        the dataset (``dataset_id = self._tenant``, mirroring how tenant
        already scopes the Postgres schema elsewhere in this package) and
        ``collection`` is the table id within it.
        """
        return self._tenant, self._target.collection

    # ------------------------------------------------------------------
    # Driver lifecycle
    # ------------------------------------------------------------------

    async def _ensure_driver(self) -> Any:
        if self._driver is None:
            try:
                dsn = self._alias_registry.resolve_dsn(self._target.connection, tenant=self._tenant)
                from asyncdb import AsyncDB  # lazy runtime import

                self._driver = AsyncDB(driver=self._target.driver, dsn=dsn)
                await self._driver.connection()
            except ImportError as exc:
                raise SinkUnavailableError(
                    f"asyncdb driver {self._target.driver!r} requires an " f"extra that is not installed: {exc}"
                ) from exc
            except Exception as exc:
                raise SinkUnavailableError(
                    f"Cannot connect to asyncdb sink {self._target.connection!r} "
                    f"(driver={self._target.driver!r}): {exc}"
                ) from exc
        return self._driver

    async def close(self) -> None:
        """Close the driver connection if this sink owns it. Idempotent."""
        if self._owns_driver and self._driver is not None:
            try:
                await self._driver.close()
            except Exception:
                self.logger.warning("AsyncDBSink: error closing driver", exc_info=True)
            self.logger.info("AsyncDBSink: driver closed")
        self._driver = None
        self._owns_driver = False

    # ------------------------------------------------------------------
    # AbstractSubmissionSink implementation
    # ------------------------------------------------------------------

    async def ensure_target(self, form: FormSchema) -> None:
        """Create the collection/table if absent. Additive only.

        Args:
            form: The form whose destination must exist. Cached on this
                sink so :meth:`write` can compute a payload when called
                with ``payload=None``.

        Raises:
            SinkUnavailableError: If provisioning fails.
        """
        self._form = form
        try:
            driver = await self._ensure_driver()
            if self._target.driver == "mongo":
                existing = await driver.list_collections()
                if self._target.collection not in existing:
                    database = getattr(driver, "_database_name", None)
                    await driver.create_collection(database=database, collection=self._target.collection)
            elif self._target.driver == "arango":
                if not await driver.collection_exists(self._target.collection):
                    await driver.create_collection(self._target.collection)
            elif self._target.driver == "bigquery":
                from google.cloud import bigquery as bq  # lazy runtime import

                dataset_id, table_id = self._split_bigquery_collection()
                schema = [bq.SchemaField(name, "STRING") for name in column_names_for(form)]
                await driver.create_table(dataset_id, table_id, schema)
            else:
                raise SinkUnavailableError(f"Unsupported asyncdb driver: {self._target.driver!r}")
        except SinkUnavailableError:
            raise
        except ImportError as exc:
            raise SinkUnavailableError(
                f"asyncdb driver {self._target.driver!r} requires an extra " f"that is not installed: {exc}"
            ) from exc
        except Exception as exc:
            raise SinkUnavailableError(
                f"asyncdb sink {self._target.connection!r} unavailable " f"during ensure_target: {exc}"
            ) from exc

    async def write(self, submission: FormSubmission, payload: Any) -> str:
        """Persist one submission, nested (document) or flattened (tabular).

        Args:
            submission: The submission record being persisted.
            payload: A pre-computed payload, or ``None`` to have this sink
                compute it itself (via :attr:`_form`, set by the most
                recent :meth:`ensure_target` call) using
                :func:`nest_submission` or :func:`flatten_submission`
                depending on the configured driver.

        Returns:
            The persisted ``submission_id``.

        Raises:
            SinkUnavailableError: If the driver connection or write fails.
        """
        if payload is None:
            if self._form is None:
                raise SinkUnavailableError(
                    "AsyncDBSink.write() needs ensure_target(form) to have " "run first, or an explicit payload"
                )
            payload = self._payload_for(self._form, submission)

        try:
            driver = await self._ensure_driver()
            if self._target.driver == "mongo":
                await driver.insert(self._target.collection, payload)
            elif self._target.driver == "arango":
                await driver.insert_document(self._target.collection, payload)
            elif self._target.driver == "bigquery":
                dataset_id, table_id = self._split_bigquery_collection()
                await driver.write([payload], table_id=table_id, dataset_id=dataset_id)
            else:
                raise SinkUnavailableError(f"Unsupported asyncdb driver: {self._target.driver!r}")
        except SinkUnavailableError:
            raise
        except Exception as exc:
            raise SinkUnavailableError(
                f"asyncdb sink {self._target.connection!r} unavailable " f"during write: {exc}"
            ) from exc

        return submission.submission_id

    def _doc_to_submission(self, doc: dict[str, Any]) -> FormSubmission:
        """Reconstruct a `FormSubmission` from a stored document/row."""
        return FormSubmission(
            submission_id=doc["submission_id"],
            form_uid=doc["form_uid"],
            form_id=doc["form_id"],
            form_version=doc["form_version"],
            data=doc.get("data", {}),
            is_valid=True,
            created_at=doc["created_at"],
            tenant=doc.get("tenant"),
            user_id=doc.get("user_id"),
            username=doc.get("username"),
            org_id=doc.get("org_id"),
            submitted_at=doc.get("submitted_at"),
            ip=doc.get("ip"),
            user_agent=doc.get("user_agent"),
            locale=doc.get("locale"),
            root_submission_id=doc.get("root_submission_id"),
            revision=doc.get("revision"),
            context=doc.get("context"),
        )

    async def read(self, submission_id: str) -> FormSubmission | None:
        """Fetch a single submission by ``submission_id``."""
        self.require(SinkCapability.READ)
        try:
            driver = await self._ensure_driver()
            if self._target.driver == "mongo":
                doc = await driver.fetch_one(self._target.collection, {"submission_id": submission_id})
            elif self._target.driver == "arango":
                result, _error = await driver.query(
                    f"FOR doc IN {self._target.collection} " "FILTER doc.submission_id == @sid LIMIT 1 RETURN doc",
                    bind_vars={"sid": submission_id},
                )
                doc = result[0] if result else None
            else:
                dataset_id, table_id = self._split_bigquery_collection()
                result, _error = await driver.query(
                    f"SELECT * FROM `{dataset_id}.{table_id}` " f"WHERE submission_id = @sid LIMIT 1",
                )
                doc = result[0] if result else None
        except SinkUnavailableError:
            raise
        except Exception as exc:
            raise SinkUnavailableError(
                f"asyncdb sink {self._target.connection!r} unavailable " f"during read: {exc}"
            ) from exc
        return self._doc_to_submission(doc) if doc else None

    async def list_revisions(self, root_submission_id: str) -> list[FormSubmission]:
        """Return the full revision chain for a submission, oldest first."""
        self.require(SinkCapability.LIST)
        try:
            driver = await self._ensure_driver()
            if self._target.driver == "mongo":
                docs = await driver.fetch(
                    self._target.collection,
                    {"root_submission_id": root_submission_id},
                )
            elif self._target.driver == "arango":
                docs, _error = await driver.query(
                    f"FOR doc IN {self._target.collection} "
                    "FILTER doc.root_submission_id == @rid "
                    "SORT doc.revision ASC RETURN doc",
                    bind_vars={"rid": root_submission_id},
                )
            else:
                dataset_id, table_id = self._split_bigquery_collection()
                docs, _error = await driver.query(
                    f"SELECT * FROM `{dataset_id}.{table_id}` " "WHERE root_submission_id = @rid ORDER BY revision ASC",
                )
        except SinkUnavailableError:
            raise
        except Exception as exc:
            raise SinkUnavailableError(
                f"asyncdb sink {self._target.connection!r} unavailable " f"during list_revisions: {exc}"
            ) from exc
        return [self._doc_to_submission(doc) for doc in (docs or [])]
