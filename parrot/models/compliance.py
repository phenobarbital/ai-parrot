from typing import List
from enum import Enum
import re
from pydantic import BaseModel, Field


class ComplianceStatus(str, Enum):
    """Possible compliance statuses for shelf checks"""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    MISSING = "missing"
    MISPLACED = "misplaced"

# Enhanced compliance result models (add these to your compliance models)
class TextComplianceResult(BaseModel):
    """Result of text compliance checking"""
    required_text: str
    found: bool
    matched_features: List[str] = Field(default_factory=list)
    confidence: float
    match_type: str


class ComplianceResult(BaseModel):
    """Final compliance check result"""
    shelf_level: str = Field(description="Shelf level being checked")
    expected_products: List[str] = Field(description="Products expected on this shelf")
    found_products: List[str] = Field(description="Products actually found")
    missing_products: List[str] = Field(description="Expected but not found")
    unexpected_products: List[str] = Field(description="Found but not expected")
    compliance_status: ComplianceStatus = Field(
        description="Overall compliance for this shelf"
    )
    compliance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Compliance score"
    )
    text_compliance_results: List[TextComplianceResult] = Field(default_factory=list)
    text_compliance_score: float = Field(default=1.0)
    overall_text_compliant: bool = Field(default=True)


class TextMatcher:
    """Utility class for text matching operations"""

    @staticmethod
    def normalize_text(text: str, case_sensitive: bool = False) -> str:
        """Normalize text for comparison"""
        if not text:
            return ""

        normalized = text.strip()
        if not case_sensitive:
            normalized = normalized.lower()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized

    @staticmethod
    def extract_text_from_features(visual_features: List[str]) -> List[str]:
        """Extract text-like features from visual features list"""
        text_features = []
        text_patterns = [
            r'(.+?)\s+text',
            r'(.+?)\s+logo',
            r'(.+?)\s+branding',
            r'(.+?)\s+message',
            r'text:\s*(.+)',
            r'says\s+(.+)',
            r'reads\s+(.+)',
        ]

        for feature in visual_features:
            if not isinstance(feature, str):
                continue

            feature_lower = feature.lower()

            # Direct text extraction patterns
            for pattern in text_patterns:
                matches = re.findall(pattern, feature_lower)
                text_features.extend(matches)

            # Look for quoted text
            quoted_matches = re.findall(r'["\']([^"\']+)["\']', feature)
            text_features.extend(quoted_matches)

            # Look for specific keywords that indicate text content
            if any(keyword in feature_lower for keyword in ['text', 'logo', 'says', 'reads', 'message', 'branding']):
                # Clean up the feature text
                cleaned = re.sub(r'\b(text|logo|says|reads|message|branding)\b', '', feature_lower).strip()
                if cleaned:
                    text_features.append(cleaned)

        return [TextMatcher.normalize_text(text) for text in text_features if text.strip()]

    @staticmethod
    def check_text_match(
        required_text: str,
        visual_features: List[str],
        match_type: str = "contains",
        case_sensitive: bool = False,
        confidence_threshold: float = 0.8
    ) -> TextComplianceResult:
        """Check if required text matches any visual features"""

        required_normalized = TextMatcher.normalize_text(required_text, case_sensitive)
        extracted_texts = TextMatcher.extract_text_from_features(visual_features)

        matched_features = []
        best_confidence = 0.0
        found = False

        for text in extracted_texts:
            text_normalized = TextMatcher.normalize_text(text, case_sensitive)
            confidence = 0.0

            if match_type == "exact":
                if text_normalized == required_normalized:
                    confidence = 1.0
                    found = True
                    matched_features.append(text)

            elif match_type == "contains":
                if required_normalized in text_normalized or text_normalized in required_normalized:
                    confidence = 0.9
                    found = True
                    matched_features.append(text)

            elif match_type == "regex":
                try:
                    pattern = re.compile(required_text, re.IGNORECASE if not case_sensitive else 0)
                    if pattern.search(text):
                        confidence = 0.95
                        found = True
                        matched_features.append(text)
                except re.error:
                    continue

            elif match_type == "fuzzy":
                confidence = TextMatcher._calculate_fuzzy_similarity(required_normalized, text_normalized)
                if confidence >= confidence_threshold:
                    found = True
                    matched_features.append(text)

            best_confidence = max(best_confidence, confidence)

        return TextComplianceResult(
            required_text=required_text,
            found=found,
            matched_features=matched_features,
            confidence=best_confidence,
            match_type=match_type
        )

    @staticmethod
    def _calculate_fuzzy_similarity(text1: str, text2: str) -> float:
        """Calculate fuzzy similarity between two texts"""
        if not text1 or not text2:
            return 0.0

        if text1 == text2:
            return 1.0

        # Simple Levenshtein-like ratio
        longer = text1 if len(text1) > len(text2) else text2
        shorter = text2 if len(text1) > len(text2) else text1

        if len(longer) == 0:
            return 1.0

        # Count matching characters (simple approach)
        matches = sum(1 for a, b in zip(shorter, longer) if a == b)
        similarity = matches / len(longer)

        # Bonus for substring matches
        if shorter in longer:
            similarity = max(similarity, 0.8)

        return similarity
