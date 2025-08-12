from typing import List
from enum import Enum
from pydantic import BaseModel, Field


class ComplianceStatus(str, Enum):
    """Possible compliance statuses for shelf checks"""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    MISSING = "missing"
    MISPLACED = "misplaced"


class ComplianceResult(BaseModel):
    """Final compliance check result"""
    shelf_level: str = Field(description="Shelf level being checked")
    expected_products: List[str] = Field(description="Products expected on this shelf")
    found_products: List[str] = Field(description="Products actually found")
    missing_products: List[str] = Field(description="Expected but not found")
    unexpected_products: List[str] = Field(description="Found but not expected")
    compliance_status: ComplianceStatus = Field(description="Overall compliance for this shelf")
    compliance_score: float = Field(ge=0.0, le=1.0, description="Compliance score")
