---
type: Wiki Entity
title: AgentSchedule
id: class:parrot.scheduler.models.AgentSchedule
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Database model for storing agent schedules.
---

# AgentSchedule

Defined in [`parrot.scheduler.models`](../summaries/mod:parrot.scheduler.models.md).

```python
class AgentSchedule(Model)
```

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
    send_result JSONB DEFAULT '{}'::JSONB,
    scheduler_type VARCHAR DEFAULT 'default',
    callbacks JSONB DEFAULT '[]'::JSONB
);

CREATE INDEX idx_agents_scheduler_enabled ON navigator.agents_scheduler(enabled);
CREATE INDEX idx_agents_scheduler_agent ON navigator.agents_scheduler(agent_name);
