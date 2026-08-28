"""A2UI v1.0 parrot catalog components (Module 5, FEAT-470 TASK-2539).

Importing this package runs each component module's ``@register_component``
side-effect, populating the catalog allowlist under
:data:`~parrot.outputs.a2ui.catalog.base.DEFAULT_CATALOG_ID`
(``https://parrot.dev/catalogs/v1``).

``form`` is intentionally NOT imported here — ``Form`` is retired as a
registered component (spec G6); ``build_form()`` (TASK-2540) replaces it with
a composition helper over Basic Catalog primitives.
"""

from parrot.outputs.a2ui.catalog.parrot import (
    chart,  # noqa: F401
    datatable,  # noqa: F401
    infocard,  # noqa: F401
    infographic,  # noqa: F401
    kpicard,  # noqa: F401
    map,  # noqa: F401
    report,  # noqa: F401
    timeline,  # noqa: F401
)
