# F001 — Monorepo layout: clients live under packages/ai-parrot

**Query**: Q003 preflight (glob/ls) · **Type**: tree

The top-level `parrot/clients/` directory contains only stale `__pycache__`
artifacts (nothing git-tracked). All client source lives at
`packages/ai-parrot/src/parrot/clients/`. The user's requested paths
(`parrot/clients/nova/...`) therefore map to
`packages/ai-parrot/src/parrot/clients/nova/...`.

## Citations
- `packages/ai-parrot/src/parrot/clients/` — google/, nova_sonic.py, bedrock.py, base.py, factory.py, live.py, etc. (git ls-files)
