"""YAML ontology file loading and validation."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .schema import OntologyDefinition

logger = logging.getLogger("Parrot.Ontology.Parser")

# Path to package-bundled default ontology files
_DEFAULTS_DIR = Path(__file__).parent / "defaults"


class OntologyParser:
    """Load and validate ontology YAML files against Pydantic schema models.

    Usage::

        parser = OntologyParser()
        definition = parser.load(Path("ontologies/base.ontology.yaml"))
    """

    @staticmethod
    def load(path: Path) -> OntologyDefinition:
        """Load a YAML file and parse it into an OntologyDefinition.

        Args:
            path: Path to the YAML ontology file.

        Returns:
            Validated OntologyDefinition instance.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            yaml.YAMLError: If the file contains invalid YAML syntax.
            ValidationError: If the YAML content does not match the schema.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Ontology file not found: {path}")

        try:
            with open(path, encoding="utf-8") as f:
                raw: dict[str, Any] = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise yaml.YAMLError(
                f"Invalid YAML in {path}: {e}"
            ) from e

        try:
            definition = OntologyDefinition.model_validate(raw)
        except ValidationError as e:
            logger.error("Ontology validation failed for %s: %s", path, e)
            raise

        logger.debug("Loaded ontology '%s' from %s", definition.name, path)
        return definition

    @staticmethod
    def load_from_dict(data: dict[str, Any]) -> OntologyDefinition:
        """Parse an OntologyDefinition from an already-loaded dict.

        Args:
            data: Dictionary representation of the ontology YAML.

        Returns:
            Validated OntologyDefinition instance.

        Raises:
            ValidationError: If the dict does not match the schema.
        """
        return OntologyDefinition.model_validate(data)

    @staticmethod
    def load_default_base() -> OntologyDefinition:
        """Load the base ontology from package-bundled defaults.

        Returns:
            The base OntologyDefinition shipped with AI-Parrot.

        Raises:
            FileNotFoundError: If the default base file is missing.
        """
        base_path = _DEFAULTS_DIR / "base.ontology.yaml"
        return OntologyParser.load(base_path)

    @staticmethod
    def get_defaults_dir() -> Path:
        """Return the path to the package-bundled defaults directory.

        Returns:
            Path to the defaults/ directory within the ontology package.
        """
        return _DEFAULTS_DIR
