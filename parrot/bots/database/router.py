# ============================================================================
# INTELLIGENT QUERY ROUTER
# ============================================================================
from typing import Any, Dict, List, Optional
import re
from .models import (
    UserRole,
    QueryIntent,
    OutputFormat,
    RouteDecision,
    OutputComponent,
    get_default_components,
    INTENT_COMPONENT_MAPPING,
    ROLE_COMPONENT_DEFAULTS
)

class SchemaQueryRouter:
    """Routes queries with multi-schema awareness and "show me" pattern recognition."""

    def __init__(self, primary_schema: str, allowed_schemas: List[str]):
        self.primary_schema = primary_schema
        self.allowed_schemas = allowed_schemas
        # Enhanced pattern matching
        self.patterns = {
            # Data retrieval patterns
            'show_data': [
                r'\bshow\s+me\b', r'\bdisplay\b', r'\blist\s+all\b',
                r'\bget\s+all\b', r'\bfind\s+all\b', r'\breturn\s+all\b',
                r'\bselect\s+.*\s+from\b'
            ],

            # Analysis patterns
            'analyze_data': [
                r'\banalyze\b', r'\banalysis\b', r'\btrends?\b',
                r'\binsights?\b', r'\bpatterns?\b', r'\bstatistics\b',
                r'\bcorrelation\b', r'\bdistribution\b', r'\bcompare\b'
            ],

            # Schema exploration
            'explore_schema': [
                r'\btables?\b', r'\bschema\b', r'\bstructure\b',
                r'\bcolumns?\b', r'\bdescribe\b', r'\bmetadata\b',
                r'\bwhat\s+.*\s+available\b'
            ],

            # Optimization focus
            'optimize_query': [
                r'\boptimiz\w+\b', r'\bperformance\b', r'\bslow\b',
                r'\bindex\b', r'\btuning?\b', r'\bexplain\b'
            ],

            # Documentation requests
            'explain_metadata': [
                r'\bexplain\b', r'\bdocument\w*\b', r'\bmetadata\b',
                r'\bin\s+markdown\s+format\b', r'\bformat.*metadata\b'
            ],

            # Example requests
            'create_examples': [
                r'\bexamples?\b', r'\bhow\s+to\s+use\b', r'\busage\b',
                r'\bshow.*examples?\b'
            ],

            # Query generation
            'generate_query': [
                r'\bget\s+\w+\s+and\s+\w+\b', r'\bfind\s+\w+\s+where\b',
                r'\bcalculate\b', r'\bcount\b', r'\bsum\b', r'\baverage\b'
            ]
        }

    async def route(
        self,
        query: str,
        user_role: UserRole,
        output_components: Optional[OutputComponent] = None,
        intent_override: Optional[QueryIntent] = None
    ) -> RouteDecision:
        """Enhanced routing with component-based decisions."""

        # Step 1: Determine intent
        if intent_override:
            intent = intent_override
        else:
            intent = self._detect_intent(query)

        # Step 2: Get base components for role
        if output_components is None:
            # Use role defaults + intent additions
            base_components = get_default_components(user_role)
            intent_components = INTENT_COMPONENT_MAPPING.get(intent, OutputComponent.NONE)
            final_components = base_components | intent_components
        else:
            final_components = output_components

        # Step 3: Configure execution parameters
        execution_config = self._configure_execution(intent, user_role, final_components)

        # Step 4: Special handling for specific roles
        execution_config = self._apply_role_specific_config(
            execution_config, user_role, final_components
        )

        return RouteDecision(
            intent=intent,
            components=final_components,
            user_role=user_role,
            primary_schema=self.primary_schema,
            allowed_schemas=self.allowed_schemas,
            **execution_config
        )

    def _is_raw_sql(self, query: str) -> bool:
        """Check if query is raw SQL."""
        sql_keywords = ['select', 'insert', 'update', 'delete', 'with', 'explain']
        query_lower = query.strip().lower()
        return any(query_lower.startswith(keyword) for keyword in sql_keywords)

    def _detect_intent(self, query: str) -> QueryIntent:
        """Detect query intent from patterns."""
        query_lower = query.lower().strip()

        # Check if query contains raw SQL
        if self._is_raw_sql(query):
            return QueryIntent.VALIDATE_QUERY

        # Pattern matching for different intents
        for intent_name, patterns in self.patterns.items():
            if any(re.search(pattern, query_lower) for pattern in patterns):
                return QueryIntent(intent_name)

        # Default to query generation
        return QueryIntent.GENERATE_QUERY

    def _configure_execution(
        self,
        intent: QueryIntent,
        user_role: UserRole,
        components: OutputComponent
    ) -> Dict[str, Any]:
        """Configure execution parameters based on intent, role, and components."""

        config = {
            'needs_metadata_discovery': True,
            'needs_query_generation': True,
            'needs_execution': True,
            'needs_plan_analysis': False,
            'data_limit': 1000,
            'include_full_data': False,
            'convert_to_dataframe': False,
            'execution_options': {
                'timeout': 30,
                'explain_analyze': False
            }
        }

        # Intent-based configuration
        if intent == QueryIntent.VALIDATE_QUERY:
            config['needs_query_generation'] = False
            config['needs_metadata_discovery'] = False

        elif intent == QueryIntent.EXPLORE_SCHEMA:
            config['needs_execution'] = False
            config['needs_query_generation'] = False

        elif intent == QueryIntent.OPTIMIZE_QUERY:
            config['needs_plan_analysis'] = True
            config['execution_options']['explain_analyze'] = True

        # Component-based configuration
        if OutputComponent.EXECUTION_PLAN in components:
            config['needs_plan_analysis'] = True
            config['execution_options']['explain_analyze'] = True

        if OutputComponent.DATAFRAME_OUTPUT in components:
            config['convert_to_dataframe'] = True

        if OutputComponent.DATA_RESULTS not in components:
            config['needs_execution'] = False

        return config

    def _apply_role_specific_config(
        self,
        config: Dict[str, Any],
        user_role: UserRole,
        components: OutputComponent
    ) -> Dict[str, Any]:
        """Apply role-specific configuration overrides."""

        if user_role == UserRole.BUSINESS_USER:
            # Business users want all data, no limits
            config['include_full_data'] = True
            config['data_limit'] = None

        elif user_role == UserRole.DATA_SCIENTIST:
            # Data scientists get DataFrame output by default
            if OutputComponent.DATAFRAME_OUTPUT in components:
                config['convert_to_dataframe'] = True
            config['data_limit'] = 10000  # Larger limit for analysis

        elif user_role == UserRole.DATABASE_ADMIN:
            # DBAs get performance analysis
            config['needs_plan_analysis'] = True
            config['execution_options']['explain_analyze'] = True
            config['execution_options']['timeout'] = 60  # Longer timeout
            config['data_limit'] = 100  # Limited data, focus on performance

        elif user_role == UserRole.DEVELOPER:
            # Developers don't need data execution by default
            if OutputComponent.DATA_RESULTS not in components:
                config['needs_execution'] = False

        elif user_role == UserRole.DATA_ANALYST:
            # Analysts get balanced configuration
            config['data_limit'] = 5000

        return config
