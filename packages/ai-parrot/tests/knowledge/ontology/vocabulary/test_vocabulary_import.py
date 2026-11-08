"""Import-ceiling tests for the ontology vocabulary package."""

from ..._support.import_probe import run_import_probe


def test_package_import_is_light() -> None:
    """Importing the package root does not load optional heavy dependencies."""
    result = run_import_probe("parrot.knowledge.ontology.vocabulary")

    assert result.error is None
    assert not result.has("asyncpg")
    assert not result.has("rdflib")
    assert not result.has("numpy")
