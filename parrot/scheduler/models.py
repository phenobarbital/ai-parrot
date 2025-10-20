from typing import Any, Dict, Optional, Callable, List
from datetime import datetime
import uuid
from asyncdb.models import Model, Field


class AgentSchedule(Model):
    """
    Database model for storing agent schedules.

    SQL Table Creation:
    CREATE TABLE IF NOT EXISTS navigator.agents_scheduler (
        schedule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        agent_id VARCHAR NOT NULL,
        agent_name VARCHAR NOT NULL,
        prompt TEXT,
        method_name VARCHAR,
        schedule_type VARCHAR NOT NULL,
        schedule_config JSONB NOT NULL,
        enabled BOOLEAN DEFAULT TRUE,
        created_by INTEGER,
        created_email VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        last_run TIMESTAMP WITH TIME ZONE,
        next_run TIMESTAMP WITH TIME ZONE,
        run_count INTEGER DEFAULT 0,
        metadata JSONB DEFAULT '{}'::JSONB,
        is_crew BOOLEAN DEFAULT FALSE,
        send_result JSONB DEFAULT '{}'::JSONB
    );

    CREATE INDEX idx_agents_scheduler_enabled ON navigator.agents_scheduler(enabled);
    CREATE INDEX idx_agents_scheduler_agent ON navigator.agents_scheduler(agent_name);
    """
    schedule_id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    agent_id: str = Field(required=True)
    agent_name: str = Field(required=True)
    prompt: Optional[str] = Field(required=False)
    method_name: Optional[str] = Field(required=False)
    schedule_type: str = Field(required=True)
    schedule_config: dict = Field(required=True, default_factory=dict)
    enabled: bool = Field(required=False, default=True)
    created_by: Optional[int] = Field(required=False)
    created_email: Optional[str] = Field(required=False)
    created_at: datetime = Field(required=False, default_factory=datetime.now)
    updated_at: datetime = Field(required=False, default_factory=datetime.now)
    last_run: Optional[datetime] = Field(required=False)
    next_run: Optional[datetime] = Field(required=False)
    run_count: int = Field(required=False, default=0)
    metadata: dict = Field(required=False, default_factory=dict)
    is_crew: bool = Field(required=False, default=False)
    send_result: dict = Field(required=False, default_factory=dict)

    class Meta:
        driver = 'pg'
        name = "agents_scheduler"
        schema = "navigator"
        strict = True
        frozen = False
