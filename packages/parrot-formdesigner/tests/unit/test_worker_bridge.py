"""Unit tests for worker_bridge.py — FEAT-459 / TASK-3173."""

from __future__ import annotations

from parrot_formdesigner.renderers.worker_bridge import (
    ALLOWED_PATCH_OPERATIONS,
    render_worker_boot_block,
    validate_patch,
)


def test_worker_patch_allowlist_has_exactly_six_operations() -> None:
    assert ALLOWED_PATCH_OPERATIONS == {
        "set_visibility", "set_required", "set_enabled", "set_value", "set_hint", "narrow_options",
    }


def test_validate_patch_accepts_allowlisted_op() -> None:
    assert validate_patch({"op": "set_visibility", "field_uid": "f1", "value": False}) is True


def test_validate_patch_rejects_unknown_op() -> None:
    assert validate_patch({"op": "delete_field", "field_uid": "f1"}) is False


def test_validate_patch_rejects_missing_field_uid() -> None:
    assert validate_patch({"op": "set_visibility", "value": False}) is False


def test_patch_rejects_structure_change() -> None:
    """Operations that would add/remove a field are simply not in the allowlist."""
    for forbidden_op in ("add_field", "remove_field", "set_field_uid", "set_form_action"):
        assert validate_patch({"op": forbidden_op, "field_uid": "f1"}) is False


def test_boot_block_contains_all_six_op_names() -> None:
    block = render_worker_boot_block()
    for op in ALLOWED_PATCH_OPERATIONS:
        assert op in block


def test_boot_block_has_no_direct_innerHTML_or_cookie_access() -> None:
    """Structural check: no raw markup injection or cookie/storage path exists."""
    block = render_worker_boot_block()
    assert "innerHTML" not in block
    assert "document.cookie" not in block
    assert "localStorage" not in block
    assert "sessionStorage" not in block


def test_patch_narrow_options_subset_only() -> None:
    """Structural check: the narrow_options case should remove options, not add them.

    This test verifies that the generated JS does not contain code paths that
    append or add new <option> elements, ensuring that narrow_options can only
    reduce the set of available options, never expand it (bounded by the spec
    constraint: "subset of ALREADY-declared options, never new ones").
    """
    block = render_worker_boot_block()
    # The JS code should not call appendChild or insertAdjacentHTML/insertAdjacentElement
    # to add options — it should only call remove() to delete unwanted ones.
    assert "appendChild" not in block
    assert "insertAdjacentHTML" not in block
    assert "insertAdjacentElement" not in block
    # The narrow_options handler should remove options, which means iterating
    # backwards through options and removing those not in the subset.
    assert "el.remove" in block
    assert "narrow_options" in block
