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
