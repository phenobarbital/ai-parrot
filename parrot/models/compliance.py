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
    """Utility class for text matching operations - FIXED VERSION"""

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
        """IMPROVED: Extract text-like features from visual features list"""
        text_features = []

        for feature in visual_features:
            if not isinstance(feature, str):
                continue

            feature_lower = feature.lower()

            # FIX 1: Handle "text [content]" pattern specifically
            text_match = re.search(r'text\s+(.+)', feature_lower)
            if text_match:
                extracted_text = text_match.group(1).strip()
                text_features.append(extracted_text)
                continue

            # FIX 2: Direct text patterns (improved)
            text_patterns = [
                r'(.+?)\s+text\b',          # "something text"
                r'(.+?)\s+logo\b',          # "something logo"
                r'(.+?)\s+branding\b',      # "something branding"
                r'(.+?)\s+message\b',       # "something message"
                r'says\s+(.+)',             # "says something"
                r'reads\s+(.+)',            # "reads something"
                r'displays?\s+(.+)',        # "display(s) something"
                r'shows?\s+(.+)',           # "show(s) something"
            ]

            for pattern in text_patterns:
                matches = re.findall(pattern, feature_lower)
                for match in matches:
                    cleaned = match.strip()
                    if cleaned and len(cleaned) > 2:  # Avoid single characters
                        text_features.append(cleaned)

            # FIX 3: Look for quoted text
            quoted_matches = re.findall(r'["\']([^"\']+)["\']', feature)
            text_features.extend(quoted_matches)

            # FIX 4: Extract brand names and specific text patterns
            if any(keyword in feature_lower for keyword in ['epson', 'logo', 'branding']):
                # Extract the brand name
                if 'epson' in feature_lower:
                    text_features.append('epson')

            # FIX 5: Handle comma-separated text content
            if ',' in feature and any(keyword in feature_lower for keyword in ['text', 'says', 'reads']):
                # Extract text after keywords and split by comma
                for keyword in ['text', 'says', 'reads']:
                    if keyword in feature_lower:
                        after_keyword = feature_lower.split(keyword, 1)[-1].strip()
                        # Split by comma and clean up
                        parts = [part.strip() for part in after_keyword.split(',')]
                        text_features.extend([part for part in parts if part and len(part) > 2])

        # FIX 6: Clean up and normalize extracted text
        cleaned_texts = []
        for text in text_features:
            normalized = TextMatcher.normalize_text(text)
            if normalized and len(normalized) > 2:
                cleaned_texts.append(normalized)

        # Remove duplicates while preserving order
        seen = set()
        unique_texts = []
        for text in cleaned_texts:
            if text not in seen:
                seen.add(text)
                unique_texts.append(text)

        return unique_texts

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

        # DEBUG: Print what was extracted
        print(f"  DEBUG: Looking for '{required_text}'")
        print(f"  DEBUG: Visual features: {visual_features}")
        print(f"  DEBUG: Extracted texts: {extracted_texts}")

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
                # FIX 7: Improved contains matching
                if required_normalized in text_normalized:
                    confidence = 0.9
                    found = True
                    matched_features.append(text)
                elif text_normalized in required_normalized:
                    confidence = 0.8
                    found = True
                    matched_features.append(text)
                # FIX 8: Handle partial word matches for phrases
                elif len(required_normalized.split()) > 1:
                    required_words = required_normalized.split()
                    text_words = text_normalized.split()
                    matches = sum(1 for word in required_words if word in text_words)
                    if matches >= len(required_words) * 0.7:  # 70% of words match
                        confidence = 0.7
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

        print(f"  DEBUG: Found: {found}, Confidence: {best_confidence}, Matched: {matched_features}")

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
