# SPEC-01 — `ScrapingPlan` & `PlanRegistry`
**Project:** AI-Parrot · WebScrapingToolkit  
**Version:** 1.0  
**Status:** Draft  
**File:** `parrot/tools/scraping/plan.py`

---

## 1. Purpose

This spec defines the data model and persistence layer for scraping plans. A
`ScrapingPlan` is the central contract that travels between plan creation,
human review, execution, and caching. `PlanRegistry` is the index that maps
URLs/domains to saved plans on disk, acting as a cache layer to prevent
redundant LLM inference calls.

---

## 2. Design Principles

- **Immutable once saved.** Plans on disk are never mutated; a new version is
  written instead, keeping a revision trail.
- **Domain-first matching.** Registry lookup works by exact URL → path prefix
  → domain, in that order. This means a plan created for
  `https://example.com/products` can be reused for any sub-path under
  `example.com/products/`.
- **Disk-only persistence.** No Redis or DB dependency in this layer. The
  registry is a single `registry.json` file in a configurable base directory.
- **Fingerprint stability.** The fingerprint hash strips query parameters and
  fragments before hashing, so URLs with tracking params still match a saved
  plan.

---

## 3. `ScrapingPlan` Model

### 3.1 Location

```
parrot/tools/scraping/plan.py
```

### 3.2 Pydantic Definition

```python
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, computed_field
import hashlib
from urllib.parse import urlparse, urlunparse


class ScrapingPlan(BaseModel):
    """
    Declarative scraping plan produced by the LLM and consumed by the
    execution engine.  Treated as a value object: create a new version
    instead of mutating an existing one.
    """

    # --- Identity ---
    name: Optional[str] = Field(
        default=None,
        description="Human-readable name.  Auto-derived from domain if omitted."
    )
    version: str = Field(
        default="1.0",
        description="Semantic version string for plan evolution tracking."
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Free-form labels for search/filtering."
    )

    # --- Target ---
    url: str = Field(description="Canonical entry-point URL for this plan.")
    domain: str = Field(description="Extracted domain (set automatically).")
    objective: str = Field(
        description="Natural-language goal the plan was created to achieve."
    )

    # --- Execution contract ---
    steps: List[Dict[str, Any]] = Field(
        description="Ordered browser action steps (same schema as WebScrapingTool)."
    )
    selectors: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Content extraction selectors."
    )
    browser_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Browser/driver overrides (headless, browser type, etc.)."
    )

    # --- Crawl hints (optional, populated for crawl-type plans) ---
    follow_selector: Optional[str] = Field(
        default=None,
        description="CSS or XPath selector for pagination/next-page links."
    )
    follow_pattern: Optional[str] = Field(
        default=None,
        description="Regex pattern to filter which discovered URLs to follow."
    )
    max_depth: Optional[int] = Field(
        default=None,
        description="Maximum crawl depth hint stored with the plan."
    )

    # --- Metadata ---
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default=None)
    source: str = Field(
        default="llm",
        description="How the plan was created: 'llm' | 'manual' | 'imported'."
    )
    fingerprint: str = Field(
        default="",
        description="SHA-256 of the normalized URL (no query/fragment)."
    )

    # --- Computed ---
    @computed_field
    @property
    def normalized_url(self) -> str:
        """URL stripped of query params and fragment for stable matching."""
        parsed = urlparse(self.url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    def model_post_init(self, __context: Any) -> None:
        """Auto-populate derived fields."""
        if not self.domain:
            self.domain = urlparse(self.url).netloc
        if not self.name:
            self.name = self.domain.replace(".", "_")
        if not self.fingerprint:
            self.fingerprint = hashlib.sha256(
                self.normalized_url.encode()
            ).hexdigest()[:16]
```

### 3.3 Serialization

Plans serialize to/from JSON via `.model_dump_json()` / `ScrapingPlan.model_validate_json()`.
The on-disk filename convention is:

```
{plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json
```

Example:
```
~/.aiparrot/plans/example_com/example_com_v1.0_a3f9c2b1.json
```

---

## 4. `PlanRegistry`

### 4.1 Responsibility

Maintains a single `registry.json` index in the plans base directory. The
index provides fast lookup without scanning all plan files.

### 4.2 Registry index schema

```json
{
  "version": "1",
  "entries": {
    "<fingerprint>": {
      "name": "example_com",
      "plan_version": "1.0",
      "url": "https://example.com/products",
      "domain": "example.com",
      "path": "example_com/example_com_v1.0_a3f9c2b1.json",
      "created_at": "2025-01-01T00:00:00Z",
      "last_used_at": "2025-01-10T12:00:00Z",
      "use_count": 7,
      "tags": ["ecommerce", "products"]
    }
  }
}
```

### 4.3 Class definition

```python
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import aiofiles
from pydantic import BaseModel


class PlanRegistryEntry(BaseModel):
    name: str
    plan_version: str
    url: str
    domain: str
    path: str                      # relative to plans_dir
    created_at: datetime
    last_used_at: Optional[datetime] = None
    use_count: int = 0
    tags: List[str] = []


class PlanRegistry:
    """
    Disk-backed index of saved scraping plans.

    Thread/task safety: a single asyncio.Lock guards all write operations.
    Multiple concurrent reads are allowed (lock not required for reads after
    initial load because the in-memory dict is replaced atomically).
    """

    REGISTRY_FILE = "registry.json"
    DEFAULT_DIR = Path.home() / ".aiparrot" / "plans"

    def __init__(self, plans_dir: Optional[Path] = None):
        self.plans_dir = Path(plans_dir or self.DEFAULT_DIR)
        self._registry_path = self.plans_dir / self.REGISTRY_FILE
        self._entries: Dict[str, PlanRegistryEntry] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load (or initialize) the registry from disk."""
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        if self._registry_path.exists():
            async with aiofiles.open(self._registry_path, "r") as f:
                raw = json.loads(await f.read())
            self._entries = {
                fp: PlanRegistryEntry(**entry)
                for fp, entry in raw.get("entries", {}).items()
            }
        self._loaded = True

    async def _save(self) -> None:
        """Persist registry to disk.  Must be called while holding _lock."""
        payload = {
            "version": "1",
            "entries": {
                fp: entry.model_dump(mode="json")
                for fp, entry in self._entries.items()
            },
        }
        async with aiofiles.open(self._registry_path, "w") as f:
            await f.write(json.dumps(payload, indent=2, default=str))

    # ------------------------------------------------------------------
    # Lookup (no lock needed — reads the immutable dict reference)
    # ------------------------------------------------------------------

    def lookup(self, url: str) -> Optional[PlanRegistryEntry]:
        """
        Find a registered plan for the given URL using a three-tier strategy:
          1. Exact fingerprint match (full URL minus query/fragment)
          2. Path-prefix match  (most-specific prefix wins)
          3. Domain-only match
        Returns None if no match found.
        """
        from .plan import ScrapingPlan
        target = ScrapingPlan.model_construct(url=url, domain="", fingerprint="")
        target.model_post_init(None)
        fingerprint = target.fingerprint

        # Tier 1 — exact fingerprint
        if fingerprint in self._entries:
            return self._entries[fingerprint]

        # Tier 2 — path prefix (find longest matching path)
        from urllib.parse import urlparse
        parsed = urlparse(url)
        candidates = []
        for entry in self._entries.values():
            ep = urlparse(entry.url)
            if ep.netloc == parsed.netloc and parsed.path.startswith(ep.path):
                candidates.append((len(ep.path), entry))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        # Tier 3 — domain only
        domain = parsed.netloc
        for entry in self._entries.values():
            if entry.domain == domain:
                return entry

        return None

    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]:
        """Look up a plan by its human-readable name."""
        for entry in self._entries.values():
            if entry.name == name:
                return entry
        return None

    def list_all(self) -> List[PlanRegistryEntry]:
        """Return all registered plans sorted by last_used_at descending."""
        return sorted(
            self._entries.values(),
            key=lambda e: e.last_used_at or e.created_at,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Mutations (require lock)
    # ------------------------------------------------------------------

    async def register(self, plan: "ScrapingPlan", relative_path: str) -> None:
        """Add or update an entry.  Creates a new version entry if plan
        fingerprint already exists but version differs."""
        async with self._lock:
            self._entries[plan.fingerprint] = PlanRegistryEntry(
                name=plan.name,
                plan_version=plan.version,
                url=plan.url,
                domain=plan.domain,
                path=relative_path,
                created_at=plan.created_at,
                last_used_at=datetime.utcnow(),
                use_count=self._entries.get(plan.fingerprint, PlanRegistryEntry(
                    name="", plan_version="", url="", domain="", path="",
                    created_at=datetime.utcnow()
                )).use_count + 1,
                tags=plan.tags,
            )
            await self._save()

    async def touch(self, fingerprint: str) -> None:
        """Update last_used_at and increment use_count for cache-hit tracking."""
        async with self._lock:
            if fingerprint in self._entries:
                entry = self._entries[fingerprint]
                self._entries[fingerprint] = entry.model_copy(update={
                    "last_used_at": datetime.utcnow(),
                    "use_count": entry.use_count + 1,
                })
                await self._save()

    async def remove(self, name: str) -> bool:
        """Remove plan from index by name.  Does not delete the file."""
        async with self._lock:
            target = self.get_by_name(name)
            if not target:
                return False
            # find fingerprint
            fp = next(
                (f for f, e in self._entries.items() if e.name == name), None
            )
            if fp:
                del self._entries[fp]
                await self._save()
            return True
```

### 4.4 Plan file I/O helpers

These free functions are used by the toolkit (not the registry directly):

```python
async def save_plan_to_disk(
    plan: ScrapingPlan,
    plans_dir: Path,
) -> Path:
    """
    Write plan JSON to the canonical path under plans_dir.
    Returns the absolute path written.
    """
    domain_dir = plans_dir / plan.domain.replace(".", "_")
    domain_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{plan.name}_v{plan.version}_{plan.fingerprint}.json"
    path = domain_dir / filename
    async with aiofiles.open(path, "w") as f:
        await f.write(plan.model_dump_json(indent=2))
    return path


async def load_plan_from_disk(path: Path) -> ScrapingPlan:
    """Deserialize a plan from an absolute file path."""
    async with aiofiles.open(path, "r") as f:
        return ScrapingPlan.model_validate_json(await f.read())
```

---

## 5. Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `plans_dir` | `~/.aiparrot/plans` | Base directory for all plan files and the registry index |

The directory is created automatically on first use.

---

## 6. File layout after saving several plans

```
~/.aiparrot/plans/
├── registry.json
├── example_com/
│   ├── example_com_v1.0_a3f9c2b1.json
│   └── example_com_v1.1_a3f9c2b1.json   ← updated version
├── shop_example_com/
│   └── shop_example_com_v1.0_d7e1a4f0.json
└── news_ycombinator_com/
    └── news_ycombinator_com_v1.0_88bc3d11.json
```

---

## 7. Dependencies

| Package | Use |
|---------|-----|
| `pydantic` v2 | Model definition and JSON serialization |
| `aiofiles` | Async file I/O |
| Standard library | `hashlib`, `pathlib`, `asyncio`, `json`, `urllib.parse` |

No new dependencies beyond what AI-Parrot already requires.

---

## 8. Tests (expected coverage)

- `ScrapingPlan`: fingerprint stability across URL variants, auto-population of `domain` and `name`, round-trip JSON serialization.
- `PlanRegistry.lookup`: all three tiers (exact, prefix, domain), no false positives.
- `PlanRegistry` mutations: register, touch, remove with concurrent async tasks.
- File I/O helpers: save and reload a plan, verify field equality.

---

*Next: [SPEC-02 — WebScrapingToolkit](./SPEC-02-WebScrapingToolkit.md)*
