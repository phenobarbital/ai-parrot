---
type: feature
base_branch: dev
---

# Brainstorm: Real review sources behind the `ReviewSource` port

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The Community Manager flow ships against a mock adapter and a generic
HMAC-signed webhook, deliberately: the flow had to be buildable and testable
without waiting on third-party API approvals. To be useful it needs at least
one real source that can both **read** reviews and **publish** replies.

## What already exists (verified)

### Google Business Profile — nearly free

`packages/ai-parrot-tools/src/parrot_tools/google/places.py` —
`GoogleBusinessTool(GoogleBaseTool)`, `name = "google_business"`:

- `GoogleBusinessToolArgs` commands: `list_accounts`, `list_locations`,
  `get_reviews`, `reply_review`, `delete_reply`; args `account_id`,
  `location_id`, `review_id`, `reply_text`, `language`.
- Calls the `mybusinessaccountmanagement` and `mybusinessreviews` APIs
  (`accounts.locations.reviews`), returning `reviewId`, `reviewer`,
  `starRating`, `comment`, `createTime`, `updateTime`.
- Runs sentiment analysis per review with **TextBlob** — note this duplicates
  what the flow's triage node does, and the two will disagree; pick one.
- The OAuth scope `https://www.googleapis.com/auth/business.manage` is already
  declared in `DEFAULT_SCOPES['business']` at
  `packages/ai-parrot/src/parrot/interfaces/google.py:79-82` and included in
  `DEFAULT_SCOPES['all']`.

This maps almost one-to-one onto the port: `get_reviews` → `fetch`,
`reply_review` → `reply`.

### Everything else

A whole-repo search finds **nothing** for Yelp, TripAdvisor, TheFork/ElTenedor,
or Meta page reviews. Adjacent but not applicable: `parrot_tools/reddit.py`
(read-only PRAW), `parrot_tools/rss/`, and the generic
`parrot_tools/scraping/` subsystem, whose README lists "Social Media Scraping"
as a documented *use case* of the crawler rather than a built integration.

The platform realities, which should be decided before any effort is spent:

| Source | Read reviews | Post replies | Notes |
|---|---|---|---|
| Google Business Profile | Official API | Official API | Already wrapped here |
| Meta (Facebook Page) | Graph API | Graph API | Needs app review; page recommendations replaced star ratings |
| TripAdvisor | Content API is partner-gated | **No public reply API** | Replies are manual in their portal |
| TheFork | No public API | No | Partner integration only |
| Yelp | Fusion API is read-only, review excerpts only | No | Explicitly prohibits scraping |

The honest summary: **Google Business Profile is the only source with a
complete, publicly available read-and-reply API.** Anything else is either
partner-gated or manual, and a product plan that assumes otherwise will not
survive contact with the platforms.

---

## Constraints & Requirements

- OAuth tokens are per tenant and must live in the `SecretStore`, not in
  process config. `GoogleBusinessTool` today resolves credentials the way the
  rest of `parrot_tools` does; that path needs a tenant dimension.
- The port's `fetch` is pull-based; Google Business Profile has no review
  webhook, so ingestion needs a poller with a watermark.
- Review de-duplication relies on `UNIQUE(tenant_id, source, external_id)`.
  Google supplies a stable `reviewId`, so this is satisfied; a source without a
  stable id would need a content hash instead.

---

## Options Explored

### Option A: `GoogleBusinessReviewSource` + a polling ingester — RECOMMENDED

Wrap the existing tool behind the port; add a per-tenant poller that stores a
watermark and feeds `POST /reviews/ingest` internally.

✅ **Pros:** the API work is already done; the scope is already declared; it is
the source hospitality businesses care most about.

❌ **Cons:** OAuth onboarding per tenant is real work; polling needs rate-limit
care; the TextBlob sentiment overlap needs resolving.

📊 **Effort:** Medium.

🔗 **Existing Code to Reuse:** `parrot_tools/google/places.py`,
`parrot/interfaces/google.py` (scopes), `parrot/auth/` OAuth machinery
(`jira_oauth.py` / `o365_oauth.py` as shape references).

### Option B: Meta Graph API for Facebook Page recommendations

✅ **Pros:** shares credentials with Instagram publishing (see
`saas-social-publishing.brainstorm.md`), so one app review covers both.

❌ **Cons:** app review is slow; recommendations are not star ratings, so the
rating-driven coupon rules need rethinking for this source.

📊 **Effort:** Medium-High, mostly non-engineering.

### Option C: Aggregator (Trustpilot-style or a reputation vendor)

Buy read+reply across platforms through one vendor API.

✅ **Pros:** one integration, several sources, including ones with no public API.

❌ **Cons:** per-tenant vendor cost; the platform becomes a reseller.

📊 **Effort:** Low engineering, high commercial.

---

## Open Questions

- [ ] Does each tenant connect their own Google account by OAuth, or does the
      platform hold a partner credential? This decides the onboarding flow.
- [ ] Poll interval and quota budget per tenant.
- [ ] Keep TextBlob sentiment in the tool, or delete it in favour of the flow's
      triage node? Two disagreeing sentiment values is worse than either.
- [ ] Is TripAdvisor important enough to justify a manual/CSV ingestion path,
      given no reply API exists?

## Recommendation

Option A alone for the first real source, and set expectations explicitly that
TripAdvisor and TheFork are not automatable today — that is a platform
limitation, not a backlog item.
