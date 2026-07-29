---
type: Wiki Summary
title: parrot.handlers.csp
id: mod:parrot.handlers.csp
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Content-Security-Policy header builder for infographic HTML serving (FEAT-197).
relates_to:
- concept: func:parrot.handlers.csp.build_csp_headers
  rel: defines
- concept: func:parrot.handlers.csp.frame_ancestors_from_env
  rel: defines
---

# `parrot.handlers.csp`

Content-Security-Policy header builder for infographic HTML serving (FEAT-197).

This helper constructs the full CSP header set required by the public
artifact-HTML endpoint (TASK-1322).  The policy is:

    default-src 'self';
    script-src 'self' 'unsafe-inline' [<cdn origins from js_bundles>];
    style-src 'self' 'unsafe-inline';
    img-src 'self' data:;
    object-src 'none';
    base-uri 'self';
    form-action 'none';
    frame-ancestors [<INFOGRAPHIC_FRAME_ANCESTORS env var or 'self'>];

Plus the non-negotiable security headers:
    X-Content-Type-Options: nosniff
    Referrer-Policy: no-referrer

The ``frame-ancestors`` value is driven by the ``INFOGRAPHIC_FRAME_ANCESTORS``
environment variable (comma-separated list, default ``'self'``).  The
``script-src`` CDN origins are derived from the template's ``JSBundle``
entries whose ``scope == 'cdn'``.

CSP MUST be set via HTTP *response header*, not via ``<meta http-equiv>`` —
this is the only way to ensure the policy is enforced before the page parses.

Design note on ``'unsafe-inline'`` in ``script-src``:
    ECharts requires inline JavaScript for chart initialisation (the
    ``echarts.init()`` call and dataset binding). ``'unsafe-inline'`` is
    intentionally included in ``script-src`` to allow this. As a consequence,
    hash-based inline script allowlisting cannot be used as an additional
    enforcement mechanism — any inline ``<script>`` block present in the
    rendered HTML will execute without restriction.

Mitigations in place:
    - External scripts are restricted to an explicit CDN allowlist enforced by SRI.
    - The ``validate_enhanced_html`` checker in ``_enhance_html_check.py`` blocks
      any external script source not present in the ``JSBundle`` whitelist.
    - ``object-src 'none'`` prevents plugin-based execution vectors.
    - ``base-uri 'self'`` prevents base-tag hijacking.
    - ``form-action 'none'`` prevents cross-origin form submission from the infographic.

Known limitation:
    CSS injection via LLM-generated ``color`` attributes is mitigated by
    ``_validate_css_color`` validators on all block models, but not fully eliminated.

## Functions

- `def build_csp_headers(*, js_bundles: Iterable[object]=(), frame_ancestors: str="'self'") -> Mapping[str, str]` — Build the full CSP + security header set.
- `def frame_ancestors_from_env(env_var: str='INFOGRAPHIC_FRAME_ANCESTORS', default: str="'self'") -> str` — Read ``INFOGRAPHIC_FRAME_ANCESTORS`` and normalise to space-separated.
