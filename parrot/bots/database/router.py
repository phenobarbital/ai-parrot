# ============================================================================
# INTELLIGENT QUERY ROUTER
# ============================================================================
from typing import Any, Dict, List, Optional
import re
from .models import (
    UserRole,
    QueryIntent,
    ReturnFormat,
    RouteDecision
)

class SchemaQueryRouter:
    """Routes queries with multi-schema awareness and "show me" pattern recognition."""

    def __init__(self, primary_schema: str, allowed_schemas: List[str]):
        self.primary_schema = primary_schema
        self.allowed_schemas = allowed_schemas
        self.show_patterns = [
            r'\bshow\s+me\b',
            r'\bdisplay\b',
            r'\blist\s+all\b',
            r'\bget\s+all\b',
            r'\bfind\s+all\b'
        ]

        self.analysis_patterns = [
            r'\banalyze\b', r'\banalysis\b', r'\btrends?\b',
            r'\binsights?\b', r'\bpatterns?\b', r'\bstatistics\b',
            r'\bcorrelation\b', r'\bdistribution\b'
        ]

        self.generation_patterns = [
            r'\bget\s+\w+\s+and\s+\w+\b',  # "get username and job_code"
            r'\bfind\s+\w+\s+where\b',     # "find users where..."
            r'\bcalculate\b', r'\bcount\b', r'\bsum\b', r'\baverage\b'
        ]

    async def route(
        self,
        query: str,
        user_role: UserRole,
        return_format: Optional[ReturnFormat] = None
    ) -> RouteDecision:
        """Route query based on patterns and user context."""

        query_lower = query.lower().strip()

        # Detect if query contains raw SQL
        if self._is_raw_sql(query):
            intent = QueryIntent.VALIDATE_QUERY
            needs_generation = False
        # Detect "show me" pattern
        elif any(re.search(pattern, query_lower) for pattern in self.show_patterns):
            intent = QueryIntent.SHOW_DATA
            needs_generation = True  # Convert "show me users" to "SELECT * FROM users"
        # Detect analysis patterns
        elif any(re.search(pattern, query_lower) for pattern in self.analysis_patterns):
            intent = QueryIntent.ANALYZE_DATA
            needs_generation = True
        # Detect complex query generation
        elif any(re.search(pattern, query_lower) for pattern in self.generation_patterns):
            intent = QueryIntent.GENERATE_QUERY
            needs_generation = True
        # Schema exploration
        elif any(word in query_lower for word in ['tables', 'schema', 'structure', 'columns']):
            intent = QueryIntent.EXPLORE_SCHEMA
            needs_generation = False  # Use schema tools instead
        else:
            # Default to query generation
            intent = QueryIntent.GENERATE_QUERY
            needs_generation = True

        # Determine return format
        if return_format is None:
            return_format = self._determine_return_format(intent, user_role)

        # Configure execution options
        execution_options = self._configure_execution(intent, user_role)

        return RouteDecision(
            intent=intent,
            return_format=return_format,
            primary_schema=self.primary_schema,
            allowed_schemas=self.allowed_schemas,
            needs_metadata_discovery=intent != QueryIntent.VALIDATE_QUERY,
            needs_query_generation=needs_generation,
            needs_execution=return_format != ReturnFormat.QUERY_ONLY,
            execution_options=execution_options
        )

    def _is_raw_sql(self, query: str) -> bool:
        """Check if query is raw SQL."""
        sql_keywords = ['select', 'insert', 'update', 'delete', 'with', 'explain']
        query_lower = query.strip().lower()
        return any(query_lower.startswith(keyword) for keyword in sql_keywords)

    def _determine_return_format(self, intent: QueryIntent, user_role: UserRole) -> ReturnFormat:
        """Determine return format based on intent and user role."""

        if intent == QueryIntent.SHOW_DATA:
            # "Show me" = user wants data
            if user_role == UserRole.BUSINESS_USER:
                return ReturnFormat.DATA_ONLY
            else:
                return ReturnFormat.QUERY_AND_DATA

        elif intent == QueryIntent.ANALYZE_DATA:
            return ReturnFormat.QUERY_DATA_EXPLANATION

        elif intent == QueryIntent.VALIDATE_QUERY:
            return ReturnFormat.QUERY_DATA_EXPLANATION

        elif intent == QueryIntent.EXPLORE_SCHEMA:
            return ReturnFormat.DATA_ONLY

        else:  # GENERATE_QUERY
            if user_role == UserRole.BUSINESS_USER:
                return ReturnFormat.DATA_ONLY
            else:
                return ReturnFormat.QUERY_AND_DATA

    def _configure_execution(self, intent: QueryIntent, user_role: UserRole) -> Dict[str, Any]:
        """Configure execution options."""
        options = {"limit": 1000, "timeout": 30}

        if intent == QueryIntent.SHOW_DATA:
            options["limit"] = 100  # Smaller limit for "show me" queries

        elif intent == QueryIntent.ANALYZE_DATA:
            options["limit"] = 5000  # More data for analysis
            options["explain_analyze"] = True

        elif user_role == UserRole.DATABASE_ADMIN:
            options["explain_analyze"] = True
            options["timeout"] = 60

        return options
