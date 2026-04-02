"""Unit tests for form style models."""

import pytest
from parrot.forms import FieldSizeHint, FieldStyleHint, LayoutType, StyleSchema


class TestStyleSchema:
    """Tests for StyleSchema model."""

    def test_default_layout(self):
        """StyleSchema defaults to SINGLE_COLUMN layout."""
        style = StyleSchema()
        assert style.layout == LayoutType.SINGLE_COLUMN

    def test_custom_layout(self):
        """StyleSchema accepts custom layout types."""
        style = StyleSchema(layout=LayoutType.WIZARD)
        assert style.layout == LayoutType.WIZARD

    def test_default_labels(self):
        """StyleSchema has default submit and cancel labels."""
        style = StyleSchema()
        assert style.submit_label == "Submit"
        assert style.cancel_label == "Cancel"

    def test_localized_labels(self):
        """StyleSchema accepts localized submit/cancel labels."""
        style = StyleSchema(
            submit_label={"en": "Send", "es": "Enviar"},
            cancel_label={"en": "Abort", "es": "Cancelar"},
        )
        assert style.submit_label["en"] == "Send"

    def test_field_styles(self):
        """StyleSchema accepts per-field style hints."""
        style = StyleSchema(
            field_styles={
                "name": FieldStyleHint(size=FieldSizeHint.FULL),
                "age": FieldStyleHint(size=FieldSizeHint.SMALL, order=2),
            }
        )
        assert style.field_styles["name"].size == FieldSizeHint.FULL
        assert style.field_styles["age"].order == 2

    def test_show_section_numbers_default(self):
        """StyleSchema section numbers default to False."""
        style = StyleSchema()
        assert style.show_section_numbers is False

    def test_theme(self):
        """StyleSchema accepts a theme identifier."""
        style = StyleSchema(theme="dark")
        assert style.theme == "dark"

    def test_meta(self):
        """StyleSchema accepts meta dict."""
        style = StyleSchema(meta={"brand": "acme"})
        assert style.meta["brand"] == "acme"

    def test_all_layout_types(self):
        """All LayoutType values can be used in StyleSchema."""
        for lt in LayoutType:
            style = StyleSchema(layout=lt)
            assert style.layout == lt


class TestFieldStyleHint:
    """Tests for FieldStyleHint model."""

    def test_all_none_defaults(self):
        """FieldStyleHint has all-None defaults."""
        hint = FieldStyleHint()
        assert hint.size is None
        assert hint.order is None
        assert hint.css_class is None
        assert hint.variant is None

    def test_all_size_hints(self):
        """All FieldSizeHint values can be used."""
        for hint_val in FieldSizeHint:
            hint = FieldStyleHint(size=hint_val)
            assert hint.size == hint_val

    def test_css_class(self):
        """FieldStyleHint accepts a CSS class string."""
        hint = FieldStyleHint(css_class="col-span-2 font-bold")
        assert hint.css_class == "col-span-2 font-bold"
