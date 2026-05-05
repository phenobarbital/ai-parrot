"""Pluggable result-storage backends for AgentCrew and AgentsFlow (FEAT-147).

Public API
----------
* ``ResultStorage``           — abstract base class (ABC).
* ``DocumentDbResultStorage`` — default backend (wraps DocumentDb).
* ``RedisResultStorage``      — Redis backend (one key per execution + TTL).
* ``PostgresResultStorage``   — Postgres backend (jsonb row per execution).
* ``get_result_storage``      — factory: resolves a name/instance/env-var.
"""
from .base import ResultStorage
from .factory import get_result_storage
from .documentdb import DocumentDbResultStorage
from .redis import RedisResultStorage
from .postgres import PostgresResultStorage

__all__ = [
    "ResultStorage",
    "DocumentDbResultStorage",
    "RedisResultStorage",
    "PostgresResultStorage",
    "get_result_storage",
]
