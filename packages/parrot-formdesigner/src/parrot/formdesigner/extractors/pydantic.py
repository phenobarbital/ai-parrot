"""Pydantic model extractor for FormSchema generation.

Introspects Pydantic v2 BaseModel classes and produces FormSchema instances.
Supports type mapping, Optional/Literal/Enum handling, nested models,
list types, and Field() metadata extraction.
"""

import re
import typing
from enum import Enum
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from ..core.constraints import FieldConstraints
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType


def _camel_to_title(name: str) -> str:
    """Convert CamelCase class name to Title Case string.

    Args:
        name: CamelCase class name.

    Returns:
        Human-readable title string.

    Example:
        _camel_to_title("UserProfile") == "User Profile"
    """
    # Insert space before uppercase letters preceded by lowercase
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    # Insert space between consecutive uppercase letters followed by lowercase
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return spaced.title()


def _snake_to_title(name: str) -> str:
    """Convert snake_case field name to Title Case string.

    Args:
        name: snake_case field name.

    Returns:
        Human-readable label string.
    """
    return name.replace("_", " ").title()


class PydanticExtractor:
    """Extracts FormSchema from Pydantic v2 BaseModel classes.

    Introspects model fields using Pydantic v2's model_fields API and
    maps Python type annotations to FormField/FieldType values.

    Supported mappings:
    - str -> TEXT
    - int -> INTEGER
    - float -> NUMBER
    - bool -> BOOLEAN
    - datetime.datetime -> DATETIME
    - datetime.date -> DATE
    - datetime.time -> TIME
    - Optional[T] -> required=False, type of T
    - Literal["a", "b"] -> SELECT with options
    - Enum subclass -> SELECT with enum values
    - nested BaseModel -> GROUP with children
    - list[T] -> ARRAY with item_template

    Example:
        extractor = PydanticExtractor()
        schema = extractor.extract(MyModel, title="My Form")
    """

    def extract(
        self,
        model: type[BaseModel],
        *,
        form_id: str | None = None,
        title: str | None = None,
        locale: str = "en",
    ) -> FormSchema:
        """Introspect a Pydantic model and produce a FormSchema.

        Args:
            model: Pydantic BaseModel subclass to introspect.
            form_id: Optional form identifier. Defaults to lowercase model name.
            title: Optional form title. Defaults to CamelCase-to-Title conversion.
            locale: Locale for generated labels.

        Returns:
            FormSchema representing the model's fields.
        """
        resolved_form_id = form_id or model.__name__.lower()
        resolved_title = title or _camel_to_title(model.__name__)

        fields = self._extract_fields_from_model(model)

        return FormSchema(
            form_id=resolved_form_id,
            title=resolved_title,
            sections=[
                FormSection(
                    section_id="fields",
                    title=resolved_title,
                    fields=fields,
                )
            ],
        )

    def _extract_fields_from_model(self, model: type[BaseModel]) -> list[FormField]:
        """Extract FormField list from a Pydantic model's fields.

        Args:
            model: Pydantic BaseModel subclass.

        Returns:
            List of FormField instances.
        """
        fields: list[FormField] = []
        for field_name, field_info in model.model_fields.items():
            form_field = self._field_info_to_form_field(
                field_name=field_name,
                field_info=field_info,
                annotation=model.__annotations__.get(field_name),
            )
            fields.append(form_field)
        return fields

    def _field_info_to_form_field(
        self,
        field_name: str,
        field_info: FieldInfo,
        annotation: Any,
    ) -> FormField:
        """Convert a single Pydantic FieldInfo to a FormField.

        Args:
            field_name: The field name as it appears in the model.
            field_info: Pydantic v2 FieldInfo instance.
            annotation: The raw type annotation from __annotations__.

        Returns:
            FormField instance.
        """
        # Resolve annotation from field_info if not provided
        if annotation is None:
            annotation = field_info.annotation

        # Unwrap Annotated[T, ...] → T
        resolved_annotation = self._unwrap_annotated(annotation)

        # Detect Optional[T] → required=False, unwrap to T
        is_optional, inner_type = self._unwrap_optional(resolved_annotation)

        # Determine requiredness using Pydantic v2's is_required() method
        is_required = not is_optional and field_info.is_required()

        # Determine field type and options
        field_type, options, children, item_template = self._determine_field_type(inner_type)

        # Extract label: use field title if set, otherwise snake_to_title
        label: str
        if field_info.title:
            label = field_info.title
        else:
            label = _snake_to_title(field_name)

        # Extract description
        description: str | None = field_info.description or None

        # Extract default (PydanticUndefined means no default)
        from pydantic_core import PydanticUndefined
        default: Any = None
        if field_info.default is not PydanticUndefined and field_info.default is not None:
            default = field_info.default

        # Extract constraints from FieldInfo metadata
        constraints = self._extract_constraints(field_info, field_type)

        return FormField(
            field_id=field_name,
            field_type=field_type,
            label=label,
            description=description,
            required=is_required,
            default=default,
            constraints=constraints if self._has_constraints(constraints) else None,
            options=options or None,
            children=children or None,
            item_template=item_template,
        )

    def _unwrap_annotated(self, annotation: Any) -> Any:
        """Unwrap Annotated[T, ...] to T.

        Args:
            annotation: Type annotation, possibly wrapped in Annotated.

        Returns:
            Unwrapped type.
        """
        if get_origin(annotation) is typing.Annotated:
            return get_args(annotation)[0]
        return annotation

    def _unwrap_optional(self, annotation: Any) -> tuple[bool, Any]:
        """Detect and unwrap Optional[T] (i.e., Union[T, None]).

        Args:
            annotation: Type annotation to inspect.

        Returns:
            Tuple of (is_optional, inner_type).
        """
        origin = get_origin(annotation)
        # Union[T, None] is Optional[T]
        if origin is typing.Union:
            args = get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if type(None) in args and len(non_none) == 1:
                return True, non_none[0]
        return False, annotation

    def _determine_field_type(
        self,
        annotation: Any,
    ) -> tuple[FieldType, list[FieldOption] | None, list[FormField] | None, FormField | None]:
        """Determine the FieldType and related data from a type annotation.

        Args:
            annotation: Resolved (unwrapped) type annotation.

        Returns:
            Tuple of (FieldType, options, children, item_template).
        """
        import datetime as dt

        origin = get_origin(annotation)
        args = get_args(annotation)

        # Literal["a", "b"] -> SELECT
        if origin is typing.Literal:
            options = [
                FieldOption(value=str(v), label=str(v))
                for v in args
            ]
            return FieldType.SELECT, options, None, None

        # list[T] or List[T] -> ARRAY
        if origin is list or annotation is list:
            item_template = None
            if args:
                item_type = args[0]
                item_field_type, item_options, item_children, _ = self._determine_field_type(item_type)
                item_template = FormField(
                    field_id="item",
                    field_type=item_field_type,
                    label="Item",
                    options=item_options or None,
                    children=item_children or None,
                )
            return FieldType.ARRAY, None, None, item_template

        # Enum subclass -> SELECT
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            options = [
                FieldOption(value=str(e.value), label=str(e.name).replace("_", " ").title())
                for e in annotation
            ]
            return FieldType.SELECT, options, None, None

        # Nested BaseModel -> GROUP
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            children = self._extract_fields_from_model(annotation)
            return FieldType.GROUP, None, children, None

        # Python primitive types
        type_map: dict[Any, FieldType] = {
            str: FieldType.TEXT,
            int: FieldType.INTEGER,
            float: FieldType.NUMBER,
            bool: FieldType.BOOLEAN,
            dt.datetime: FieldType.DATETIME,
            dt.date: FieldType.DATE,
            dt.time: FieldType.TIME,
        }

        if annotation in type_map:
            return type_map[annotation], None, None, None

        # Default fallback
        return FieldType.TEXT, None, None, None

    def _extract_constraints(
        self,
        field_info: FieldInfo,
        field_type: FieldType,
    ) -> FieldConstraints:
        """Extract FieldConstraints from Pydantic FieldInfo metadata.

        Reads ge/le/gt/lt constraints for numeric types, min_length/max_length
        and pattern for string types.

        Args:
            field_info: Pydantic v2 FieldInfo.
            field_type: Resolved FieldType for the field.

        Returns:
            FieldConstraints instance (may have all None values).
        """
        constraints = FieldConstraints()

        # Pydantic v2 stores metadata in field_info.metadata (list of validators)
        for meta in field_info.metadata:
            # String constraints
            if hasattr(meta, "min_length") and meta.min_length is not None:
                constraints.min_length = meta.min_length
            if hasattr(meta, "max_length") and meta.max_length is not None:
                constraints.max_length = meta.max_length
            if hasattr(meta, "pattern") and meta.pattern is not None:
                constraints.pattern = meta.pattern

            # Numeric constraints
            if hasattr(meta, "ge") and meta.ge is not None:
                constraints.min_value = float(meta.ge)
            if hasattr(meta, "gt") and meta.gt is not None:
                constraints.min_value = float(meta.gt)
            if hasattr(meta, "le") and meta.le is not None:
                constraints.max_value = float(meta.le)
            if hasattr(meta, "lt") and meta.lt is not None:
                constraints.max_value = float(meta.lt)

        return constraints

    def _has_constraints(self, constraints: FieldConstraints) -> bool:
        """Check if a FieldConstraints instance has any non-None values.

        Args:
            constraints: FieldConstraints to inspect.

        Returns:
            True if at least one constraint is set.
        """
        return any(
            v is not None
            for v in constraints.model_dump().values()
        )
