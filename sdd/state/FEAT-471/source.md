---
kind: inline
jira_key: null
fetched_at: 2026-08-28T20:10:00Z
summary_oneline: wikitoolkit needs rustworkx but it is not installed by `uv pip install ai-parrot` and `uv sync` removes it
---

add-rustworkx-dependency -- para funcionar con wikitoolkit * se necesita rustworkx pero esta como dependencia transitiva en algun lado, hacer un "uv pip install ai-parrot" no instala rustworkx, al parecer hacer un "uv sync" también lo desinstala, hay que reparar esa dependencia
