---
id: F002
query_id: Q002
type: read
intent: Understand ScrapingPlan fields, fingerprint computation, and immutability constraints
executed_at: 2026-06-04T00:00:00Z
duration_ms: 52576
parent_id: null
depth: 0
---

# F002 — ScrapingPlan is a Pydantic model with URL-derived fingerprint

## Summary

`ScrapingPlan` (plan.py:59-110) is a Pydantic BaseModel with 16 fields. `model_post_init` auto-populates `domain`, `name`, and `fingerprint` from the URL. Fingerprint is a 16-char SHA-256 hex prefix of the normalized URL (query/fragment stripped). The model is effectively immutable after construction — no mutation methods exist. `browser_config` is an optional Dict[str, Any] passed through to driver setup.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py`
  lines: 59-110
  symbol: `ScrapingPlan`
  excerpt: |
    class ScrapingPlan(BaseModel):
        name: Optional[str] = None
        version: str = "1.0"
        tags: List[str]
        url: str
        domain: str = ""
        objective: str
        steps: List[Dict[str, Any]]
        selectors: Optional[List[Dict[str, Any]]] = None
        browser_config: Optional[Dict[str, Any]] = None

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py`
  lines: 31-44
  symbol: `_compute_fingerprint`
  excerpt: |
    def _compute_fingerprint(normalized_url: str) -> str:
        digest = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
        return digest[:16]

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py`
  lines: 98-109
  symbol: `model_post_init`
  excerpt: |
    def model_post_init(self, __context: Any) -> None:
        parsed = urlparse(self.url)
        if not self.domain:
            self.domain = parsed.netloc
        if self.name is None:
            self.name = _sanitize_domain(self.domain)
        if not self.fingerprint:
            self.fingerprint = _compute_fingerprint(self.normalized_url)

## Notes

Fingerprint is derived solely from URL. For TemplatePlan.bind(), the fingerprint of the produced ScrapingPlan must incorporate parameter values — otherwise two binds of the same URL template with different params would collide.
