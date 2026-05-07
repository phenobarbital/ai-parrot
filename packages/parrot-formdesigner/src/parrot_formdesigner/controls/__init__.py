"""Form-control registry — extensible toolbar metadata.

Public API:

    from parrot_formdesigner.controls import (
        register_field_control, get_controls, iter_controls,
        FieldControlMetadata,
    )

Importing ``parrot_formdesigner.controls.builtin`` seeds the registry with
one entry per ``FieldType`` value. The default seed is loaded by
``parrot_formdesigner.api.__init__`` so that ``GET /api/v1/form-controls``
returns the full list from day one.
"""

from .registry import (
    FieldControlMetadata,
    get_controls,
    iter_controls,
    register_field_control,
)

__all__ = [
    "FieldControlMetadata",
    "get_controls",
    "iter_controls",
    "register_field_control",
]
