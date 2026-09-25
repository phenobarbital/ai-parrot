"""Data-driven deductibility rules for Spanish autónomos (FEAT-602 M9). Pure after ``load``."""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import BaseModel

from ..models import BankExpenseRow, DeductibilityVerdict, HoobaMapping

logger = logging.getLogger(__name__)
BUNDLED = Path(__file__).with_name("autonomo_es_v1.yaml")


class RuleMatcher(BaseModel):
    """Conditions that identify a deductibility rule."""

    concept_regex: Optional[str] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    category: str


class AeatRule(BaseModel):
    """One versioned AEAT-inspired deductibility rule."""

    rule_id: str
    matcher: RuleMatcher
    priority: int = 100
    deductible_pct: Decimal
    vat_deductible_pct: Decimal
    annual_cap: Optional[Decimal] = None
    daily_cap: Optional[Decimal] = None
    requires_exclusive_use: bool = False
    invoice_required: bool = True
    review_required: bool = True
    skip: bool = False
    legal_basis: str
    hooba: HoobaMapping


class RuleTable(BaseModel):
    """A versioned collection of deductibility rules."""

    version: str
    simplified_invoice_limit_eur: Decimal
    rules: list[AeatRule]
    fallback_rule_id: str


class RuleEngine:
    """Classify bank rows into deductibility verdicts."""

    def __init__(self, table: RuleTable) -> None:
        self.table = table
        self._rules_by_id = {rule.rule_id: rule for rule in table.rules}
        if len(self._rules_by_id) != len(table.rules):
            raise ValueError("rule table contains duplicate rule_id values")
        try:
            self._fallback_rule = self._rules_by_id[table.fallback_rule_id]
        except KeyError as exc:
            raise ValueError(f"fallback rule {table.fallback_rule_id!r} does not exist") from exc
        self._compiled_patterns = {
            rule.rule_id: re.compile(rule.matcher.concept_regex, re.IGNORECASE)
            for rule in table.rules
            if rule.matcher.concept_regex is not None
        }

    @classmethod
    def load(cls, path: Optional[Union[str, Path]] = None) -> "RuleEngine":
        """Load and validate a rule table (bundled ``autonomo_es_v1.yaml`` by default)."""
        table_path = Path(path) if path is not None else BUNDLED
        with table_path.open(encoding="utf-8") as stream:
            raw_table = yaml.safe_load(stream)
        return cls(RuleTable.model_validate(raw_table))

    def _matches(self, rule: AeatRule, row: BankExpenseRow) -> bool:
        """Return whether a rule's pattern and amount bounds match a bank row."""
        pattern = self._compiled_patterns.get(rule.rule_id)
        text = " ".join(part for part in (row.concept, row.movement, row.observations) if part)
        if pattern is not None and pattern.search(text) is None:
            return False

        amount = abs(row.amount)
        if rule.matcher.amount_min is not None and amount < rule.matcher.amount_min:
            return False
        return rule.matcher.amount_max is None or amount <= rule.matcher.amount_max

    def match(self, row: BankExpenseRow) -> AeatRule:
        """Lowest-priority-number match; ties or no match → fallback (never guess, S12)."""
        matches = [rule for rule in self.table.rules if self._matches(rule, row)]
        if not matches:
            return self._fallback_rule

        priority = min(rule.priority for rule in matches)
        winners = [rule for rule in matches if rule.priority == priority]
        return winners[0] if len(winners) == 1 else self._fallback_rule

    def assess(self, row: BankExpenseRow, *, period: str) -> Optional[DeductibilityVerdict]:
        """Return a draft verdict, or None when the matched rule is ``skip``."""
        rule = self.match(row)
        if rule.skip:
            return None

        capped_amount: Optional[Decimal] = None
        caps = [cap for cap in (rule.daily_cap, rule.annual_cap) if cap is not None]
        if caps:
            capped_amount = min(abs(row.amount), *caps)

        matched_pattern = rule.matcher.concept_regex if rule.rule_id in self._compiled_patterns else None
        hooba = rule.hooba.model_copy(update={"simplified": abs(row.amount) <= self.table.simplified_invoice_limit_eur})
        return DeductibilityVerdict(
            draft_id=f"{row.row_id}:{rule.rule_id}",
            txn_id=row.row_id,
            rule_id=rule.rule_id,
            deductible_pct=rule.deductible_pct,
            vat_deductible_pct=rule.vat_deductible_pct,
            capped_amount=capped_amount,
            legal_basis=rule.legal_basis,
            invoice_required=rule.invoice_required,
            review_required=rule.review_required,
            evidence={
                "concept": row.concept,
                "movement": row.movement,
                "observations": row.observations,
                "amount": row.amount,
                "matched_pattern": matched_pattern,
            },
            hooba=hooba,
        )
