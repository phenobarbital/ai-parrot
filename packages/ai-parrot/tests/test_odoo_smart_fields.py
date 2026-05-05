"""Unit tests for smart field selection heuristic.

Tests are deterministic and network-free — they only exercise the pure
``select_smart_fields`` function and the ``_smart_field_score`` helper.
"""
from __future__ import annotations

import pytest

from parrot_tools.odoo.smart_fields import (
    _smart_field_score,
    select_smart_fields,
    SKIP_FIELD_TYPES,
    TECHNICAL_FIELD_NAMES,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def rich_fields_metadata() -> dict:
    """A representative fields_get response with diverse field types."""
    return {
        "id": {"type": "integer", "string": "ID", "readonly": True},
        "display_name": {"type": "char", "string": "Display Name"},
        "name": {"type": "char", "string": "Name", "required": True},
        "state": {"type": "selection", "string": "Status"},
        "amount_total": {"type": "float", "string": "Total"},
        "image_1920": {"type": "binary", "string": "Image"},
        "__last_update": {"type": "datetime", "string": "Last Modified"},
        "partner_id": {"type": "many2one", "string": "Partner", "relation": "res.partner"},
        "line_ids": {"type": "one2many", "string": "Lines", "relation": "account.move.line"},
        "tag_ids": {"type": "many2many", "string": "Tags", "relation": "account.tag"},
        "notes": {"type": "html", "string": "Notes"},
        "create_uid": {"type": "many2one", "string": "Created by"},
        "write_date": {"type": "datetime", "string": "Last Updated"},
    }


# ── _smart_field_score ────────────────────────────────────────────────────────


def test_score_binary_is_skip_sentinel():
    """Binary fields must return -inf so they are always excluded."""
    score = _smart_field_score("image_1920", {"type": "binary"})
    assert score == float("-inf")


def test_score_html_is_skip_sentinel():
    """HTML fields must return -inf so they are always excluded."""
    score = _smart_field_score("description", {"type": "html"})
    assert score == float("-inf")


def test_score_name_field_high():
    """'name' is a high-value field and should score well above a plain char."""
    name_score = _smart_field_score("name", {"type": "char", "string": "Name"})
    other_score = _smart_field_score("ref_code", {"type": "char", "string": "Ref"})
    assert name_score > other_score


def test_score_technical_field_penalised():
    """Technical fields (create_uid, write_date, etc.) score lower than regular ones."""
    regular = _smart_field_score("partner_id", {"type": "many2one", "string": "Partner"})
    technical = _smart_field_score("create_uid", {"type": "many2one", "string": "Created by"})
    assert technical < regular


def test_score_message_field_penalised():
    """message_* fields are Odoo chatter internals and should score very low."""
    score = _smart_field_score("message_ids", {"type": "one2many", "string": "Messages"})
    regular = _smart_field_score("line_ids", {"type": "one2many", "string": "Lines"})
    assert score < regular


def test_score_required_field_boosted():
    """Required fields get a small boost over optional ones of the same type."""
    req = _smart_field_score("name", {"type": "char", "required": True})
    opt = _smart_field_score("description", {"type": "char", "required": False})
    assert req > opt


# ── select_smart_fields ───────────────────────────────────────────────────────


def test_always_includes_id_and_display_name(rich_fields_metadata):
    """id and display_name must always appear in the result."""
    result = select_smart_fields(rich_fields_metadata)
    assert "id" in result
    assert "display_name" in result


def test_id_and_display_name_come_first(rich_fields_metadata):
    """id and display_name should be at the beginning of the list."""
    result = select_smart_fields(rich_fields_metadata)
    assert result[0] == "id"
    assert result[1] == "display_name"


def test_max_cap(rich_fields_metadata):
    """Output must never exceed max_fields + len(pinned) fields."""
    # 50 generic char fields
    big_meta = {f"field_{i}": {"type": "char", "string": f"F{i}"} for i in range(50)}
    big_meta["id"] = {"type": "integer", "string": "ID"}
    big_meta["display_name"] = {"type": "char", "string": "Display Name"}
    result = select_smart_fields(big_meta, max_fields=15)
    # 15 scored + 2 pinned = 17
    assert len(result) <= 17


def test_binary_fields_excluded(rich_fields_metadata):
    """Binary fields must never appear in the result."""
    result = select_smart_fields(rich_fields_metadata)
    assert "image_1920" not in result


def test_html_fields_excluded(rich_fields_metadata):
    """HTML fields must never appear in the result."""
    result = select_smart_fields(rich_fields_metadata)
    assert "notes" not in result


def test_high_value_fields_ranked_above_technical(rich_fields_metadata):
    """name and state should rank above create_uid and write_date."""
    result = select_smart_fields(rich_fields_metadata, max_fields=4)
    # name and/or state should be in the top results, technical fields should not
    assert "name" in result or "state" in result
    # When we only take top 4, technical fields should be excluded or ranked low
    pinned = {"id", "display_name"}
    non_pinned = [f for f in result if f not in pinned]
    if "create_uid" in non_pinned or "write_date" in non_pinned:
        # If included, they should appear after high-value fields
        high_idx = min(
            result.index(f) for f in ("name", "state", "partner_id", "amount_total")
            if f in result
        )
        for tech in ("create_uid", "write_date"):
            if tech in result:
                assert result.index(tech) > high_idx, \
                    f"{tech} appears before high-value fields"


def test_empty_metadata_returns_pinned_only():
    """Empty input returns exactly ['id', 'display_name']."""
    result = select_smart_fields({})
    assert result == ["id", "display_name"]


def test_always_include_parameter():
    """always_include fields appear regardless of score and don't count against cap."""
    meta = {
        "name": {"type": "char", "string": "Name"},
        "custom_field": {"type": "char", "string": "Custom"},
    }
    result = select_smart_fields(meta, always_include=["custom_field"])
    assert "custom_field" in result
    assert "id" in result
    assert "display_name" in result


def test_max_fields_zero():
    """max_fields=0 still returns the pinned fields."""
    meta = {"name": {"type": "char", "string": "Name"}}
    result = select_smart_fields(meta, max_fields=0)
    assert "id" in result
    assert "display_name" in result


def test_all_fields_binary_returns_pinned():
    """When all fields are binary/html, result is just the pinned fields."""
    meta = {
        "image": {"type": "binary", "string": "Image"},
        "desc": {"type": "html", "string": "Desc"},
    }
    result = select_smart_fields(meta)
    assert result == ["id", "display_name"]


def test_skip_field_types_constant():
    """Verify SKIP_FIELD_TYPES contains binary and html."""
    assert "binary" in SKIP_FIELD_TYPES
    assert "html" in SKIP_FIELD_TYPES


def test_technical_field_names_constant():
    """Verify core technical field names are in TECHNICAL_FIELD_NAMES."""
    assert "create_uid" in TECHNICAL_FIELD_NAMES
    assert "write_uid" in TECHNICAL_FIELD_NAMES
    assert "__last_update" in TECHNICAL_FIELD_NAMES
