---
id: F006
query_id: Q007
type: grep
intent: Find existing Drive tools / consumers anywhere in the repo (Q007 + Q008)
executed_at: 2026-09-25T22:53:00Z
duration_ms: 1200
parent_id: null
depth: 0
---

# F006 — No Drive tool, loader, or integration exists; the only hit is the scope table in `google.py`

## Summary

`grep -in drive parrot_tools/google/tools.py` matches only `travel_mode:
"DRIVE"` (Routes API) and a selenium comment. A repo-wide
`googleapis.com/auth/drive|GoogleDrive|google_drive|gdrive` grep over
`packages docs examples` (py/md/toml) hits only
`packages/ai-parrot/src/parrot/interfaces/google.py` (and its stale
`build/lib` copy). Proves absence: no naming collision, no legacy path to
preserve, no loader that would need migrating.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/google/tools.py`
  lines: 50
  symbol: `GoogleRouteArgs.travel_mode`
  excerpt: |
    travel_mode: str = Field(default="DRIVE", description="Travel mode: DRIVE, WALK, BICYCLE, TRANSIT")

- path: `packages/ai-parrot-tools/src/parrot_tools/google/tools.py`
  lines: 15-19
  symbol: imports
  excerpt: |
    from googleapiclient.discovery import build      # sync google-api-python-client, used by search tools
    from parrot.conf import GOOGLE_API_KEY
    from ..abstract import AbstractTool

- path: `packages/ai-parrot-tools/src/parrot_tools/google/tools.py`
  lines: 134-354
  symbol: `GooglePlacesBaseTool / GoogleSearchTool / GoogleSiteSearchTool`
  excerpt: |
    class GooglePlacesBaseTool(AbstractTool): ...
    class GoogleSearchTool(AbstractTool): ...

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 41-47
  symbol: `DEFAULT_SCOPES["drive"]`
  excerpt: |
    "https://www.googleapis.com/auth/drive"   # only repo-wide match for the Drive scope
