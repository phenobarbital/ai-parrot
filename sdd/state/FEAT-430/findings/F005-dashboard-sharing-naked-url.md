# F005 — Navigator dashboard sharing exists; the naked-URL problem is REAL and in production

**Query:** Q008 (grep, navigator-api)
**Citations:** `navigator-api/apps/ambassador/views.py`
  :: `LeadHandler._build_offers_urls` (L325-347), `_put_callback` (L349-375)
**Repo:** `/home/jelitox/repos/trocglobal/navigator-api` (not wiki-indexed; grep is correct here)
**Confidence:** high (direct source read)

## Confirmed: dashboard share URL pattern (brainstorm §3.4)

```python
base_url = "https://connect.trocdigital.io/share/dashboard/"          # production
base_url = f"https://connect.{_env}.trocdigital.io/share/dashboard/"  # non-prod
full_url = urljoin(base_url, str(offer.dashboard_id)) + "?" + urlencode(query_params)
```

Canonical share URL: `https://connect[.<env>].trocdigital.io/share/dashboard/<dashboard_id>?...`
Scoping is by `dashboard_id` in the path — consistent with §3.4's "token grants access
only to that specific dashboard".

## CONFIRMED WITH EVIDENCE: brainstorm rev2 #4 (the naked-URL problem)

```python
_api_key = config.get("AMBASSADOR_ANONYM_USER_TOKEN")
query_params = {"referalcode": lead_id, "apikey": _api_key}
```

The share link carries a **long-lived, shared, environment-wide anonymous user token**
as a query parameter, and is then emailed to external leads (`_put_callback` →
`_build_email_msg` → `NotifyClient.stream`). This is exactly the "direct, indiscriminate
credential distribution" the brainstorm names — not a hypothetical, but live behavior on
the lead/ambassador path.

Properties of the current mechanism:
- credential is **static** (a config value, not per-recipient, not per-send)
- credential is **not time-bounded** (no TTL, no expiry)
- credential is **not revocable per-recipient** (rotating it breaks every link ever sent)
- scoping comes only from `dashboard_id` in the path, not from the token itself

This makes HI-3 a **fix to existing behavior**, not merely a constraint on new code —
which raises SPEC-A's value and should be stated as such in the proposal.

## Secondary observations

- `Dashboard` model with `dashboard_id` + `name` is used here via
  `_get_multi_records_or_raise_error(self, Dashboard, "dashboard_id", offers_ids)`.
- navigator-api already delivers templated email through `NotifyClient`/
  `NOTIFY_WORKER_STREAM` with `template="email_lead.html"` — a **third** notify entry
  point beyond the two the brainstorm names (Flowtask `SendNotify` + scheduler callback).
  The proposal should confirm which entry point SPEC-A's email path should use.
