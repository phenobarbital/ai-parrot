# F001 — Repo drift since brainstorm date (2026-08-09)
**Query**: Q001/Q002/Q003 (git_log) · **Confidence**: high

Heavy churn, none of it overlapping the SaaS program's scope except tenancy precedent (→F002):
- clients/: FEAT-438 rebased OpenAI/Groq/Zai onto `OpenAIBaseClient`; new codex client; Bedrock API-key fix (b5893f4e4). Line anchors in `clients/base.py` moved (→F008).
- flows/: workflow **authoring** pipeline landed (9ca8b580a, cda45e33a "close the FlowDefinition models and tag the action union", 46cb7b8be NodeDefinition.config-driven construction, 60811a57b "keep already-stored crews loadable under extra=forbid"). `flow.py` reworked (FEAT-377 back-edges) — all brainstorm line anchors in flow.py drifted (→F005).
- server/: crew HTTP surface extended (durable job progress 966242b4b, tales-research POST handler fc03ad64c) — **more unauthenticated crew surface, not less**.
- security: f2c34cb44 resolved 121 CodeQL alerts — did NOT add auth to crew handlers (→F003).
- sdd/: FEAT-437..441 all unrelated to tenancy/metering. No competing SaaS work started.
