---
type: Wiki Summary
title: parrot.integrations.matrix.registration
id: mod:parrot.integrations.matrix.registration
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generate Matrix Application Service registration YAML.
relates_to:
- concept: func:parrot.integrations.matrix.registration.generate_registration
  rel: defines
- concept: func:parrot.integrations.matrix.registration.generate_tokens
  rel: defines
---

# `parrot.integrations.matrix.registration`

Generate Matrix Application Service registration YAML.

Produces a Synapse/Conduit/Tuwunel-compatible registration file
that must be placed in the homeserver data directory and referenced
in homeserver.yaml under `app_service_config_files`.

## Functions

- `def generate_tokens() -> tuple[str, str]` — Generate random AS and HS tokens.
- `def generate_registration(as_token: str, hs_token: str, *, bot_localpart: str='parrot', namespace_regex: str='parrot-.*', as_url: str='http://localhost:9090', as_id: str='ai-parrot', output_path: Optional[str]=None) -> dict` — Generate an AS registration YAML.
