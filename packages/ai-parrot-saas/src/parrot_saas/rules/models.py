"""Persisted eligibility rules and the payloads that create or amend them."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .builder import DEFAULT_RULESET

#: Bounds on a rule name. Long enough to be descriptive, short enough to read
#: in a listing.
NAME_MAX_LENGTH = 80

#: Priority bounds. Signed so a tenant can push an exclusion below the default
#: rules without renumbering everything above it.
PRIORITY_MIN = -1000
PRIORITY_MAX = 1000


class Rule(BaseModel):
    """A rule as stored in ``saas.rules``.

    Attributes:
        rule_id: Surrogate key. Also the tie-break when two rules share a
            priority — see the index comment in ``db/schema.py``.
        tenant_id: Owning tenant.
        ruleset: Which ruleset this belongs to.
        name: Unique per tenant and ruleset; what the decision reports back.
        priority: Higher evaluates first under FIRST_MATCH.
        enabled: Disabled rules stay for the record but never evaluate.
        conditions: navrules condition spec.
        result: Payload returned when the rule wins — ``offer_code`` and
            ``reason`` for the coupon flow.
        description: Why this rule exists, in the tenant's own words.
        created_at: Row creation time.
        updated_at: Last modification time.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    rule_id: str = ""
    tenant_id: str = ""
    ruleset: str = DEFAULT_RULESET
    name: str = ""
    priority: int = 0
    enabled: bool = True
    conditions: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_spec(self) -> dict[str, Any]:
        """Render the spec shape ``RuleLoader`` accepts.

        ``rule_type`` is emitted as a constant rather than read from the row —
        see the table comment for why it is not a column.
        """
        from .builder import RULE_TYPE

        return {
            "rule_type": RULE_TYPE,
            "name": self.name,
            "priority": self.priority,
            "conditions": self.conditions,
            "result": self.result,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Rule":
        """Build a rule from a database row.

        Args:
            row: A record from ``saas.rules``. ``conditions`` and ``result``
                may arrive as JSON strings or mappings depending on driver
                codecs.

        Returns:
            The parsed rule.
        """
        import json

        data = dict(row)
        if data.get("rule_id") is not None:
            data["rule_id"] = str(data["rule_id"])
        for key in ("conditions", "result"):
            value = data.get(key)
            if isinstance(value, str):
                data[key] = json.loads(value or "{}")
            elif value is None:
                data[key] = {}
        return cls(**data)


class RuleCreate(BaseModel):
    """Payload accepted to create a rule.

    ``extra="forbid"`` because silence is worse than a 400 here: a caller who
    posts ``rule_type: "ComputedRule"`` believes they are creating one, and
    ignoring the field would hand them a ConditionRule without a word.
    """

    model_config = ConfigDict(validate_default=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    conditions: dict[str, Any] = Field(...)
    result: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=PRIORITY_MIN, le=PRIORITY_MAX)
    enabled: bool = True
    description: str = ""
    ruleset: str = DEFAULT_RULESET

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        """Names are identifiers in a listing, not free prose."""
        value = value.strip()
        if not value:
            raise ValueError("a rule needs a name")
        return value


class RuleUpdate(BaseModel):
    """Partial amendment. Absent fields are left alone.

    ``name`` and ``ruleset`` are deliberately absent: renaming a rule through
    the same endpoint that edits it makes "did this rule change or is it a
    different rule?" unanswerable from the audit trail. Delete and recreate.
    """

    model_config = ConfigDict(validate_default=True, extra="forbid")

    conditions: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    priority: Optional[int] = Field(default=None, ge=PRIORITY_MIN, le=PRIORITY_MAX)
    enabled: Optional[bool] = None
    description: Optional[str] = None

    def changes(self) -> dict[str, Any]:
        """Return only the fields the caller actually supplied."""
        return self.model_dump(exclude_none=True)


__all__ = (
    "NAME_MAX_LENGTH",
    "PRIORITY_MAX",
    "PRIORITY_MIN",
    "Rule",
    "RuleCreate",
    "RuleUpdate",
)
