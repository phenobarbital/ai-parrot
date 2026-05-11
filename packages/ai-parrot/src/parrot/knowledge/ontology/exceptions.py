"""Custom exceptions for the Ontological Graph RAG system."""


class OntologyError(Exception):
    """Base exception for all ontology-related errors."""


class OntologyMergeError(OntologyError):
    """Raised during YAML merge when rules are violated.

    Examples:
        - Duplicate entity without ``extend: true``
        - Attempting to change an immutable field (key_field, collection)
        - Relation endpoint mismatch between layers
    """


class OntologyIntegrityError(OntologyError):
    """Raised during post-merge integrity validation.

    Examples:
        - Relation references a non-existent entity
        - Vectorize field references a non-existent property
    """


class AQLValidationError(OntologyError):
    """Raised when LLM-generated AQL fails safety validation.

    Examples:
        - AQL contains mutation keywords (INSERT, UPDATE, REMOVE)
        - Traversal depth exceeds ONTOLOGY_MAX_TRAVERSAL_DEPTH
        - Access to system collections (_system, _graphs)
        - Inline JavaScript execution attempts
    """


class UnknownDataSourceError(OntologyError):
    """Raised by DataSourceFactory when a source name cannot be resolved."""


class DataSourceValidationError(OntologyError):
    """Raised by ExtractDataSource.validate() when the source schema doesn't match.

    Examples:
        - Expected fields not found in data source
        - Source is inaccessible or returns unexpected format
    """


# ── FEAT-159: Ontology Curation Exceptions ──


class FrameworkOverrideError(OntologyError):
    """Raised when an overlay attempts to mutate a framework entity, relation, or pattern.

    Framework items (those in base.ontology.yaml) are immutable at runtime.
    No UI path or PG overlay may redefine them.

    Args:
        message: Human-readable error description.
        entity_name: Name of the framework entity/relation/pattern that was targeted.
    """

    def __init__(self, message: str, entity_name: str | None = None) -> None:
        self.entity_name = entity_name
        super().__init__(message)


class CycleError(OntologyError):
    """Raised when an is_a edge would create a cycle in the concept DAG.

    Cycle detection runs on every propose_isa_edge and approve call.
    The cycle path is stored for debugging.

    Args:
        message: Human-readable error description.
        cycle_path: Ordered list of node IDs/names forming the cycle.
    """

    def __init__(self, message: str, cycle_path: list[str] | None = None) -> None:
        self.cycle_path: list[str] = cycle_path or []
        super().__init__(message)


class SynonymConflictError(OntologyError):
    """Raised when a synonym conflicts with an existing approved concept synonym.

    Synonym uniqueness is enforced within a tenant's approved concepts.

    Args:
        message: Human-readable error description.
        synonym: The conflicting synonym string.
        existing_slug: Slug of the concept that already owns the synonym.
    """

    def __init__(
        self,
        message: str,
        synonym: str | None = None,
        existing_slug: str | None = None,
    ) -> None:
        self.synonym = synonym
        self.existing_slug = existing_slug
        super().__init__(message)


class DryRunFailedError(OntologyError):
    """Raised when a schema overlay dry-run fails validation.

    The dry-run report is stored so callers can surface check details to users.

    Args:
        message: Human-readable error description.
        report: The DryRunReport (or a plain dict) describing what failed.
    """

    def __init__(self, message: str, report: object | None = None) -> None:
        self.report = report
        super().__init__(message)


class InvalidTransitionError(OntologyError):
    """Raised when a state-machine transition is not permitted.

    Args:
        message: Human-readable error description.
        current_state: The current state of the entity.
        requested_action: The action that was attempted.
    """

    def __init__(
        self,
        message: str,
        current_state: str | None = None,
        requested_action: str | None = None,
    ) -> None:
        self.current_state = current_state
        self.requested_action = requested_action
        super().__init__(message)
