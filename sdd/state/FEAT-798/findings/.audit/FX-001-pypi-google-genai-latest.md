---
id: FX-001
query_id: Q016
type: read
intent: "External: latest google-genai release on PyPI (upgrade target for the SDK bump)"
executed_at: 2026-11-04T01:36:55Z
duration_ms: 900
parent_id: null
depth: 1
---

# FX-001 — google-genai latest on PyPI is 2.34.0 (2026-10-29); FEAT-688's candidate floor was 2.31.0

## Summary

PyPI (`https://pypi.org/pypi/google-genai/json`, fetched 2026-11-04T01:36:55Z) reports the latest release as
**2.34.0** (uploaded 2026-10-29), `requires_python >=3.11`. Releases since the FEAT-688 work:
2.28.0 (10-02), 2.29.0 (10-07), 2.30.0/2.30.1 (10-13), 2.31.0 (10-14), 2.32.0 (10-21), 2.33.0 (10-23), 2.34.0 (10-29).
Cadence is roughly weekly, so any floor declared in a spec must be re-verified at implementation time.

## Citations

- path: `https://pypi.org/pypi/google-genai/json`
  lines: n/a
  symbol: `info.version`
  excerpt: |
    latest 2.34.0 requires_python >=3.11
    2.31.0 2026-10-14
    2.32.0 2026-10-21
    2.33.0 2026-10-23
    2.34.0 2026-10-29

## Notes

External source, not a repo file; the synthesis must not cite it as a codebase path. Pair with the
pyproject / uv.lock pin reported by the codebase lane (Q016).
