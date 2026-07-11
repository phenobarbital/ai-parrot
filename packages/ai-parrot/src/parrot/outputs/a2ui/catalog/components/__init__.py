"""A2UI v1 catalog components (Module 3).

Importing this package runs each component module's ``@register_component``
side-effect, populating the catalog allowlist. Parallel Module 3 tasks each add
their own imports here (one per line, merge-friendly).
"""

from parrot.outputs.a2ui.catalog.components import chart  # noqa: F401
from parrot.outputs.a2ui.catalog.components import datatable  # noqa: F401
from parrot.outputs.a2ui.catalog.components import map  # noqa: F401
