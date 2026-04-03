"""Unit tests for PydanticExtractor."""

import datetime
from enum import Enum
from typing import Literal, Optional

import pytest
from pydantic import BaseModel, Field

from parrot.forms import FieldType, FormSchema
from parrot.forms.extractors.pydantic import PydanticExtractor


@pytest.fixture
def extractor():
    """PydanticExtractor instance."""
    return PydanticExtractor()


class TestPydanticExtractorBasic:
    """Tests for basic type mapping."""

    def test_basic_model(self, extractor):
        """Simple str and int fields map to TEXT and INTEGER."""
        class User(BaseModel):
            name: str
            age: int

        schema = extractor.extract(User)
        assert schema.form_id == "user"
        fields = schema.sections[0].fields
        assert fields[0].field_type == FieldType.TEXT
        assert fields[1].field_type == FieldType.INTEGER

    def test_float_field(self, extractor):
        """float maps to NUMBER."""
        class Form(BaseModel):
            price: float

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].field_type == FieldType.NUMBER

    def test_bool_field(self, extractor):
        """bool maps to BOOLEAN."""
        class Form(BaseModel):
            active: bool

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].field_type == FieldType.BOOLEAN

    def test_datetime_field(self, extractor):
        """datetime.datetime maps to DATETIME."""
        class Form(BaseModel):
            created_at: datetime.datetime

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].field_type == FieldType.DATETIME

    def test_date_field(self, extractor):
        """datetime.date maps to DATE."""
        class Form(BaseModel):
            birthday: datetime.date

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].field_type == FieldType.DATE

    def test_form_id_defaults_to_lowercase_class_name(self, extractor):
        """form_id defaults to lowercase model name."""
        class UserProfile(BaseModel):
            name: str

        schema = extractor.extract(UserProfile)
        assert schema.form_id == "userprofile"

    def test_custom_form_id(self, extractor):
        """Custom form_id overrides default."""
        class MyModel(BaseModel):
            x: str

        schema = extractor.extract(MyModel, form_id="custom_form")
        assert schema.form_id == "custom_form"

    def test_title_defaults_to_camel_case_conversion(self, extractor):
        """title defaults to CamelCase-to-Title conversion."""
        class UserProfile(BaseModel):
            name: str

        schema = extractor.extract(UserProfile)
        assert "User" in schema.title
        assert "Profile" in schema.title

    def test_custom_title(self, extractor):
        """Custom title overrides default."""
        class MyModel(BaseModel):
            x: str

        schema = extractor.extract(MyModel, title="My Custom Form")
        assert schema.title == "My Custom Form"


class TestPydanticExtractorOptional:
    """Tests for Optional field handling."""

    def test_optional_field(self, extractor):
        """Optional[T] fields are not required."""
        class Form(BaseModel):
            notes: Optional[str] = None

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].required is False

    def test_required_field(self, extractor):
        """Non-optional fields without defaults are required."""
        class Form(BaseModel):
            name: str

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].required is True

    def test_field_with_default_not_required(self, extractor):
        """Fields with defaults are not required."""
        class Form(BaseModel):
            status: str = "active"

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].required is False


class TestPydanticExtractorLiteral:
    """Tests for Literal type handling."""

    def test_literal_becomes_select(self, extractor):
        """Literal["a", "b"] becomes SELECT with options."""
        class Form(BaseModel):
            color: Literal["red", "green", "blue"]

        schema = extractor.extract(Form)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.SELECT
        assert len(field.options) == 3

    def test_literal_option_values(self, extractor):
        """Literal options have correct value strings."""
        class Form(BaseModel):
            status: Literal["active", "inactive"]

        schema = extractor.extract(Form)
        values = {opt.value for opt in schema.sections[0].fields[0].options}
        assert values == {"active", "inactive"}


class TestPydanticExtractorEnum:
    """Tests for Enum type handling."""

    def test_enum_becomes_select(self, extractor):
        """Enum subclass becomes SELECT."""
        class Color(str, Enum):
            RED = "red"
            GREEN = "green"

        class Form(BaseModel):
            color: Color

        schema = extractor.extract(Form)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.SELECT

    def test_enum_options_populated(self, extractor):
        """Enum values appear as SELECT options."""
        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class Form(BaseModel):
            status: Status

        schema = extractor.extract(Form)
        values = {opt.value for opt in schema.sections[0].fields[0].options}
        assert "active" in values
        assert "inactive" in values


class TestPydanticExtractorNested:
    """Tests for nested model and list handling."""

    def test_nested_model_becomes_group(self, extractor):
        """Nested BaseModel becomes GROUP field with children."""
        class Address(BaseModel):
            street: str
            city: str

        class User(BaseModel):
            name: str
            address: Address

        schema = extractor.extract(User)
        addr_field = next(
            f for f in schema.sections[0].fields if f.field_id == "address"
        )
        assert addr_field.field_type == FieldType.GROUP
        assert len(addr_field.children) == 2

    def test_list_becomes_array(self, extractor):
        """list[str] becomes ARRAY field."""
        class Form(BaseModel):
            tags: list[str]

        schema = extractor.extract(Form)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.ARRAY

    def test_list_item_template(self, extractor):
        """list[str] ARRAY has item_template with TEXT type."""
        class Form(BaseModel):
            tags: list[str]

        schema = extractor.extract(Form)
        field = schema.sections[0].fields[0]
        assert field.item_template is not None
        assert field.item_template.field_type == FieldType.TEXT


class TestPydanticExtractorFieldMetadata:
    """Tests for Field() metadata extraction."""

    def test_field_constraints_extracted(self, extractor):
        """Field metadata (min_length, max_length, pattern) becomes constraints."""
        class Form(BaseModel):
            code: str = Field(..., min_length=3, max_length=10, pattern=r"^[A-Z]+$")

        schema = extractor.extract(Form)
        c = schema.sections[0].fields[0].constraints
        assert c is not None
        assert c.min_length == 3
        assert c.max_length == 10
        assert c.pattern == r"^[A-Z]+$"

    def test_numeric_constraints_extracted(self, extractor):
        """ge/le Field constraints map to min_value/max_value."""
        class Form(BaseModel):
            age: int = Field(..., ge=0, le=150)

        schema = extractor.extract(Form)
        c = schema.sections[0].fields[0].constraints
        assert c is not None
        assert c.min_value == 0.0
        assert c.max_value == 150.0

    def test_field_description(self, extractor):
        """Field description is extracted to FormField.description."""
        class Form(BaseModel):
            email: str = Field(..., description="Your work email address")

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].description == "Your work email address"

    def test_label_from_snake_case(self, extractor):
        """snake_case field name auto-converts to Title Case label."""
        class Form(BaseModel):
            first_name: str

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].label == "First Name"

    def test_no_constraints_when_not_set(self, extractor):
        """Fields without constraints have constraints=None."""
        class Form(BaseModel):
            name: str

        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].constraints is None

    def test_roundtrip_json(self, extractor):
        """Extracted schema survives JSON round-trip."""
        class Form(BaseModel):
            name: str
            age: int

        schema = extractor.extract(Form)
        json_str = schema.model_dump_json()
        restored = FormSchema.model_validate_json(json_str)
        assert restored.form_id == schema.form_id
