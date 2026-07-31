---
type: Wiki Summary
title: parrot.outputs.a2ui.delivery
id: mod:parrot.outputs.a2ui.delivery
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI delivery bridge (Module 7, first half).
relates_to:
- concept: func:parrot.outputs.a2ui.delivery.deliver_artifact
  rel: defines
- concept: mod:parrot.outputs.a2ui.artifacts
  rel: references
---

# `parrot.outputs.a2ui.delivery`

A2UI delivery bridge (Module 7, first half).

Maps a baked :class:`~parrot.outputs.a2ui.artifacts.RenderedArtifact` onto the EXISTING
``NotificationMixin.send_notification`` machinery (spec G5) — never a new delivery stack.
Attachments flow through the mixin's ``report.files`` PRIORITY-1 extraction path.

Per-provider policy:
* **EMAIL / TELEGRAM** — full attachment via ``report.files`` (works today, no mixin change).
* **SLACK** — no file upload (spec Non-Goal); a public artifact URL line is appended in
  ``_send_slack`` (the bridge computes it via ``ArtifactStore.get_public_url`` and passes
  it as a kwarg). Degraded delivery is logged, never silent.
* **TEAMS** — unchanged filenames-in-text today; real Graph upload is TASK-1734.

One-way import rule (G8): this module never imports agents/DatasetManager/LLM clients,
nor the notifications subsystem — the provider is passed as a string (matching the
``NotificationProvider`` enum *values*) and the mixin-bearing owner is passed in.

## Functions

- `async def deliver_artifact(owner: Any, artifact: RenderedArtifact, *, recipients: Any, provider: Any=_EMAIL, message: str='', subject: Optional[str]=None, artifact_store: Any=None, user_id: Optional[str]=None, agent_id: Optional[str]=None, session_id: Optional[str]=None) -> dict[str, Any]` — Deliver a ``RenderedArtifact`` via ``owner.send_notification`` (per-provider policy).
