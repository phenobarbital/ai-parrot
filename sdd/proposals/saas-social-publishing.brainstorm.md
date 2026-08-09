---
type: feature
base_branch: dev
---

# Brainstorm: `SocialPublisher` port — Instagram and TikTok publishing

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option B
**Related**: `saas-reel-generator-flow.brainstorm.md`

---

## Problem Statement

The reel flow produces a finished vertical video. The product promise is that a
tenant can then publish it to Instagram or TikTok without leaving the platform.

## The starting point: nothing exists

This is the clearest finding of the investigation and it is worth stating
plainly, because the rest of the reel pipeline is mature enough to create the
opposite impression.

A whole-repo content search across every `.py` and `.toml` under `packages/`
for `instagram`, `tiktok`, `facebook` and `graph.facebook.com` returns **zero
matches**. There is no Meta Graph client, no OAuth flow for either platform, no
post scheduler, and no publishing tool. Every `publish` hit in `parrot_tools`
is unrelated: AWS Lambda `Publish`, CloudWatch metrics, `publish_dashboard` for
Navigator dashboards, `whatif_toolkit` scenario publishing, and RSS
`published_parsed` timestamps.

Adjacent capability that *does* exist and will be reused: `FileManagerFactory`
(`parrot/tools/filemanager.py`) with lazy S3/GCS managers, since both platforms
ingest video by **public URL**, not by upload from the caller.

## What each platform actually requires

**Instagram (Reels)** — Instagram Graph API, via a Facebook app:
- An Instagram *Business* or *Creator* account linked to a Facebook Page.
- Two-step publish: `POST /{ig-user-id}/media` with `media_type=REELS` and a
  publicly reachable `video_url`, poll `status_code` until `FINISHED`, then
  `POST /{ig-user-id}/media_publish`.
- Rate limit: 25 posts per 24 hours per account.
- Permissions (`instagram_content_publish`, `pages_show_list`, …) require **App
  Review**, which is a submission-and-wait process, not an afternoon.

**TikTok** — Content Posting API:
- Developer app plus per-user OAuth.
- `PULL_FROM_URL` requires domain verification; otherwise `FILE_UPLOAD`.
- Unaudited apps can only post to **private/self-only** visibility until audit
  passes — so a demo can look like it works while being unable to publish
  publicly.

The engineering here is modest. The gating work is account setup, domain
verification and platform review, and it should be scheduled as such.

---

## Constraints & Requirements

- Publishing is public, irreversible and brand-facing: it must sit behind an
  explicit human approval, never agent discretion.
- Per-tenant OAuth tokens in the `SecretStore`, with refresh handling.
- Video must be reachable at a public HTTPS URL for the duration of ingestion —
  which argues for a signed, expiring S3/GCS URL rather than a permanent one.
- Both platforms are asynchronous: publishing is a job with polling, not a
  request/response.

---

## Options Explored

### Option A: Direct calls from a publishing tool

An `AbstractTool` per platform, called by the agent.

✅ **Pros:** fastest to a demo.

❌ **Cons:** no shared retry/poll/approval story; each platform's async
lifecycle reimplemented; an agent holding publish authority is exactly the
wrong default.

📊 **Effort:** Low.

### Option B: `SocialPublisher` port + per-platform adapters + a publish job — RECOMMENDED

```python
class SocialPublisher(Protocol):
    platform: str
    async def authorize_url(self, tenant_id: str) -> str: ...
    async def publish_video(self, tenant_id: str, *, video_url: str,
                            caption: str, options: Mapping) -> PublishHandle: ...
    async def poll(self, tenant_id: str, handle: PublishHandle) -> PublishStatus: ...
```

with `InstagramPublisher`, `TikTokPublisher`, and a `MockPublisher` that lets
the whole approval-and-publish path be built and tested before any platform
review is granted — the same trick the `ReviewSource` port used, and for the
same reason.

✅ **Pros:** one async lifecycle; approval gate lives above the port; the mock
keeps the feature unblocked by third-party timelines; adding a platform is an
adapter.

❌ **Cons:** more structure than one platform strictly needs.

📊 **Effort:** Medium (plus non-engineering lead time).

🔗 **Existing Code to Reuse:** `parrot/tools/filemanager.py` for signed URLs;
`handlers/jobs/` `JobManager` for the 202+poll surface; `parrot/auth/oauth2*`
for the OAuth dance shape.

### Option C: Third-party scheduler (Buffer / Later / Ayrshare)

✅ **Pros:** one API, several platforms, no app review.

❌ **Cons:** per-tenant subscription cost; a hard dependency for a core promise;
still needs per-tenant account linking.

📊 **Effort:** Low engineering, ongoing cost.

---

## Open Questions

- [ ] One platform-owned Meta/TikTok app with tenants linking accounts, or an
      app per tenant? Affects review burden and blast radius.
- [ ] Is publishing part of the base plan or an add-on? App review effort is
      the same either way.
- [ ] Signed-URL lifetime versus platform ingestion time — needs measuring, not
      guessing.
- [ ] Should a rejected publish auto-retry, or always return to a human?

## Recommendation

Option B, with the mock adapter built first so the approval and publish flow can
ship and be exercised while platform review is pending. Start the Meta and
TikTok app submissions in parallel with the engineering, not after it.
