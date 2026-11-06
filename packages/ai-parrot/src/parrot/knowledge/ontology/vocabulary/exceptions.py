"""Typed errors of the ontology vocabulary store (FEAT-824)."""
from __future__ import annotations

from typing import Sequence

from parrot.knowledge.ontology.exceptions import OntologyError
from parrot.knowledge.ontology.vocabulary.contracts import ValidationIssue


class VocabularyError(OntologyError):
    """Base class for vocabulary-store errors."""


class OntologyNotFound(VocabularyError):
    """The ontology_id is not registered."""


class OntologyVersionNotFound(VocabularyError):
    """as_of names a version that was never published, or one a snapshot does not hold."""


class OntologyValidationError(VocabularyError):
    """Publication rejected; ``issues`` holds every ValidationIssue."""

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        self.issues = list(issues)
        issue_codes = ", ".join(issue.code for issue in self.issues)
        super().__init__(f"{len(self.issues)} issues: {issue_codes}")


class PublishConflict(VocabularyError):
    """The base version kept moving; bounded retries were exhausted."""
