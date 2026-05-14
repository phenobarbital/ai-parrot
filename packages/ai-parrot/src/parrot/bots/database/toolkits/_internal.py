"""DatabaseAgentToolkit — internal helper tools for DatabaseAgent.

Ports 16 utility helpers from AbstractDBAgent into a standalone, LLM-callable
toolkit. Gating logic (OutputComponent / QueryIntent filtering) lives at the
agent layer (Module 5 / TASK-1128); this module is component-agnostic.

Module 3 of FEAT-164 (database-agent-homologation).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from functools import wraps

from parrot.tools import tool
from parrot.tools.toolkit import AbstractToolkit

from ..models import OutputComponent

logger = logging.getLogger(__name__)


def _async_tool(func: Any) -> Any:
    """Apply @tool metadata while keeping the method a proper coroutine function.

    The stock @tool decorator wraps every function in a sync wrapper, which
    breaks inspect.iscoroutinefunction for async methods. This helper applies
    @tool for metadata extraction and then rewraps in an async function so
    that inspect.iscoroutinefunction returns True.
    """
    decorated = tool(func)

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    async_wrapper._is_tool = decorated._is_tool  # type: ignore[attr-defined]
    async_wrapper._tool_metadata = decorated._tool_metadata  # type: ignore[attr-defined]
    return async_wrapper


class DatabaseAgentToolkit(AbstractToolkit):
    """Internal helper toolkit for DatabaseAgent.

    Provides 16 stateless utilities for formatting, extracting, and generating
    database-related content. All methods are decorated with ``@tool`` so the
    LLM can call them directly. Async methods (#7, #10, #16) require ``await``.

    Args:
        session_maker: Optional async session factory used by
            ``get_schema_counts_direct``. When ``None``, that method returns
            ``(0, 0)`` immediately.
    """

    def __init__(self, session_maker: Optional[Callable] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session_maker = session_maker

    # ── 1 ──────────────────────────────────────────────────────────

    @tool
    def format_explain_plan(self, plan_json: str) -> str:
        """Format a PostgreSQL EXPLAIN ANALYZE JSON string into readable text.

        Args:
            plan_json: JSON string produced by ``EXPLAIN (ANALYZE, FORMAT JSON)``.

        Returns:
            Human-readable execution plan summary with cost, rows, and node details.
        """
        if not plan_json:
            return "No execution plan available"

        try:
            parsed = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
        except (json.JSONDecodeError, TypeError):
            return f"Could not parse plan JSON: {str(plan_json)[:200]}"

        if not parsed or not isinstance(parsed, list):
            return "No execution plan available"

        plan_data = parsed[0]
        main_plan = plan_data.get("Plan", {})

        lines: List[str] = []
        lines.append("=" * 60)
        lines.append("POSTGRESQL EXECUTION PLAN ANALYSIS")
        lines.append("=" * 60)

        if "Execution Time" in plan_data:
            lines.append(f"Overall Execution Time: {plan_data['Execution Time']:.3f}ms")
        if "Planning Time" in plan_data:
            lines.append(f"Planning Time: {plan_data['Planning Time']:.3f}ms")

        lines.append("")
        lines.append("Detailed Node Analysis:")
        lines.append("-" * 40)

        def _format_node(node: Dict[str, Any], level: int = 0) -> List[str]:
            indent = "  " * level
            node_type = node.get("Node Type", "Unknown")
            result = [f"{indent}{'└─' if level > 0 else '▶'} {node_type}"]

            startup = node.get("Startup Cost", 0)
            total = node.get("Total Cost", 0)
            if startup or total:
                result.append(f"{indent}   Cost: {startup:.2f}..{total:.2f}")

            plan_rows = node.get("Plan Rows")
            actual_rows = node.get("Actual Rows")
            if plan_rows is not None or actual_rows is not None:
                result.append(f"{indent}   Rows: {plan_rows or 'N/A'} planned → {actual_rows or 'N/A'} actual")

            if "Relation Name" in node:
                result.append(f"{indent}   Table: {node['Relation Name']}")

            for child in node.get("Plans", []):
                result.extend(_format_node(child, level + 1))

            return result

        lines.extend(_format_node(main_plan))
        return "\n".join(lines)

    # ── 2 ──────────────────────────────────────────────────────────

    @tool
    def simplify_column_type(self, raw_type: str) -> str:
        """Simplify a verbose SQL column type to its base name.

        Args:
            raw_type: Full column type string (e.g. ``"numeric(10,2)"`` or
                ``"timestamp without time zone"``).

        Returns:
            Base type name in lowercase (e.g. ``"numeric"``, ``"timestamp"``).
        """
        if not raw_type:
            return raw_type

        t = raw_type.strip().lower()

        # Strip size spec: numeric(10,2) → numeric
        paren_pos = t.find("(")
        if paren_pos != -1:
            t = t[:paren_pos].strip()

        # Strip trailing qualifiers for compound types
        # e.g. "timestamp without time zone" → "timestamp"
        # e.g. "character varying" → "character varying" (keep full alias)
        compound_prefixes = [
            "timestamp",
            "time",
            "interval",
            "double precision",
            "character varying",
        ]
        for prefix in compound_prefixes:
            if t.startswith(prefix):
                return prefix.split()[0] if " " not in prefix else prefix

        # Remove any trailing whitespace leftover
        return t.split()[0] if t else raw_type

    # ── 3 ──────────────────────────────────────────────────────────

    @tool
    def extract_sql_from_response(self, response_text: str) -> str:
        """Extract a SQL query from an LLM response that may contain markdown.

        Args:
            response_text: Raw LLM response text, optionally with ```sql blocks.

        Returns:
            Extracted SQL string, or empty string when none is found.
        """
        sql_patterns = [
            r"```sql\s*(.*?)\s*```",
            r"```SQL\s*(.*?)\s*```",
            r"```\s*(SELECT.*?(?:;|\Z))",
            r"```\s*(WITH.*?(?:;|\Z))",
        ]

        for pattern in sql_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL | re.IGNORECASE)
            if matches:
                sql = matches[0].strip()
                if sql:
                    return sql

        lines = response_text.split("\n")
        sql_lines: List[str] = []
        in_sql = False

        for line in lines:
            stripped = line.strip()
            upper = stripped.upper()
            if any(upper.startswith(kw) for kw in ["SELECT", "WITH", "INSERT", "UPDATE", "DELETE"]):
                in_sql = True
                sql_lines.append(stripped)
            elif in_sql:
                if stripped.endswith(";"):
                    sql_lines.append(stripped)
                    break
                elif not stripped or stripped.startswith("**") or stripped.startswith("#"):
                    break
                else:
                    sql_lines.append(stripped)

        if sql_lines:
            return "\n".join(sql_lines)

        if any(kw in response_text.upper() for kw in ["SELECT", "FROM", "WHERE"]):
            return response_text.strip()

        return ""

    # ── 4 ──────────────────────────────────────────────────────────

    @tool
    def extract_table_name_from_query(self, query: str) -> Optional[str]:
        """Extract the primary table name from a natural-language query or SQL.

        Args:
            query: User query or SQL fragment to extract a table name from.

        Returns:
            Extracted table name string, or ``None`` when not found.
        """
        patterns = [
            r"\bfrom\s+(?:[\w.]+\.)?(\w+)",
            r"\btable\s+(?:[\w.]+\.)?(\w+)",
            r"\bdescribe\s+(?:table\s+)?(?:[\w.]+\.)?(\w+)",
            r"\bstructure\s+of\s+(?:[\w.]+\.)?(\w+)",
            r"\brecords?\s+from\s+(?:[\w.]+\.)?(\w+)",
            r"\bdata\s+from\s+(?:[\w.]+\.)?(\w+)",
        ]

        false_positives = {
            "the", "in", "from", "with", "for", "about", "format",
            "return", "select", "where", "order", "group", "by",
            "limit", "offset", "having", "distinct",
        }

        query_lower = query.lower()
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                name = match.group(1)
                if name not in false_positives:
                    return name

        return None

    # ── 5 ──────────────────────────────────────────────────────────

    @tool
    def extract_table_names_from_metadata(self, metadata_context: str) -> List[str]:
        """Extract table names referenced in a YAML/text metadata context block.

        Args:
            metadata_context: Raw metadata string (YAML or plain text) describing schema.

        Returns:
            Deduplicated list of table names, up to 5 results.
        """
        if not metadata_context:
            return []
        matches = re.findall(r"table:\s+\w+\.(\w+)", metadata_context)
        return list(set(matches))[:5]

    # ── 6 ──────────────────────────────────────────────────────────

    @tool
    def generate_create_table_statement(self, table_yaml: str) -> str:
        """Generate a CREATE TABLE DDL statement from a YAML table descriptor.

        Args:
            table_yaml: YAML string describing the table with keys ``name``,
                ``schema``, and ``columns`` (list of name/type/nullable dicts).

        Returns:
            CREATE TABLE SQL statement string.
        """
        try:
            import yaml as _yaml  # type: ignore[import]
            table = _yaml.safe_load(table_yaml)
        except Exception:
            return f"-- Could not parse table_yaml\n-- {table_yaml[:200]}"

        schema = table.get("schema", "public")
        name = table.get("name", "unknown_table")
        full_name = f"{schema}.{name}"
        columns: List[Dict[str, Any]] = table.get("columns", [])

        if not columns:
            return f"-- No columns defined for {full_name}"

        col_defs: List[str] = []
        for col in columns:
            col_def = f'    "{col["name"]}" {col.get("type", "text")}'
            if not col.get("nullable", True):
                col_def += " NOT NULL"
            if col.get("default"):
                col_def += f" DEFAULT {col['default']}"
            col_defs.append(col_def)

        pks = table.get("primary_keys", [])
        if pks:
            pk_cols = ", ".join(f'"{pk}"' for pk in pks)
            col_defs.append(f"    PRIMARY KEY ({pk_cols})")

        body = ",\n".join(col_defs)
        return f"CREATE TABLE {full_name} (\n{body}\n);"

    # ── 7 — async ──────────────────────────────────────────────────

    @_async_tool
    async def generate_optimization_tips(self, sql_query: str, query_plan: str) -> List[str]:
        """Generate query optimization tips from SQL and execution plan text.

        Analyses the execution plan with pattern matching and returns actionable
        tips. When an LLM is available this can be overridden for richer output.

        Args:
            sql_query: The SQL statement that was executed.
            query_plan: EXPLAIN ANALYZE text output for the statement.

        Returns:
            List of optimization tip strings.
        """
        return self.generate_basic_optimization_tips(sql_query, query_plan)

    # ── 8 ──────────────────────────────────────────────────────────

    @tool
    def generate_basic_optimization_tips(self, sql_query: str, query_plan: str) -> List[str]:
        """Generate pattern-based optimization tips without an LLM call.

        Args:
            sql_query: The SQL statement that was executed.
            query_plan: EXPLAIN ANALYZE text output for the statement.

        Returns:
            List of optimization tip strings; at least one entry is always returned.
        """
        tips: List[str] = []
        plan_lower = query_plan.lower() if query_plan else ""
        query_lower = sql_query.lower() if sql_query else ""

        if "seq scan" in plan_lower:
            tips.append("Consider adding indexes on frequently filtered columns to avoid sequential scans")
        if "sort" in plan_lower:
            tips.append("Large sort operation detected — consider adding indexes for ORDER BY columns")
        if "nested loop" in plan_lower and "join" in query_lower:
            tips.append("Nested loop joins detected — ensure join columns are indexed")
        if "select *" in query_lower:
            tips.append("Avoid SELECT * — specify only needed columns for better performance")

        return tips or ["Query appears to be well-optimized"]

    # ── 9 ──────────────────────────────────────────────────────────

    @tool
    def generate_table_specific_tips(self, table_yaml: str) -> List[str]:
        """Generate query-development tips based on a YAML table descriptor.

        Args:
            table_yaml: YAML string describing tables (name, column count,
                row_count, has_indexes keys are optional).

        Returns:
            List of up to 4 targeted optimization and usage tips.
        """
        tips: List[str] = []
        try:
            import yaml as _yaml  # type: ignore[import]
            data = _yaml.safe_load(table_yaml)
        except Exception:
            return ["Could not parse table_yaml for tips"]

        if not data:
            return ["No table data available for specific tips"]

        tables = data if isinstance(data, list) else [data]
        names = [t.get("name", "unknown") for t in tables if isinstance(t, dict)]

        if len(tables) > 1:
            tips.append(f"Multiple tables detected — consider JOIN relationships between {', '.join(names)}")

        total_cols = sum(len(t.get("columns", [])) for t in tables if isinstance(t, dict))
        if total_cols > 20:
            tips.append("Many columns available — use SELECT specific_columns instead of SELECT *")

        large = [t.get("name") for t in tables if isinstance(t, dict) and t.get("row_count", 0) > 100_000]
        if large:
            tips.append(f"Large tables ({', '.join(large)}) — add WHERE filters and LIMIT clauses")

        indexed = [t.get("name") for t in tables if isinstance(t, dict) and t.get("has_indexes")]
        if indexed:
            tips.append("Indexed tables available — leverage existing indexes for optimal performance")

        return (tips or [f"Focus on the {len(tables)} table(s) structure for efficient query design"])[:4]

    # ── 10 — async ─────────────────────────────────────────────────

    @_async_tool
    async def generate_examples(self, schema_context: str, intent: str) -> List[str]:
        """Generate SQL usage examples from a schema context and query intent.

        Args:
            schema_context: Text description of available tables and columns.
            intent: Short description of what the user wants to accomplish.

        Returns:
            List of example SQL query strings.
        """
        tables = re.findall(r"(?:table|TABLE)[\s:]+(\w+(?:\.\w+)?)", schema_context)
        if not tables:
            tables = re.findall(r"(\w+)\s*\(", schema_context)

        examples: List[str] = []
        for table in tables[:2]:
            examples.extend([
                f"-- Example for {table} ({intent})",
                f"SELECT * FROM {table} LIMIT 10;",
                f"SELECT COUNT(*) FROM {table};",
            ])

        if not examples:
            examples = [
                f"-- No tables parsed from schema_context for intent: {intent}",
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';",
            ]

        return examples

    # ── 11 ─────────────────────────────────────────────────────────

    @tool
    def extract_performance_metrics(self, explain_analyze: str) -> Dict[str, Any]:
        """Extract key performance metrics from EXPLAIN ANALYZE text or JSON.

        Args:
            explain_analyze: EXPLAIN ANALYZE output (text or JSON string).

        Returns:
            Dictionary with keys ``execution_time_ms``, ``estimated_cost``,
            ``rows_examined``, ``index_usage``, ``scan_types``, and ``join_types``.
        """
        metrics: Dict[str, Any] = {
            "execution_time_ms": "N/A",
            "estimated_cost": "N/A",
            "rows_examined": "N/A",
            "index_usage": "Unknown",
            "scan_types": [],
            "join_types": [],
        }

        if not explain_analyze:
            return metrics

        # Try JSON first
        try:
            parsed = json.loads(explain_analyze)
            if isinstance(parsed, list) and parsed:
                plan_data = parsed[0]
                if "Execution Time" in plan_data:
                    metrics["execution_time_ms"] = plan_data["Execution Time"]
                main = plan_data.get("Plan", {})
                if "Total Cost" in main:
                    metrics["estimated_cost"] = main["Total Cost"]
                if "Actual Rows" in main:
                    metrics["rows_examined"] = main["Actual Rows"]

                def _scan(node: Dict[str, Any]) -> None:
                    nt = node.get("Node Type", "").lower()
                    if "scan" in nt:
                        metrics["scan_types"].append(node["Node Type"])
                        if "index" in nt:
                            metrics["index_usage"] = "Index scan"
                        elif "seq" in nt:
                            metrics["index_usage"] = "Sequential scan"
                    if "join" in nt:
                        metrics["join_types"].append(node["Node Type"])
                    for child in node.get("Plans", []):
                        _scan(child)

                _scan(main)
                metrics["scan_types"] = list(set(metrics["scan_types"]))
                metrics["join_types"] = list(set(metrics["join_types"]))
                return metrics
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Fallback: text parsing
        text = explain_analyze.lower()
        cost_match = re.search(r"cost:\s*([\d.]+)", explain_analyze)
        if cost_match:
            metrics["estimated_cost"] = float(cost_match.group(1))
        rows_match = re.search(r"rows=(\d+)", explain_analyze)
        if rows_match:
            metrics["rows_examined"] = int(rows_match.group(1))
        if "seq scan" in text:
            metrics["scan_types"].append("Sequential Scan")
            metrics["index_usage"] = "No indexes used"
        if "index scan" in text:
            metrics["scan_types"].append("Index Scan")
            metrics["index_usage"] = "Indexes used"

        return metrics

    # ── 12 ─────────────────────────────────────────────────────────

    @tool
    def format_as_text(self, data: Any, components: int = 0) -> str:
        """Format arbitrary data into a human-readable string based on active components.

        Args:
            data: Data to format — may be a string, list, dict, or ``None``.
            components: Bitmask of ``OutputComponent`` flags indicating what
                to include. Accepts an int (the underlying Flag value) — the
                type hint is ``int`` instead of ``OutputComponent`` because
                Gemini's ``FunctionDeclaration`` rejects enum members whose
                values are integers (it requires string enums).

        Returns:
            Formatted string representation of the data.
        """
        if data is None:
            return "No data available"

        components = OutputComponent(int(components or 0))

        parts: List[str] = []

        if components & OutputComponent.SQL_QUERY and isinstance(data, dict) and "query" in data:
            parts.append(f"**SQL Query:**\n```sql\n{data['query']}\n```")

        if components & OutputComponent.DATA_RESULTS:
            if isinstance(data, str):
                parts.append(data)
            elif isinstance(data, list):
                parts.append("\n".join(str(row) for row in data))
            elif isinstance(data, dict):
                rows = data.get("rows", data.get("data", data))
                parts.append(str(rows))

        if components & OutputComponent.DOCUMENTATION and isinstance(data, dict):
            doc = data.get("documentation", data.get("description", ""))
            if doc:
                parts.append(f"**Documentation:**\n{doc}")

        return "\n\n".join(parts) if parts else str(data)

    # ── 13 ─────────────────────────────────────────────────────────

    @tool
    def format_query_history(self, history: List[Dict[str, Any]]) -> str:
        """Format a list of previous query attempts into an LLM-readable string.

        Args:
            history: List of attempt dicts with keys ``attempt``, ``error_type``,
                and ``error``.

        Returns:
            Multi-line string summarising each attempt, or ``"No previous attempts."``.
        """
        if not history:
            return "No previous attempts."
        return "\n".join(
            f"Attempt {a.get('attempt', i + 1)}: "
            f"{a.get('error_type', 'Error')} — {a.get('error', 'unknown')}"
            for i, a in enumerate(history)
        )

    # ── 14 ─────────────────────────────────────────────────────────

    @tool
    def parse_tips(self, response_text: str) -> List[str]:
        """Parse structured optimization tips from an LLM response.

        Args:
            response_text: Raw LLM response expected to contain emoji-prefixed tip blocks.

        Returns:
            List of tip strings (only substantial tips with 50+ characters are kept).
        """
        tips: List[str] = []
        current: List[str] = []
        in_tip = False
        emoji_set = {"📊", "⚡", "🔗", "💾", "🔧", "📈", "🎯", "🔍"}

        for line in response_text.split("\n"):
            stripped = line.strip()
            starts_with_emoji = stripped and any(stripped[:2].startswith(e) for e in emoji_set)
            is_tip_header = starts_with_emoji and ("**" in stripped or starts_with_emoji)

            if is_tip_header:
                if current:
                    text = "\n".join(current).strip()
                    if len(text) > 50:
                        tips.append(text)
                current = [stripped]
                in_tip = True
            elif in_tip:
                current.append(stripped)

        if current:
            text = "\n".join(current).strip()
            if len(text) > 50:
                tips.append(text)

        return tips

    # ── 15 ─────────────────────────────────────────────────────────

    @tool
    def is_explanatory_response(self, response_text: str) -> bool:
        """Detect whether an LLM response is an explanation rather than SQL.

        Args:
            response_text: Raw LLM response text to classify.

        Returns:
            ``True`` when the response contains explanation language but no SQL.
        """
        text = response_text.strip().lower()

        explanation_patterns = [
            "i cannot", "i'm sorry", "i am sorry", "unable to",
            "cannot fulfill", "cannot generate", "cannot create",
            "does not contain", "missing", "not found", "no table",
            "no column", "not available", "insufficient information",
            "please provide", "you need to",
        ]
        sql_patterns = ["select", "from", "where", "order by", "group by", "insert", "update", "delete"]

        has_explanation = any(p in text for p in explanation_patterns)
        has_sql = any(p in text for p in sql_patterns)

        return has_explanation and not has_sql

    # ── 16 — async ─────────────────────────────────────────────────

    @_async_tool
    async def get_schema_counts_direct(self, schema_name: str) -> Tuple[int, int]:
        """Return the number of tables and views in a schema via information_schema.

        Args:
            schema_name: PostgreSQL schema name to count objects in.

        Returns:
            Tuple of ``(table_count, view_count)``. Returns ``(0, 0)`` when
            no session maker is configured.
        """
        if self._session_maker is None:
            logger.debug("get_schema_counts_direct: no session_maker configured, returning (0, 0)")
            return 0, 0

        try:
            from sqlalchemy import text as _text  # type: ignore[import]

            async with self._session_maker() as session:
                table_q = _text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
                )
                table_count = (await session.execute(table_q, {"s": schema_name})).scalar() or 0

                view_q = _text(
                    "SELECT COUNT(*) FROM information_schema.views WHERE table_schema = :s"
                )
                view_count = (await session.execute(view_q, {"s": schema_name})).scalar() or 0

                return int(table_count), int(view_count)

        except Exception as exc:
            logger.error("get_schema_counts_direct failed for %s: %s", schema_name, exc)
            return 0, 0
