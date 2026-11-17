"""FEAT-710 TASK-4544 — generic current_tenant ContextVar."""

from parrot.observability.context import current_tenant
from parrot.skills.tenancy import bind_skill_tenant, current_skill_tenant, reset_skill_tenant


def test_default_is_none() -> None:
    """The generic tenant ContextVar defaults to None."""
    assert current_tenant.get() is None


def test_skill_bind_visible_as_current_tenant() -> None:
    """A skills tenancy bind updates the shared tenant ContextVar."""
    tok = bind_skill_tenant("acme")
    try:
        assert current_tenant.get() == "acme"
        assert current_skill_tenant() == "acme"
    finally:
        reset_skill_tenant(tok)
    assert current_tenant.get() is None


def test_generic_bind_visible_to_skills() -> None:
    """A generic tenant bind is visible through the skills helper."""
    tok = current_tenant.set("acme")
    try:
        assert current_skill_tenant() == "acme"
    finally:
        current_tenant.reset(tok)
    assert current_skill_tenant() is None
