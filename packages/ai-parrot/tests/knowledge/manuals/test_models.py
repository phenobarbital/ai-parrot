"""Core manual-card model invariants."""

from datetime import date
import re

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.models import (
    ManualCard,
    ManualVersion,
    MediaRef,
    Procedure,
    Step,
    StepIdentity,
    content_hash,
    manual_snapshot_payload,
    mint_step_id,
)


def _text(quote: str = "Torque the bolt to 12 Nm.") -> Extracted[str]:
    return Extracted[str](value=quote, evidence=Evidence(node_id="0003", quote=quote, page=3), confidence=0.9)


def test_step_requires_substantiated_evidence() -> None:
    """Step text without a quote is rejected."""
    with pytest.raises(ValueError):
        Step(
            identity=StepIdentity(step_id="m:p:abc", content_hash=content_hash("x")),
            order=1,
            text=Extracted[str](value="x", evidence=None),
        )


def test_step_identity_order_independent() -> None:
    """Display renumbering does not change the immutable identity."""
    identity = StepIdentity(step_id=mint_step_id("manual", "repair"), content_hash=content_hash("tighten bolt"))
    assert (
        Step(identity=identity, order=1, text=_text()).identity
        == Step(identity=identity, order=8, text=_text()).identity
    )


def test_content_hash_numeric_fields() -> None:
    """Numeric extraction fields participate in equality hashes."""
    assert content_hash("Torque", torque="12 Nm") != content_hash("Torque", torque="14 Nm")


def test_mint_step_id_is_unique_and_key_safe() -> None:
    """Minted ids are unique and normalize unsafe key characters."""
    first = mint_step_id("manual / 1", "repair step")
    second = mint_step_id("manual / 1", "repair step")
    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9_\-:.@()+,=;$!*'%]+", first)


def test_media_ref_never_stores_url() -> None:
    """Storage keys are opaque storage identifiers, never persisted URLs."""
    with pytest.raises(ValueError):
        MediaRef(media_id="m1", kind="figure", storage_key="https://bucket/x.png")


def test_manual_card_rejects_duplicate_procedure_slugs() -> None:
    """One manual cannot contain duplicate procedure slugs."""
    procedure = Procedure(procedure_id="p1", slug="repair", kind="maintenance", title=_text())
    with pytest.raises(ValueError):
        ManualCard(
            manual_id="manual-1",
            revision="A",
            procedures=[procedure, procedure.model_copy(update={"procedure_id": "p2"})],
        )


def test_manual_version_interval_and_snapshot_rules() -> None:
    """Version intervals are exclusive at the end and snapshots cannot recurse."""
    version = ManualVersion(n=1, revision="A", valid_from=date(2026, 1, 1), valid_to=date(2026, 2, 1))
    assert version.in_force(date(2026, 1, 31))
    assert not version.in_force(date(2026, 2, 1))
    with pytest.raises(ValueError):
        ManualVersion(n=1, revision="A", card_snapshot={"versions": [{"n": 1}]})
    assert "versions" not in manual_snapshot_payload(ManualCard(manual_id="manual-1", revision="A"))


def test_lazy_facade_resolves_models_and_rejects_unknown() -> None:
    """Package import is lazy and unknown names are ordinary attributes errors."""
    import parrot.knowledge.manuals as manuals

    assert manuals.ManualCard.__name__ == "ManualCard"
    with pytest.raises(AttributeError):
        _ = manuals.DoesNotExist
