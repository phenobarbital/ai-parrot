"""Query safety validator — shared across ai-parrot and parrot-tools.

Provides ``QueryLanguage`` (the supported query dialects) and
``QueryValidator`` (a static, dependency-free safety check for SQL, Flux,
and Elasticsearch JSON DSL).

This module lives in ``parrot.security`` so both the ``DatabaseQueryTool``
(in ``parrot-tools``) and the ``DatabaseToolkit`` (in ``ai-parrot``) can
reuse it without creating a circular dependency between packages.
"""
from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional


class QueryLanguage(str, Enum):
    """Supported query languages."""
    SQL = "sql"
    FLUX = "flux"  # InfluxDB
    MQL = "mql"    # MongoDB Query Language
    CYPHER = "cypher"  # Neo4j
    JSON = "json"  # Elasticsearch/OpenSearch JSON DSL
    AQL = "aql"  # ArangoDB Query Language


class QueryValidator:
    """Validates queries based on query language."""

    @staticmethod
    def validate_sql_query(query: str) -> Dict[str, Any]:
        """Validate SQL query for safety."""
        query_upper = query.upper().strip()

        # Remove comments and extra whitespace
        query_cleaned = re.sub(r'--.*?\n', '', query_upper)
        query_cleaned = re.sub(r'/\*.*?\*/', '', query_cleaned, flags=re.DOTALL)
        query_cleaned = ' '.join(query_cleaned.split())

        # Dangerous operations to block
        dangerous_operations = [
            'CREATE', 'ALTER', 'DROP', 'TRUNCATE',
            'INSERT', 'UPDATE', 'DELETE', 'MERGE',
            'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
            'CALL', 'DECLARE', 'SET @'
        ]

        # Check for dangerous operations
        for operation in dangerous_operations:
            if re.search(rf'\b{operation}\b', query_cleaned):
                return {
                    'is_safe': False,
                    'message': f"SQL query contains dangerous operation: {operation}",
                    'suggestions': [
                        "Use SELECT statements for data retrieval",
                        "Use aggregate functions (COUNT, SUM, AVG) for analysis",
                        "Use WHERE clauses to filter data"
                    ]
                }

        # Check if query starts with SELECT or other safe operations
        safe_starts = ['SELECT', 'WITH', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN']
        if not any(query_cleaned.startswith(safe_op) for safe_op in safe_starts):
            return {
                'is_safe': False,
                'message': "SQL query should start with SELECT, WITH, SHOW, DESCRIBE, or EXPLAIN",
                'suggestions': [
                    "Start queries with SELECT for data retrieval",
                    "Use WITH clauses for complex queries with CTEs",
                    "Use EXPLAIN for query analysis"
                ]
            }

        return {'is_safe': True, 'message': 'SQL query validation passed'}

    @staticmethod
    def validate_flux_query(query: str) -> Dict[str, Any]:
        """Validate InfluxDB Flux query for safety."""
        query_lower = query.lower().strip()

        # Flux queries typically start with from() or import
        if not (query_lower.startswith('from(') or query_lower.startswith('import')):
            return {
                'is_safe': False,
                'message': "Flux query should typically start with from() or import",
                'suggestions': [
                    "Use from(bucket: \"...\") to query data",
                    "Chain with |> range() to specify time range",
                    "Use |> filter() to filter data"
                ]
            }

        # Check for potentially dangerous Flux operations
        # Flux write operations
        dangerous_patterns = [
            r'\bto\s*\(',  # to() function writes data
            r'\bdelete\s*\(',  # delete() function
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, query_lower):
                return {
                    'is_safe': False,
                    'message': "Flux query contains write/delete operation",
                    'suggestions': [
                        "Use queries for data retrieval only",
                        "Use from() |> range() |> filter() for reading data"
                    ]
                }

        return {'is_safe': True, 'message': 'Flux query validation passed'}

    @staticmethod
    def validate_elasticsearch_query(query: str) -> Dict[str, Any]:
        """Validate Elasticsearch query (JSON DSL format)."""
        try:
            # Parse the query to ensure it's valid JSON
            query_dict = json.loads(query) if isinstance(query, str) else query

            # Basic validation
            if not isinstance(query_dict, dict):
                return {
                    'is_safe': False,
                    'message': 'Query must be a valid JSON object',
                    'suggestions': ['Ensure query is a valid JSON object']
                }
            # Check for unsafe operations (if needed)
            # For now, we allow all queries as Elasticsearch is primarily read-only
            return {
                'is_safe': True,
                'message': 'Elasticsearch query validation passed'
            }
        except json.JSONDecodeError as e:
            return {
                'is_safe': False,
                'message': f'Invalid JSON: {str(e)}',
                'suggestions': ['Fix JSON syntax errors']
            }
        except Exception as e:
            return {
                'is_safe': False,
                'message': f'Query validation failed: {str(e)}',
                'suggestions': []
            }

    @classmethod
    def validate_query(cls, query: str, query_language: QueryLanguage) -> Dict[str, Any]:
        """Validate query based on its language."""
        if query_language == QueryLanguage.SQL:
            return cls.validate_sql_query(query)
        elif query_language == QueryLanguage.FLUX:
            return cls.validate_flux_query(query)
        elif query_language == QueryLanguage.JSON:
            return cls.validate_elasticsearch_query(query)
        else:
            # For unknown query languages, do minimal validation
            return {
                'is_safe': True,
                'message': f'Basic validation passed for {query_language.value}'
            }

    @classmethod
    def validate_sql_ast(
        cls,
        query: str,
        dialect: Optional[str] = None,
        read_only: bool = True,
        require_pk_in_where: bool = False,
        primary_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """sqlglot-backed SQL safety validator.

        Parses *query* into an AST and enforces the configured policy:

        * Rejects unparseable SQL and multi-statement queries.
        * DDL (``Create``/``Drop``/``Alter``/``TruncateTable``/``Grant``/
          ``Revoke``) is **always** rejected.
        * ``read_only=True`` — allows only ``Select``/``Union``/``Intersect``/
          ``Except``/``With``/``Describe``/``Pragma`` and the read-only
          ``Command`` keywords ``EXPLAIN``/``SHOW``/``DESCRIBE``/``DESC``.
        * ``read_only=False`` — DML is permitted, but ``Update``/``Delete``
          must carry a ``WHERE`` clause.
        * When ``require_pk_in_where=True``, ``Update``/``Delete`` WHERE
          clauses must reference at least one column from ``primary_keys``.
          This prevents accidental full-table updates/deletes. When
          ``require_pk_in_where=True`` but ``primary_keys`` is empty or
          ``None``, the check is treated as a misconfiguration and the
          query is rejected.

        Falls back to the regex-based :meth:`validate_sql_query` when
        ``sqlglot`` is not installed.

        Args:
            query: Raw SQL string.
            dialect: Optional sqlglot dialect name (e.g. ``"postgres"``,
                ``"bigquery"``, ``"mysql"``). ``None`` uses sqlglot default.
            read_only: Whether to reject any write operation.
            require_pk_in_where: When ``True``, UPDATE/DELETE WHERE clauses
                must reference at least one column from ``primary_keys``.
                Defaults to ``False`` for backward compatibility.
            primary_keys: List of primary key column names used with
                ``require_pk_in_where=True``. Must be non-empty when
                ``require_pk_in_where`` is ``True``.

        Returns:
            Dict with ``is_safe`` (bool), ``message`` (str) and
            ``suggestions`` (list[str]) keys — same shape as the regex
            validator for drop-in interchangeability.
        """
        try:
            import sqlglot
            from sqlglot import exp
        except ImportError:
            return cls.validate_sql_query(query)

        try:
            statements = [
                s for s in sqlglot.parse(query, dialect=dialect) if s is not None
            ]
        except Exception as exc:
            return {
                'is_safe': False,
                'message': f'Failed to parse SQL: {exc}',
                'suggestions': ['Check SQL syntax'],
            }

        if not statements:
            return {
                'is_safe': False,
                'message': 'Empty query',
                'suggestions': ['Provide a SQL statement to execute'],
            }
        if len(statements) > 1:
            return {
                'is_safe': False,
                'message': 'Multiple statements are not permitted',
                'suggestions': ['Submit one statement at a time'],
            }

        root = statements[0]

        # DDL is blocked in every mode.
        ddl_nodes = (
            exp.Create, exp.Drop, exp.Alter,
            exp.TruncateTable, exp.Grant, exp.Revoke,
        )
        if isinstance(root, ddl_nodes):
            op = type(root).__name__
            return {
                'is_safe': False,
                'message': f"DDL operation '{op}' is not permitted",
                'suggestions': [
                    'Use SELECT for reads',
                    'Use INSERT / UPDATE / DELETE for writes',
                ],
            }

        safe_command_keywords = {'EXPLAIN', 'SHOW', 'DESCRIBE', 'DESC'}

        if read_only:
            read_nodes = (
                exp.Select, exp.Union, exp.Intersect, exp.Except,
                exp.With, exp.Describe, exp.Pragma,
            )
            if isinstance(root, read_nodes):
                return {'is_safe': True, 'message': 'SQL query validation passed'}
            if isinstance(root, exp.Command):
                keyword = str(root.this or '').upper().strip()
                if keyword in safe_command_keywords:
                    return {
                        'is_safe': True,
                        'message': 'SQL query validation passed',
                    }
                return {
                    'is_safe': False,
                    'message': f"Read-only mode: command '{keyword}' not permitted",
                    'suggestions': ['Use SELECT/WITH/EXPLAIN/SHOW only'],
                }
            op = type(root).__name__.upper()
            return {
                'is_safe': False,
                'message': f'Read-only mode: {op} not permitted',
                'suggestions': ['Use SELECT/WITH/EXPLAIN/SHOW only'],
            }

        # DML-permitted mode.
        if isinstance(root, (exp.Update, exp.Delete)):
            if root.args.get('where') is None:
                op = 'UPDATE' if isinstance(root, exp.Update) else 'DELETE'
                return {
                    'is_safe': False,
                    'message': f'{op} queries must include a WHERE clause',
                    'suggestions': [f'Add a WHERE clause to the {op} statement'],
                }
            # PK-presence check: when require_pk_in_where=True, at least one PK column
            # must appear in the WHERE clause to prevent accidental full-table writes.
            if require_pk_in_where:
                if not primary_keys:
                    return {
                        'is_safe': False,
                        'message': 'require_pk_in_where=True requires non-empty primary_keys',
                        'suggestions': [
                            'Pass primary_keys=[...] listing the table primary key columns',
                        ],
                    }
                where_node = root.args.get('where')
                if where_node is not None:
                    where_cols = {
                        c.name.lower()
                        for c in where_node.find_all(exp.Column)
                    }
                    pk_set = {pk.lower() for pk in primary_keys}
                    if not (where_cols & pk_set):
                        return {
                            'is_safe': False,
                            'message': (
                                f'WHERE clause must reference primary key column(s): '
                                f'{sorted(pk_set)}'
                            ),
                            'suggestions': [
                                f'Add a condition on one of: {", ".join(sorted(pk_set))}',
                            ],
                        }

        if isinstance(root, exp.Command):
            keyword = str(root.this or '').upper().strip()
            if keyword not in safe_command_keywords:
                return {
                    'is_safe': False,
                    'message': f"Command '{keyword}' is not permitted",
                    'suggestions': [
                        'Use SELECT/INSERT/UPDATE/DELETE/EXPLAIN/SHOW only',
                    ],
                }

        return {'is_safe': True, 'message': 'SQL query validation passed'}
