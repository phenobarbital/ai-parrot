"""Tests for ontology YAML parser."""
import yaml
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import OntologyDefinition


@pytest.fixture
def valid_yaml(tmp_path: Path) -> Path:
    """Create a valid ontology YAML file."""
    p = tmp_path / "test.ontology.yaml"
    p.write_text(yaml.dump({
        "name": "test_ontology",
        "version": "1.0",
        "description": "Test ontology",
        "entities": {
            "Employee": {
                "collection": "employees",
                "key_field": "employee_id",
                "properties": [
                    {"name": {"type": "string", "required": True}},
                    {"email": {"type": "string"}},
                ],
                "vectorize": ["name"],
            }
        },
        "relations": {
            "reports_to": {
                "from": "Employee",
                "to": "Employee",
                "edge_collection": "reports_to",
            }
        },
        "traversal_patterns": {
            "find_manager": {
                "description": "Find employee manager",
                "trigger_intents": ["my manager", "who is my manager"],
                "query_template": "FOR v IN 1..1 OUTBOUND @uid reports_to RETURN v",
                "post_action": "none",
            }
        },
    }))
    return p


@pytest.fixture
def invalid_yaml_schema(tmp_path: Path) -> Path:
    """Create a YAML file with invalid schema."""
    p = tmp_path / "invalid.ontology.yaml"
    p.write_text(yaml.dump({
        "name": "bad",
        "entities": {
            "Employee": {
                "collection": "employees",
                "bogus_field": "should fail",  # extra="forbid"
            }
        },
    }))
    return p


@pytest.fixture
def invalid_yaml_syntax(tmp_path: Path) -> Path:
    """Create a file with invalid YAML syntax."""
    p = tmp_path / "bad_syntax.yaml"
    p.write_text("name: test\n  bad indent: [unclosed")
    return p


class TestOntologyParser:

    def test_load_valid(self, valid_yaml: Path):
        result = OntologyParser.load(valid_yaml)
        assert isinstance(result, OntologyDefinition)
        assert result.name == "test_ontology"
        assert "Employee" in result.entities
        assert result.entities["Employee"].collection == "employees"
        assert "reports_to" in result.relations
        assert "find_manager" in result.traversal_patterns

    def test_load_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            OntologyParser.load(tmp_path / "nonexistent.yaml")

    def test_load_invalid_schema(self, invalid_yaml_schema: Path):
        with pytest.raises(ValidationError):
            OntologyParser.load(invalid_yaml_schema)

    def test_load_from_dict(self):
        data = {
            "name": "dict_test",
            "version": "2.0",
            "entities": {},
        }
        result = OntologyParser.load_from_dict(data)
        assert result.name == "dict_test"
        assert result.version == "2.0"

    def test_load_from_dict_invalid(self):
        with pytest.raises(ValidationError):
            OntologyParser.load_from_dict({"name": "x", "bogus": "y"})

    def test_defaults_dir_exists(self):
        defaults = OntologyParser.get_defaults_dir()
        assert defaults.exists()
        assert defaults.is_dir()

    def test_relation_alias(self, valid_yaml: Path):
        result = OntologyParser.load(valid_yaml)
        rel = result.relations["reports_to"]
        assert rel.from_entity == "Employee"
        assert rel.to_entity == "Employee"

    def test_traversal_pattern_fields(self, valid_yaml: Path):
        result = OntologyParser.load(valid_yaml)
        pattern = result.traversal_patterns["find_manager"]
        assert pattern.post_action == "none"
        assert "my manager" in pattern.trigger_intents

    def test_empty_yaml(self, tmp_path: Path):
        """Empty YAML (parsed as None) should fail validation."""
        p = tmp_path / "empty.yaml"
        p.write_text("")
        with pytest.raises(ValidationError):
            OntologyParser.load(p)
