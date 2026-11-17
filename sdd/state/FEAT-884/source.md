---
kind: inline
jira_key: null
fetched_at: 2026-11-12T19:16:11Z
summary_oneline: "parrot self migration — versioned DB schema migrations for parrot tables (starting with navigator.ai_bots), mirroring navauth self upgrade"
---

db-upgrade -- en navigator-auth implementamos "navauth self upgrade" para actualizar cambios en tablas y mantener up-to-date cambios en las estructuras de las tablas, debemos imitar eso en parrot con "parrot self migration" para permitir que los cambios en tablas relacionadas (empezando con navigator.ai_bots) se documenten y permitan ejecutar una migración efectiva de cambios de manera fácil
