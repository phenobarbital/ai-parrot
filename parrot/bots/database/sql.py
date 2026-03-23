from __future__ import annotations
from typing import List, Optional, Union
from parrot._imports import lazy_import
from ...stores.abstract import AbstractStore
from .abstract import AbstractDBAgent


class SQLAgent(AbstractDBAgent):
    """SQL Database Agent using LLMs to interact with SQL databases."""
    def __init__(
        self,
        name: str = "DBAgent",
        dsn: str = None,
        allowed_schemas: Union[str, List[str]] = "public",
        primary_schema: Optional[str] = None,
        vector_store: Optional[AbstractStore] = None,
        auto_analyze_schema: bool = True,
        client_id: Optional[str] = None,  # For per-client agents
        **kwargs
    ):
        if dsn is None:
            _qs_conf = lazy_import("querysource.conf", package_name="querysource", extra="db")
            dsn = _qs_conf.async_default_dsn
        super().__init__(
            name=name,
            dsn=dsn,
            allowed_schemas=allowed_schemas,
            primary_schema=primary_schema,
            vector_store=vector_store,
            auto_analyze_schema=auto_analyze_schema,
            client_id=client_id,
            **kwargs)

    def _ensure_async_driver(self, dsn: str) -> str:
        # Ensure async driver
        if self.database_type == 'postgresql':
            if '+asyncpg' not in dsn:
                connection_string = dsn.replace(
                    'postgresql://', 'postgresql+asyncpg://'
                )
            else:
                connection_string = dsn
        else:
            connection_string = dsn
        return connection_string
