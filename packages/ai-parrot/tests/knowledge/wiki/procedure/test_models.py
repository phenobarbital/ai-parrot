"""Tests for the procedure graph models (FEAT-891)."""

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.procedure.models import EDGE_FIELDS, ProcedureManifest, ProcedureSpec, ScopeArg


def _spec(**overrides: object) -> ProcedureSpec:
    """Build a minimal procedure specification."""
    return ProcedureSpec(**{"id": "sdd:a", "title": "A", "kind": "command", **overrides})


def test_spec_edges() -> None:
    """Every edge field maps to its relation; applies_to targets get the type: prefix."""
    spec = _spec(**{field_name: ["Task" if field_name == "applies_to" else "sdd:b"] for field_name in EDGE_FIELDS})

    assert spec.edges() == [
        ("sdd:a", "sdd:b", "requires"),
        ("sdd:a", "sdd:b", "next"),
        ("sdd:a", "sdd:b", "alternative_to"),
        ("sdd:a", "sdd:b", "escalates_to"),
        ("sdd:a", "sdd:b", "on_failure"),
        ("sdd:a", "sdd:b", "learned_from"),
        ("sdd:a", "type:Task", "applies_to"),
    ]


def test_models_forbid_extra() -> None:
    """Unknown keys are rejected in ProcedureSpec and ProcedureManifest."""
    with pytest.raises(ValidationError):
        _spec(unexpected=True)
    with pytest.raises(ValidationError):
        ProcedureManifest(graph="sdd", unexpected=True)


def test_scope_arg_needs_exactly_one() -> None:
    """ScopeArg rejects neither and both of argv / flag."""
    assert ScopeArg(argv=0).argv == 0
    assert ScopeArg(flag="--base").flag == "--base"
    with pytest.raises(ValidationError):
        ScopeArg()
    with pytest.raises(ValidationError):
        ScopeArg(argv=0, flag="--base")


def test_lazy_exports_resolve_models() -> None:
    """The package resolves model names lazily and rejects unknown names."""
    from parrot.knowledge.wiki import procedure

    assert procedure.ProcedureSpec is ProcedureSpec
    with pytest.raises(AttributeError):
        procedure.nope
