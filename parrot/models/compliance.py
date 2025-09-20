from typing import List, Optional, Tuple, Iterable, Set
from enum import Enum
import re
import unicodedata
from difflib import SequenceMatcher
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

class BrandComplianceResult(BaseModel):
    """Result of brand logo compliance checking"""
    expected_brand: str
    found_brand: Optional[str] = None
    found: bool = False
    confidence: float = 0.0

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
    brand_compliance_result: Optional[BrandComplianceResult] = Field(
        None, description="Result of the brand logo compliance check."
    )
    text_compliance_score: float = Field(default=1.0)
    overall_text_compliant: bool = Field(default=True)


class TextMatcher:
    """
    N-gram + fuzzy text matcher for planogram text compliance.

    Public API:
        TextMatcher.check_text_match(
            required_text: str,
            visual_features: List[str],
            match_type: str = "contains",      # "contains" | "regex" | "ngram" | "auto"
            case_sensitive: bool = False,
            confidence_threshold: float = 0.6, # used for "ngram"/"auto"
            ngram_range: Tuple[int, int] = (1, 3),
            min_token_len: int = 2,
        ) -> TextComplianceResult
    """

    @staticmethod
    def _strip_ocr_prefix(s: str) -> str:
        return s[4:].strip() if isinstance(s, str) and s.lower().startswith("ocr:") else s

    @staticmethod
    def _normalize(s: str, *, keep_case: bool = False) -> str:
        if s is None:
            return ""
        s = TextMatcher._strip_ocr_prefix(s)
        # de-accent
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        if not keep_case:
            s = s.lower()
        # keep letters/digits/space
        s = re.sub(r"[^0-9a-zA-Z]+", " ", s)
        # collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _tokenize(s: str, min_len: int = 2) -> List[str]:
        return [t for t in s.split() if len(t) >= min_len]

    @staticmethod
    def _ngrams(tokens: List[str], n_from: int, n_to: int) -> Set[str]:
        grams: Set[str] = set()
        for n in range(max(1, n_from), max(n_from, n_to) + 1):
            for i in range(0, max(0, len(tokens) - n + 1)):
                grams.add(" ".join(tokens[i:i+n]))
        return grams

    @staticmethod
    def _jaccard(a: Set[str], b: Set[str]) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        if inter == 0:
            return 0.0
        union = len(a | b)
        return inter / max(1, union)

    @staticmethod
    def _best_ngram_hits(req_grams: Set[str], feat_grams: Set[str], top_k: int = 5) -> List[str]:
        hits = list(req_grams & feat_grams)
        # sort by length desc to surface most informative matches
        hits.sort(key=lambda x: (-len(x), x))
        return hits[:top_k]

    @classmethod
    def check_text_match(
        cls,
        required_text: str,
        visual_features: List[str],
        match_type: str = "contains",      # "contains" | "regex" | "ngram" | "auto"
        case_sensitive: bool = False,
        confidence_threshold: float = 0.6, # only used by ngram/auto
        ngram_range: Tuple[int, int] = (1, 3),
        min_token_len: int = 2,
    ):
        # Normalize the required text for all algorithms except strict case-sensitive contains/regex
        req_norm = cls._normalize(required_text, keep_case=False)
        req_norm_cs = cls._normalize(required_text, keep_case=True)
        req_tokens = cls._tokenize(req_norm, min_len=min_token_len)
        req_grams = cls._ngrams(req_tokens, ngram_range[0], ngram_range[1])

        # Normalize all feature strings; keep both raw and normalized for substring/case options
        norm_features: List[str] = []
        raw_features: List[str] = []
        for f in (visual_features or []):
            if not isinstance(f, str):
                continue
            raw_features.append(cls._strip_ocr_prefix(f))
            norm_features.append(cls._normalize(f, keep_case=False))

        # Helper to build the result
        def _result(found: bool, confidence: float, match_kind: str, matched_feats: List[str]):
            # TextComplianceResult(required_text, found, matched_features, confidence, match_type)
            return TextComplianceResult(
                required_text=required_text,
                found=bool(found),
                matched_features=matched_feats,
                confidence=float(max(0.0, min(1.0, confidence))),
                match_type=match_kind
            )

        # ----- 1) Regex (if explicitly requested)
        if match_type == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(required_text, flags)
            except re.error:
                # fall back to auto if invalid regex
                match_type = "auto"
            else:
                for raw in raw_features:
                    if pattern.search(raw):
                        return _result(True, 1.0, "regex", [raw])
                return _result(False, 0.0, "regex", [])

        # ----- 2) Contains (fast path)
        if match_type == "contains":
            needle = req_norm_cs if case_sensitive else req_norm
            for raw, norm in zip(raw_features, norm_features):
                haystack = raw if case_sensitive else norm
                if needle and needle in haystack:
                    return _result(True, 1.0, "contains", [needle])
            return _result(False, 0.0, "contains", [])

        # ----- 3) N-gram / Auto (n-gram + fuzzy + contains fallback)
        # quick exact-substring fallback (case-insensitive)
        for raw, norm in zip(raw_features, norm_features):
            if req_norm and req_norm in norm:
                return _result(True, 1.0, "contains", [required_text])

        best_conf = 0.0
        best_hits: List[str] = []
        best_kind = "ngram"

        for raw, norm in zip(raw_features, norm_features):
            # n-gram containment
            feat_tokens = cls._tokenize(norm, min_len=min_token_len)
            feat_grams = cls._ngrams(feat_tokens, ngram_range[0], ngram_range[1])
            jacc = cls._jaccard(req_grams, feat_grams)

            # fuzzy ratio (sequence similarity)
            fuzzy = SequenceMatcher(None, req_norm, norm).ratio()

            conf = max(jacc, fuzzy)
            if conf > best_conf:
                best_conf = conf
                # collect some concrete n-gram hits for debugging
                hits = cls._best_ngram_hits(req_grams, feat_grams, top_k=5)
                best_hits = hits if hits else ([required_text] if conf >= 1.0 else [])
                best_kind = "ngram" if jacc >= fuzzy else "fuzzy"

        found = best_conf >= confidence_threshold
        return _result(found, best_conf, best_kind, best_hits)
