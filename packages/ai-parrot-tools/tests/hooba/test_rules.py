"""FEAT-602 TASK-3740 — rule engine."""

import datetime as dt
from decimal import Decimal

import pytest
import yaml

from parrot_tools.hooba.models import BankExpenseRow
from parrot_tools.hooba.rules import RuleEngine


def _row(concept: str, amount: str) -> BankExpenseRow:
    return BankExpenseRow(
        row_index=0,
        booking_date=dt.date(2026, 9, 3),
        concept=concept,
        amount=Decimal(amount),
        row_id="d:0",
    )


def test_rule_table_loads_and_priorities(tmp_path):
    """The bundled table validates, and duplicate ids fail closed."""
    engine = RuleEngine.load()

    assert len(engine.table.rules) == 15
    assert all(rule.review_required for rule in engine.table.rules)
    assert engine.table.fallback_rule_id == "unclassified"

    duplicate_table = engine.table.model_dump(mode="json")
    duplicate_table["rules"].append(duplicate_table["rules"][0])
    path = tmp_path / "duplicate.yaml"
    path.write_text(yaml.safe_dump(duplicate_table), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate rule_id"):
        RuleEngine.load(path)


def test_rule_engine_matches_and_skips():
    """Starter rows classify deterministically and skip non-expense movements."""
    engine = RuleEngine.load()

    reta = engine.assess(_row("CUOTA RETA", "-320"), period="2026-09")
    fuel = engine.assess(_row("REPSOL", "-55"), period="2026-09")
    unknown = engine.assess(_row("COMERCIO DESCONOCIDO", "-10"), period="2026-09")

    assert reta is not None
    assert reta.deductible_pct == Decimal("100")
    assert reta.vat_deductible_pct == Decimal("0")
    assert reta.hooba.tax_code == "EXENTO"
    assert fuel is not None
    assert fuel.deductible_pct == Decimal("0")
    assert fuel.vat_deductible_pct == Decimal("50")
    assert engine.assess(_row("TRASPASO A CUENTA PROPIA", "-50"), period="2026-09") is None
    assert unknown is not None
    assert unknown.rule_id == "unclassified"
    assert unknown.review_required is True


def test_same_priority_ambiguity_falls_back(tmp_path):
    """Two matching rules at the same priority are rejected as ambiguous."""
    table = RuleEngine.load().table.model_dump(mode="json")
    table["rules"] = [rule for rule in table["rules"] if rule["rule_id"] in {"unclassified", "reta"}]
    table["rules"].append({**table["rules"][0], "rule_id": "other_reta"})
    path = tmp_path / "ambiguous.yaml"
    path.write_text(yaml.safe_dump(table), encoding="utf-8")

    assert RuleEngine.load(path).match(_row("CUOTA RETA", "-320")).rule_id == "unclassified"


def test_simplified_threshold():
    """The bundled YAML threshold drives the simplified-invoice flag."""
    engine = RuleEngine.load()

    below = engine.assess(_row("CUOTA RETA", "-399.99"), period="2026-09")
    above = engine.assess(_row("CUOTA RETA", "-400.01"), period="2026-09")

    assert below is not None
    assert above is not None
    assert below.hooba.simplified is True
    assert above.hooba.simplified is False


def test_verdict_carries_evidence_and_legal_basis():
    """A verdict retains raw row evidence and the rule's legal basis."""
    row = BankExpenseRow(
        row_index=0,
        booking_date=dt.date(2026, 9, 3),
        concept="REPSOL",
        movement="PAGO TARJETA",
        observations="Estación de servicio",
        amount=Decimal("-55"),
        row_id="d:0",
    )

    verdict = RuleEngine.load().assess(row, period="2026-09")

    assert verdict is not None
    assert verdict.legal_basis == "LIVA 37/1992 art. 95.Tres.2ª"
    assert verdict.review_required is True
    assert verdict.evidence == {
        "concept": "REPSOL",
        "movement": "PAGO TARJETA",
        "observations": "Estación de servicio",
        "amount": Decimal("-55"),
        "matched_pattern": "REPSOL|CEPSA|BP|GALP|SHELL",
    }
