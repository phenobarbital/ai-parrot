# ============================================================================
# INTELLIGENT QUERY ROUTER
# ============================================================================
from typing import Any, Dict, List, Optional
import re
from .models import (
    UserRole,
    QueryIntent,
    RouteDecision,
    OutputComponent,
    get_default_components,
    INTENT_COMPONENT_MAPPING
)

# Intent → suggested UserRole mapping (FEAT-082)
INTENT_ROLE_MAPPING: Dict[QueryIntent, UserRole] = {
    QueryIntent.OPTIMIZE_QUERY: UserRole.DATABASE_ADMIN,
    QueryIntent.SHOW_DATA: UserRole.BUSINESS_USER,
    QueryIntent.GENERATE_QUERY: UserRole.DATA_ANALYST,
    QueryIntent.ANALYZE_DATA: UserRole.DATA_SCIENTIST,
    QueryIntent.EXPLORE_SCHEMA: UserRole.DEVELOPER,
    QueryIntent.VALIDATE_QUERY: UserRole.QUERY_DEVELOPER,
    QueryIntent.EXPLAIN_METADATA: UserRole.DEVELOPER,
    QueryIntent.CREATE_EXAMPLES: UserRole.DEVELOPER,
}


class SchemaQueryRouter:
    """Routes queries with multi-schema awareness and "show me" pattern recognition."""

    def __init__(self, primary_schema: str, allowed_schemas: List[str]):
        self.primary_schema = primary_schema
        self.allowed_schemas = allowed_schemas
        # Database identifiers → toolkit names (FEAT-082)
        self.registered_databases: Dict[str, str] = {}
        # Enhanced pattern matching
        # Patterns are matched against the lower-cased query. Each intent
        # carries both English and Spanish triggers — the agent is used by
        # a bilingual team and the previous English-only set silently fell
        # back to ``GENERATE_QUERY`` for Spanish prompts, so EXPLAIN /
        # optimization tools were never surfaced when the user wrote
        # "optimizá este query" in Spanish.
        self.patterns = {
            'show_data': [
                # English
                r'\bshow\s+me\b', r'\bdisplay\b', r'\blist\s+all\b',
                r'\bget\s+all\b', r'\bfind\s+all\b', r'\breturn\s+all\b',
                r'\bselect\s+.*\s+from\b',
                r'\bget\s+\w+\s+\d+\s+records?\b',
                r'\bget\s+(last|first|top)\s+\d+\b',
                r'\bshow\s+\d+\s+records?\b',
                r'\bfetch\s+\d+\s+records?\b',
                r'\breturn\s+\d+\s+records?\b',
                r'\bget\s+records?\s+from\b',
                r'\bselect\s+from\b',
                r'\blist\s+data\b',
                r'\bshow\s+data\b',
                # Spanish
                r'\bmu[eé]strame\b',
                r'\bmostrar\b',
                r'\bdame\s+(todos|todas|los|las)\b',
                r'\blistar?\s+(todos|todas|los|las)\b',
                r'\btraer?\s+(todos|todas|los|las)\b',
                r'\bobtener?\s+(todos|todas|los|las)\b',
                r'\bver\s+(los|las)\b',
                r'\b(los|las)\s+(primeros?|primeras?|[uú]ltimos?|[uú]ltimas?)\s+\d+\b',
                r'\btraer?\s+\d+\s+registros?\b',
                r'\bdame\s+\d+\s+registros?\b',
            ],
            'generate_query': [
                # English
                r'\bget\s+\w+\s+and\s+\w+\b', r'\bfind\s+\w+\s+where\b',
                r'\bcalculate\b', r'\bcount\b', r'\bsum\b', r'\baverage\b',
                r'\bget\s+.*\s+where\b',
                r'\bfind\s+.*\s+with\b',
                r'\bretrieve\s+.*\s+from\b',
                r'\bquery\s+.*\s+for\b',
                r'\bgenerate\s+.*\s+(query|sql)\b',
                # Spanish
                r'\bcalcular?\b',
                r'\bcontar?\b', r'\bcu[eé]nta(me)?\b',
                r'\bsuma(r)?\b',
                r'\bpromedio\b', r'\bpromediar?\b',
                r'\bagrupar?\b', r'\bagrupando\b',
                r'\bquiero\s+(saber|ver|consultar)\b',
                r'\bpuedes?\s+(dar(me)?|generar|crear|hacer)\s+(un|una)\s+(query|consulta)\b',
                r'\bgenera(r|me)?\s+(un|una)\s+(query|consulta|sql)\b',
                r'\bconsulta\s+que\b',
                r'\bdame\s+(un|una)\s+(query|consulta|sql)\b',
            ],
            'explore_schema': [
                # English
                r'\bwhat\s+tables?\b', r'\blist\s+tables?\b', r'\bshow\s+tables?\b',
                r'\bwhat\s+.*\s+available\b', r'\bschema\s+structure\b',
                r'\bdatabase\s+schema\b', r'\btable\s+structure\b',
                # Spanish
                r'\bqu[eé]\s+tablas?\b',
                r'\bcu[aá]les\s+tablas?\b',
                r'\blistar?\s+tablas?\b',
                r'\btablas?\s+(disponibles|hay|tenemos|existen)\b',
                r'\btenemos\s+(una\s+)?tabla\b',
                r'\bexiste\s+(una\s+)?tabla\b',
                r'\besquema\s+(de\s+la\s+)?(base\s+de\s+datos)?\b',
                r'\bestructura\s+(de\s+la\s+)?tabla\b',
            ],
            'explain_metadata': [
                # English
                r'\bmetadata\s+of\s+table\b',
                r'\bdescribe\s+table\b',
                r'\btable\s+.*\s+metadata\b',
                r'\bin\s+markdown\s+format\b',
                r'\bformat.*metadata\b',
                r'\bdocument\w*.*table\b',
                r'\bexplain\s+.*\s+structure\b',
                r'\bwhat\s+columns?\s+(does|has|are)\b',
                # Spanish
                r'\bdescribe?\s+(la\s+)?tabla\b',
                r'\bdescribir?\s+(la\s+)?tabla\b',
                r'\bmetadata\s+de\s+(la\s+)?tabla\b',
                r'\bqu[eé]\s+columnas?\s+tiene\b',
                r'\bcu[aá]les\s+(son\s+las\s+)?columnas?\b',
                r'\bdocumenta(r|me)?\s+(la\s+)?tabla\b',
                r'\bexplica(r|me)?\s+(la\s+)?(estructura|tabla|esquema)\b',
            ],
            'analyze_data': [
                # English
                r'\banalyze\b', r'\banalysis\b', r'\btrends?\b',
                r'\binsights?\b', r'\bpatterns?\b', r'\bstatistics\b',
                r'\bcorrelation\b', r'\bdistribution\b', r'\bcompare\b',
                # Spanish
                r'\banaliza(r|me)?\b',
                r'\ban[aá]lisis\b',
                r'\btendencias?\b',
                r'\bpatr(o|ó)n(es)?\b',
                r'\bestad[ií]sticas?\b',
                r'\bcorrelaci[oó]n\b',
                r'\bdistribuci[oó]n\b',
                r'\bcomparar?\b', r'\bcompara(me)?\b',
            ],
            'optimize_query': [
                # English
                r'\boptimiz\w+\b', r'\bperformance\b', r'\bslow\b',
                r'\bindex(es|ing)?\b', r'\btuning?\b',
                r'\bexplain\s+analyze\b', r'\bquery\s+plan\b',
                r'\bexecution\s+plan\b',
                r'\bsuggest\s+indexes?\b',
                r'\bbottleneck\b',
                r'\bmake\s+.*\s+faster\b',
                r'\bspeed\s+up\b',
                # Spanish (note: ``optimiz\w+`` above already matches
                # "optimizar/optimización" by suffix — these add the rest)
                r'\b[ií]ndices?\b',
                r'\brendimiento\b',
                r'\blent[oa]s?\b',
                r'\bm[aá]s\s+r[aá]pid[oa]\b',
                r'\bacelerar?\b', r'\bacelera(me|r|lo)\b',
                r'\bmejorar?\s+(el\s+|la\s+)?(rendimiento|performance|query|consulta|velocidad)\b',
                r'\bplan\s+de\s+ejecuci[oó]n\b',
                r'\bcuello\s+de\s+botella\b',
                r'\bsugerir?\s+[ií]ndices?\b',
                r'\bproponer?\s+[ií]ndices?\b',
                r'\bagregar?\s+[ií]ndices?\b',
                r'\bexplain\s+anal[ií]za(r|me)?\b',
            ],
            'create_examples': [
                # English
                r'\bexamples?\b', r'\bhow\s+to\s+use\b', r'\busage\b',
                r'\bshow.*examples?\b',
                # Spanish
                r'\bejemplos?\b',
                r'\bc[oó]mo\s+(usar|usarlo|usarla)\b',
                r'\buso\s+de\b',
                r'\bd[aá]me?\s+(un|unos)\s+ejemplos?\b',
            ],
        }

    def register_database(self, identifier: str, toolkit_name: str) -> None:
        """Register a database identifier for query routing.

        Args:
            identifier: Keyword that triggers routing (e.g. "postgres", "pg", "bigquery").
            toolkit_name: Name of the toolkit to route to.
        """
        self.registered_databases[identifier.lower()] = toolkit_name

    def _detect_target_database(self, query: str) -> Optional[str]:
        """Detect which registered database is mentioned in the query."""
        query_lower = query.lower()
        for identifier, toolkit_name in self.registered_databases.items():
            if identifier in query_lower:
                return toolkit_name
        return None

    def _infer_role(self, intent: QueryIntent) -> Optional[UserRole]:
        """Infer a suggested UserRole from QueryIntent."""
        return INTENT_ROLE_MAPPING.get(intent)

    async def route(
        self,
        query: str,
        user_role: Optional[UserRole] = None,
        output_components: Optional[OutputComponent] = None,
        intent_override: Optional[QueryIntent] = None,
        database: Optional[str] = None,
    ) -> RouteDecision:
        """Enhanced routing with database selection and role inference.

        Role resolution (three-tier):
          1. Explicit ``user_role`` parameter → ``role_source="explicit"``
          2. Inferred from ``QueryIntent`` → ``role_source="inferred"``
          3. Default ``DATA_ANALYST`` → ``role_source="default"``

        Database selection:
          1. Explicit ``database`` parameter
          2. Detected from query text via registered database identifiers
          3. ``None`` (let the agent decide)
        """
        # Step 1: Determine intent
        if intent_override:
            intent = intent_override
        else:
            intent = self._detect_intent(query)

        # Step 2: Three-tier role resolution
        role_source = "default"
        effective_role = UserRole.DATA_ANALYST
        if user_role is not None:
            effective_role = user_role
            role_source = "explicit"
        else:
            inferred = self._infer_role(intent)
            if inferred is not None:
                effective_role = inferred
                role_source = "inferred"

        # Step 3: Database selection
        target_database = database  # explicit first
        if target_database is None:
            target_database = self._detect_target_database(query)

        # Step 4: Get base components for role
        if output_components is None:
            base_components = get_default_components(effective_role)
            intent_components = INTENT_COMPONENT_MAPPING.get(intent, OutputComponent.NONE)
            final_components = base_components | intent_components
        else:
            final_components = output_components

        # Step 5: Configure execution parameters
        execution_config = self._configure_execution(intent, effective_role, final_components)

        # Step 6: Special handling for specific roles
        execution_config = self._apply_role_specific_config(
            execution_config, effective_role, final_components
        )

        return RouteDecision(
            intent=intent,
            components=final_components,
            user_role=effective_role,
            primary_schema=self.primary_schema,
            allowed_schemas=self.allowed_schemas,
            target_database=target_database,
            role_source=role_source,
            **execution_config,
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

        # Determine if we need query generation
        # ANY component that requires data needs query generation
        data_requiring_components = {
            OutputComponent.DATA_RESULTS,
            OutputComponent.DATAFRAME_OUTPUT,
            OutputComponent.SAMPLE_DATA,
            OutputComponent.SQL_QUERY  # Obviously needs query generation
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

        if any(comp in components for comp in data_requiring_components):
            config['needs_query_generation'] = True

        # Components that require actual query execution
        execution_requiring_components = {
            OutputComponent.DATA_RESULTS,
            OutputComponent.DATAFRAME_OUTPUT,
            OutputComponent.SAMPLE_DATA,
            OutputComponent.EXECUTION_PLAN,
            OutputComponent.PERFORMANCE_METRICS
        }

        if any(comp in components for comp in execution_requiring_components):
            config['needs_execution'] = True

        # Intent-specific configuration
        if intent == QueryIntent.SHOW_DATA:
            config['execution_options']['timeout'] = 30
        elif intent == QueryIntent.ANALYZE_DATA:
            config['execution_options']['timeout'] = 60  # More time for complex analysis

        return config

    def _apply_role_specific_config(
        self,
        config: Dict[str, Any],
        user_role: UserRole,
        components: OutputComponent
    ) -> Dict[str, Any]:
        """Apply role-specific configuration overrides."""

        if user_role == UserRole.BUSINESS_USER:
            # Business users want all data, with a sane upper bound
            config['include_full_data'] = True
            config['data_limit'] = 100_000

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
