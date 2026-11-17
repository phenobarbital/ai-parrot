"""Form schema extractors for the formdesigner package.

Extractors convert external sources (Pydantic models, tool args schemas,
YAML files, JSON Schema) into the canonical FormSchema representation.
"""

import importlib
from typing import TYPE_CHECKING

from .jsonschema import JSONSchemaExtractor, JsonSchemaExtractor
from .pydantic import PydanticExtractor
from .tool import ToolExtractor
from .yaml import YAMLExtractor, YamlExtractor

# FEAT-650 — the A2UI extractor imports ai-parrot lazily inside its functions, but keep the symbol itself lazy too
# (PEP 562, same pattern as renderers/__init__.py) so `import parrot_formdesigner.extractors` stays cheap.
_LAZY_EXPORTS = {
    "A2UIExtractor": ".a2ui",
    "ExtractedForm": ".a2ui",
    "ExtractionMode": ".a2ui",
    "DroppedComponent": ".a2ui",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path, package=__name__), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from .a2ui import A2UIExtractor, DroppedComponent, ExtractedForm, ExtractionMode

__all__ = [
    "A2UIExtractor",
    "DroppedComponent",
    "ExtractedForm",
    "ExtractionMode",
    "JsonSchemaExtractor",
    "JSONSchemaExtractor",
    "PydanticExtractor",
    "ToolExtractor",
    "YamlExtractor",
    "YAMLExtractor",
]
