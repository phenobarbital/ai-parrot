---
type: Wiki Entity
title: RedisJobInjector
id: class:parrot.autonomous.redis_jobs.RedisJobInjector
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Permite inyectar jobs dinámicamente desde cualquier proceso.
---

# RedisJobInjector

Defined in [`parrot.autonomous.redis_jobs`](../summaries/mod:parrot.autonomous.redis_jobs.md).

```python
class RedisJobInjector
```

Permite inyectar jobs dinámicamente desde cualquier proceso.

Usa Redis como canal de comunicación para agregar jobs al scheduler
sin necesidad de acceso directo al proceso del scheduler.

## Methods

- `async def connect(self)` — Establece conexión con Redis.
- `async def close(self)` — Cierra conexiones.
- `async def inject_job(self, agent_name: str, prompt: str, *, priority: int=5, schedule_at: Optional[datetime]=None, metadata: Optional[Dict[str, Any]]=None, crew_name: Optional[str]=None, method_name: Optional[str]=None, callback_url: Optional[str]=None) -> str` — Inyecta un job para ser ejecutado por el scheduler.
- `async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]` — Obtiene el estado de un job.
- `async def start_listening(self, job_handler: Callable[[Dict[str, Any]], Any])` — Inicia el listener para procesar jobs de la cola.
