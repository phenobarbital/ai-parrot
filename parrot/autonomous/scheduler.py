# parrot/autonomy/scheduler.py
from enum import Enum
from typing import Optional, Dict, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore


class TriggerMode(Enum):
    """Cómo se dispara la ejecución de un agente."""
    SCHEDULED = "scheduled"      # APScheduler (cron, interval)
    EVENT = "event"              # Event bus (pub/sub)
    WEBHOOK = "webhook"          # HTTP webhook externo
    REACTIVE = "reactive"        # Reacción a output de otro agente
    MANUAL = "manual"            # Solo ejecución explícita


@dataclass
class AgentTriggerConfig:
    """Configuración de trigger para un agente autónomo."""
    mode: TriggerMode
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Para SCHEDULED
    schedule_type: Optional[str] = None  # cron, interval, once
    schedule_params: Dict[str, Any] = field(default_factory=dict)
    
    # Para EVENT
    event_patterns: list[str] = field(default_factory=list)  # ["order.created", "user.*"]
    
    # Para WEBHOOK  
    webhook_path: Optional[str] = None
    webhook_secret: Optional[str] = None
    
    # Para REACTIVE
    depends_on_agents: list[str] = field(default_factory=list)
    condition: Optional[Callable] = None  # fn(result) -> bool


@dataclass
class AutonomousJob:
    """Representa un job autónomo en cualquier modo."""
    job_id: str
    agent_name: str
    crew_name: Optional[str] = None
    trigger_config: AgentTriggerConfig = None
    prompt_template: Optional[str] = None
    context_builder: Optional[Callable] = None
    success_callback: Optional[Callable] = None
    error_callback: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Tracking
    created_at: datetime = field(default_factory=datetime.now)
    last_run: Optional[datetime] = None
    run_count: int = 0
    last_result: Optional[Any] = None
    last_error: Optional[str] = None