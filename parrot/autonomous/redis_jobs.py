# parrot/autonomy/redis_jobs.py
import json
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import asyncio
import redis.asyncio as aioredis
from navconfig.logging import logging


class RedisJobInjector:
    """
    Permite inyectar jobs dinámicamente desde cualquier proceso.
    
    Usa Redis como canal de comunicación para agregar jobs al scheduler
    sin necesidad de acceso directo al proceso del scheduler.
    """
    
    CHANNEL_PREFIX = "parrot:jobs:"
    QUEUE_NAME = "parrot:job_queue"
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        db: int = 0
    ):
        self.redis_url = redis_url
        self.db = db
        self._redis: Optional[aioredis.Redis] = None
        self._subscriber: Optional[aioredis.Redis] = None
        self._listening = False
        self.logger = logging.getLogger("parrot.autonomy.redis_jobs")
        
        # Callbacks para cuando llega un job
        self._job_handlers: Dict[str, Callable] = {}
    
    async def connect(self):
        """Establece conexión con Redis."""
        self._redis = await aioredis.from_url(
            self.redis_url,
            db=self.db,
            decode_responses=True
        )
        self._subscriber = await aioredis.from_url(
            self.redis_url,
            db=self.db,
            decode_responses=True
        )
    
    async def close(self):
        """Cierra conexiones."""
        self._listening = False
        if self._redis:
            await self._redis.close()
        if self._subscriber:
            await self._subscriber.close()
    
    # === Producer Side (inyectar jobs) ===
    
    async def inject_job(
        self,
        agent_name: str,
        prompt: str,
        *,
        priority: int = 5,  # 1-10, menor = más prioritario
        schedule_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        crew_name: Optional[str] = None,
        method_name: Optional[str] = None,
        callback_url: Optional[str] = None,  # Webhook para notificar resultado
    ) -> str:
        """
        Inyecta un job para ser ejecutado por el scheduler.
        
        Puede ser llamado desde cualquier proceso que tenga acceso a Redis.
        
        Returns:
            job_id: ID único del job inyectado
        """
        import uuid
        
        job_id = str(uuid.uuid4())
        job_data = {
            "job_id": job_id,
            "agent_name": agent_name,
            "prompt": prompt,
            "priority": priority,
            "schedule_at": schedule_at.isoformat() if schedule_at else None,
            "metadata": metadata or {},
            "crew_name": crew_name,
            "method_name": method_name,
            "callback_url": callback_url,
            "injected_at": datetime.now().isoformat(),
            "status": "pending"
        }
        
        # Guardar job data
        await self._redis.hset(
            f"{self.CHANNEL_PREFIX}data:{job_id}",
            mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v or "") 
                    for k, v in job_data.items()}
        )
        
        # Agregar a cola con prioridad (sorted set)
        score = priority * 1e10 + datetime.now().timestamp()
        await self._redis.zadd(self.QUEUE_NAME, {job_id: score})
        
        # Publicar notificación
        await self._redis.publish(
            f"{self.CHANNEL_PREFIX}new_job",
            json.dumps({"job_id": job_id, "agent_name": agent_name})
        )
        
        self.logger.info(f"Injected job {job_id} for agent {agent_name}")
        return job_id
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene el estado de un job."""
        data = await self._redis.hgetall(f"{self.CHANNEL_PREFIX}data:{job_id}")
        if not data:
            return None
        
        # Deserializar
        result = {}
        for k, v in data.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result
    
    # === Consumer Side (procesar jobs) ===
    
    async def start_listening(
        self,
        job_handler: Callable[[Dict[str, Any]], Any]
    ):
        """
        Inicia el listener para procesar jobs de la cola.
        
        Args:
            job_handler: Función async que recibe el job_data y lo procesa
        """
        self._listening = True
        
        # Suscribirse a notificaciones
        pubsub = self._subscriber.pubsub()
        await pubsub.subscribe(f"{self.CHANNEL_PREFIX}new_job")
        
        self.logger.info("Started Redis job listener")
        
        async def process_queue():
            while self._listening:
                # Pop job de la cola (el de menor score = mayor prioridad)
                result = await self._redis.zpopmin(self.QUEUE_NAME, 1)
                
                if result:
                    job_id, score = result[0]
                    job_data = await self.get_job_status(job_id)
                    
                    if job_data and job_data.get("status") == "pending":
                        # Marcar como processing
                        await self._redis.hset(
                            f"{self.CHANNEL_PREFIX}data:{job_id}",
                            "status", "processing"
                        )
                        
                        try:
                            # Ejecutar handler
                            result = await job_handler(job_data)
                            
                            # Actualizar resultado
                            await self._redis.hset(
                                f"{self.CHANNEL_PREFIX}data:{job_id}",
                                mapping={
                                    "status": "completed",
                                    "result": json.dumps(result) if result else "",
                                    "completed_at": datetime.now().isoformat()
                                }
                            )
                            
                            # Notificar callback si existe
                            if callback_url := job_data.get("callback_url"):
                                await self._notify_callback(callback_url, job_id, result)
                                
                        except Exception as e:
                            self.logger.error(f"Job {job_id} failed: {e}")
                            await self._redis.hset(
                                f"{self.CHANNEL_PREFIX}data:{job_id}",
                                mapping={
                                    "status": "failed",
                                    "error": str(e),
                                    "failed_at": datetime.now().isoformat()
                                }
                            )
                else:
                    # No hay jobs, esperar
                    await asyncio.sleep(0.1)
        
        # También escuchar pubsub para wakeup inmediato
        asyncio.create_task(process_queue())
    
    async def _notify_callback(
        self, 
        callback_url: str, 
        job_id: str, 
        result: Any
    ):
        """Notifica resultado via webhook."""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    callback_url,
                    json={
                        "job_id": job_id,
                        "status": "completed",
                        "result": result
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status >= 400:
                        self.logger.warning(
                            f"Callback to {callback_url} returned {resp.status}"
                        )
        except Exception as e:
            self.logger.error(f"Failed to notify callback: {e}")