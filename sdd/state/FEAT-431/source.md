---
kind: file
source_path: /home/jelitox/BRAINSTORM-dashboard-notify-canvas.md (§5 — SPEC-B)
fetched_at: 2026-08-19T00:00:00Z
summary_oneline: "SPEC-B — Artifact & Canvas Builder: agent-generated A2UI replacing opaque HTML artifacts"
related: FEAT-430 (SPEC-A, ai-parrot)
user_constraints:
  - "Feature-flagged coexistence: v1-html stays supported, v2-a2ui added alongside"
  - "Scope: backend + frontend contract; Canvas Builder itself goes to navigator-svelte with its own FEAT-ID"
decisions:
  - "D1: reverse adapter A2UI -> canvas block vocabulary (frontend never learns A2UI)"
  - "D2: supersede FEAT-301, absorb its theming content into the centralized A2UI catalog"
