# F007 — A2UI (FEAT-273) already ships artifact + delivery + secure deep-link machinery

**Query:** Q006 (wiki_query + direct read)
**Citations:**
  `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` :: `RenderedArtifact`, `DeepLink`
  `packages/ai-parrot/src/parrot/outputs/a2ui/delivery.py` :: `deliver_artifact`
  `packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py` :: `DeepLinkService`
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/`
    :: `adaptive_cards.py`, `ssr_html.py`, `interactive_html.py`, `pdf.py`
**Confidence:** high (direct source read)

## FEAT-273 is broader than the brainstorm assumes

Brainstorm §3.5/§5 treats FEAT-273 as "agents respond in A2UI structures". It also
already contains the **artifact, delivery and sharing** layers SPEC-A believes it must
build:

- **`RenderedArtifact`** — "the self-contained, fully-baked output of a static renderer
  (PDF, email HTML, baked document)", carrying inline `content` XOR a `path`. This is a
  ready-made common abstraction for the feature-flagged coexistence the user requires:
  both `v1-html` and `v2-a2ui` generators can emit a `RenderedArtifact`.
- **`deliver_artifact()`** — explicitly "maps a baked RenderedArtifact onto the EXISTING
  `NotificationMixin.send_notification` machinery (spec G5) — never a new delivery
  stack", with documented per-provider policy (EMAIL/TELEGRAM attach, SLACK gets a
  public artifact URL via `ArtifactStore.get_public_url`, TEAMS noted as TASK-1734).
- **`a2ui_renderers/adaptive_cards.py`** — an A2UI → Adaptive Cards renderer already
  exists, alongside `ssr_html`, `interactive_html` and `pdf`.

This directly answers SPEC-B open question §5.1.D ("A2UI → sendable/viewable rendering
for the share URL target"): renderers for card, SSR HTML and PDF already exist.

## `DeepLinkService` — the secure-sharing pattern already chosen in this codebase

`deeplink.py` implements single-use, TTL-bound opaque tokens, and its docstring records
a design decision that maps 1:1 onto brainstorm HI-3:

> navigator_auth exposes a JWT `create_token` mint, but binding core to it would violate
> the one-way import rule (G8). This service therefore uses the **pre-approved Redis
> opaque one-shot token** ... The URL embeds ONLY the opaque id — never the payload.

Properties: `secrets.token_urlsafe(32)` opaque id, Redis-stored payload, TTL, deleted on
first consume (replay guard). This is a stronger answer to the naked-URL problem (F005)
than the brainstorm's proposal, and it is already built and reviewed.
