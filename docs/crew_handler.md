"""
AgentCrew REST API Documentation
=================================

Complete API documentation for managing and executing agent crews.

## Overview

The AgentCrew REST API provides endpoints for creating, managing, and executing
multi-agent workflows with support for three execution modes:

- **Sequential**: Agents execute one after another in a pipeline
- **Parallel**: All agents execute simultaneously
- **Flow**: DAG-based execution with dependencies and automatic parallelization

## Base URL

```
/api/v1/crew
```

## Endpoints

### 1. CREATE CREW (PUT)

Create a new agent crew with configuration.

**Endpoint:** `PUT /api/v1/crew`

**Request Body:**
```json
{
  "name": "research_crew",
  "description": "A crew for conducting research",
  "execution_mode": "sequential",  // or "parallel", "flow"
  "agents": [
    {
      "agent_id": "researcher",
      "agent_class": "BaseAgent",
      "name": "Research Agent",
      "config": {
        "model": "gpt-4",
        "temperature": 0.7,
        "max_tokens": 2000
      },
      "tools": ["web_search", "calculator"],
      "system_prompt": "You are an expert researcher focused on AI and ML topics."
    },
    {
      "agent_id": "writer",
      "agent_class": "BaseAgent",
      "name": "Writer Agent",
      "config": {
        "model": "gpt-4",
        "temperature": 0.8
      },
      "tools": ["grammar_check"],
      "system_prompt": "You are a skilled technical writer."
    }
  ],
  "flow_relations": [  // Only used in "flow" mode
    {
      "source": "researcher",
      "target": ["writer", "editor"]
    },
    {
      "source": ["writer", "editor"],
      "target": "reviewer"
    }
  ],
  "shared_tools": ["database"],
  "max_parallel_tasks": 10,
  "metadata": {
    "created_by": "user123",
    "project": "ai_research"
  }
}
```

**Response (201 Created):**
```json
{
  "message": "Crew created successfully",
  "crew_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "research_crew",
  "execution_mode": "sequential",
  "agents": ["researcher", "writer"],
  "created_at": "2025-01-15T10:30:00Z"
}
```

**Error Responses:**
- `400 Bad Request`: Invalid request format or missing required fields
- `500 Internal Server Error`: Server error during crew creation

---

### 2. GET CREW (GET)

Retrieve crew information or list all crews.

**Endpoint:** `GET /api/v1/crew`

**Query Parameters:**
- `name` (optional): Crew name to retrieve specific crew
- `crew_id` (optional): Crew ID to retrieve specific crew

**Example 1: Get specific crew**
```bash
GET /api/v1/crew?name=research_crew
```

**Response (200 OK):**
```json
{
  "crew_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "research_crew",
  "description": "A crew for conducting research",
  "execution_mode": "sequential",
  "agents": [
    {
      "agent_id": "researcher",
      "agent_class": "BaseAgent",
      "name": "Research Agent",
      "config": {"model": "gpt-4", "temperature": 0.7},
      "tools": ["web_search", "calculator"],
      "system_prompt": "You are an expert researcher..."
    }
  ],
  "flow_relations": [],
  "shared_tools": ["database"],
  "max_parallel_tasks": 10,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z",
  "metadata": {"created_by": "user123"}
}
```

**Example 2: List all crews**
```bash
GET /api/v1/crew
```

**Response (200 OK):**
```json
{
  "crews": [
    {
      "crew_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "research_crew",
      "description": "A crew for conducting research",
      "execution_mode": "sequential",
      "agent_count": 2,
      "created_at": "2025-01-15T10:30:00Z"
    },
    {
      "crew_id": "660e9511-f30c-52e5-b827-557766551111",
      "name": "analysis_crew",
      "description": "Data analysis crew",
      "execution_mode": "parallel",
      "agent_count": 4,
      "created_at": "2025-01-16T14:20:00Z"
    }
  ],
  "total": 2
}
```

**Error Responses:**
- `404 Not Found`: Crew not found
- `500 Internal Server Error`: Server error

---

### 3. EXECUTE CREW (POST)

Execute a crew asynchronously and get a job ID for tracking.

**Endpoint:** `POST /api/v1/crew/execute`

**Request Body:**

```json
{
  "crew_id": "550e8400-e29b-41d4-a716-446655440000",
  // or "name": "research_crew",
  "query": "What are the latest developments in Large Language Models?",
  // For parallel mode with specific agent tasks:
  // "query": {
  //   "researcher": "Research LLMs",
  //   "writer": "Write a summary"
  // },
  "user_id": "user123",
  "session_id": "session456",
  "synthesis_prompt": "Provide a comprehensive synthesis of all findings",
  "kwargs": {
    "max_iterations": 100,
    "temperature": 0.7
  }
}
```

**Response (202 Accepted):**
```json
{
  "job_id": "770f0622-g41d-63f6-c938-668877662222",
  "crew_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Crew execution started",
  "created_at": "2025-01-15T11:00:00Z"
}
```

**Error Responses:**
- `400 Bad Request`: Invalid request or missing required fields
- `404 Not Found`: Crew not found
- `500 Internal Server Error`: Server error

---

### 4. GET JOB STATUS (PATCH)

Check the status and retrieve results of an asynchronous crew execution.

**Endpoint:** `PATCH /api/v1/crew/job`

**Query Parameters:**
- `job_id` (required): Job identifier returned from POST

**Example:**
```bash
PATCH /api/v1/crew/job?job_id=770f0622-g41d-63f6-c938-668877662222
```

**Response (200 OK) - Job Running:**
```json
{
  "job_id": "770f0622-g41d-63f6-c938-668877662222",
  "crew_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "elapsed_time": 15.3,
  "created_at": "2025-01-15T11:00:00Z",
  "started_at": "2025-01-15T11:00:02Z",
  "metadata": {}
}
```

**Response (200 OK) - Job Completed:**
```json
{
  "job_id": "770f0622-g41d-63f6-c938-668877662222",
  "crew_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "elapsed_time": 45.7,
  "created_at": "2025-01-15T11:00:00Z",
  "completed_at": "2025-01-15T11:00:45Z",
  "result": {
    "output": "Here is a comprehensive analysis of LLMs...",
    "results": [
      "Research findings from agent 1...",
      "Written summary from agent 2..."
    ],
    "agent_ids": ["researcher", "writer"],
    "agents": [
      {
        "agent_id": "researcher",
        "agent_name": "Research Agent",
        "llm_provider": "openai",
        "model": "gpt-4",
        "execution_time": 23.4,
        "status": "completed",
        "tool_calls": [...]
      }
    ],
    "execution_log": [...],
    "total_time": 45.7,
    "status": "completed",
    "errors": {},
    "metadata": {"mode": "sequential"}
  },
  "metadata": {}
}
```

**Response (200 OK) - Job Failed:**
```json
{
  "job_id": "770f0622-g41d-63f6-c938-668877662222",
  "crew_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error": "Agent execution failed: API rate limit exceeded",
  "elapsed_time": 10.2,
  "created_at": "2025-01-15T11:00:00Z",
  "completed_at": "2025-01-15T11:00:10Z",
  "metadata": {}
}
```

**Error Responses:**
- `400 Bad Request`: Missing job_id parameter
- `404 Not Found`: Job not found
- `500 Internal Server Error`: Server error

---

### 5. DELETE CREW (DELETE)

Remove a crew from the system.

**Endpoint:** `DELETE /api/v1/crew`

**Query Parameters:**
- `name` (optional): Crew name
- `crew_id` (optional): Crew ID

**Example:**
```bash
DELETE /api/v1/crew?name=research_crew
```

**Response (200 OK):**
```json
{
  "message": "Crew 'research_crew' deleted successfully"
}
```

**Error Responses:**
- `400 Bad Request`: Missing name or crew_id
- `404 Not Found`: Crew not found
- `500 Internal Server Error`: Server error

---

## Execution Modes

### Sequential Mode

Agents execute in order, each receiving the output of the previous agent.

```json
{
  "execution_mode": "sequential",
  "agents": [
    {"agent_id": "researcher", ...},
    {"agent_id": "writer", ...},
    {"agent_id": "editor", ...}
  ]
}
```

**Flow:** researcher → writer → editor

### Parallel Mode

All agents execute simultaneously on independent tasks.

```json
{
  "execution_mode": "parallel",
  "agents": [
    {"agent_id": "researcher1", ...},
    {"agent_id": "researcher2", ...},
    {"agent_id": "researcher3", ...}
  ]
}
```

**Flow:** researcher1 || researcher2 || researcher3 (simultaneous)

### Flow Mode

Agents execute based on a dependency graph (DAG).

```json
{
  "execution_mode": "flow",
  "agents": [
    {"agent_id": "researcher", ...},
    {"agent_id": "analyst1", ...},
    {"agent_id": "analyst2", ...},
    {"agent_id": "synthesizer", ...}
  ],
  "flow_relations": [
    {"source": "researcher", "target": ["analyst1", "analyst2"]},
    {"source": ["analyst1", "analyst2"], "target": "synthesizer"}
  ]
}
```

**Flow:**
```
researcher
    ├─→ analyst1 ─┐
    └─→ analyst2 ─┴─→ synthesizer
```

---

## Python Client Example

```python
import aiohttp
import asyncio
import json

class CrewAPIClient:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.api_path = f"{base_url}/api/v1/crew"

    async def create_crew(self, crew_definition: dict) -> dict:
        """Create a new crew."""
        async with aiohttp.ClientSession() as session:
            async with session.put(
                self.api_path,
                json=crew_definition
            ) as response:
                return await response.json()

    async def execute_crew(
        self,
        crew_id: str,
        query: str,
        **kwargs
    ) -> dict:
        """Execute a crew and get job ID."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_path}/execute",
                json={
                    "crew_id": crew_id,
                    "query": query,
                    **kwargs
                }
            ) as response:
                return await response.json()

    async def get_job_status(self, job_id: str) -> dict:
        """Get job status and results."""
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                f"{self.api_path}/job",
                params={"job_id": job_id}
            ) as response:
                return await response.json()

    async def wait_for_completion(
        self,
        job_id: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0
    ) -> dict:
        """Wait for job completion with polling."""
        start_time = asyncio.get_event_loop().time()

        while True:
            status = await self.get_job_status(job_id)

            if status["status"] in ["completed", "failed", "cancelled"]:
                return status

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"Job {job_id} did not complete within {timeout}s"
                )

            await asyncio.sleep(poll_interval)


# Usage Example
async def main():
    client = CrewAPIClient("http://localhost:8080")

    # 1. Create a crew
    crew_def = {
        "name": "research_crew",
        "execution_mode": "sequential",
        "agents": [
            {
                "agent_id": "researcher",
                "agent_class": "BaseAgent",
                "name": "Research Agent",
                "config": {"model": "gpt-4", "temperature": 0.7},
                "system_prompt": "You are a research expert."
            },
            {
                "agent_id": "writer",
                "agent_class": "BaseAgent",
                "name": "Writer Agent",
                "config": {"model": "gpt-4", "temperature": 0.8},
                "system_prompt": "You are a technical writer."
            }
        ]
    }

    crew_response = await client.create_crew(crew_def)
    print(f"Created crew: {crew_response['crew_id']}")

    # 2. Execute crew
    job_response = await client.execute_crew(
        crew_id=crew_response['crew_id'],
        query="What are the latest trends in AI?"
    )
    print(f"Job started: {job_response['job_id']}")

    # 3. Wait for completion
    result = await client.wait_for_completion(job_response['job_id'])

    if result['status'] == 'completed':
        print("Job completed!")
        print("Result:", result['result']['output'])
    else:
        print(f"Job failed: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## cURL Examples

### Create Crew
```bash
curl -X PUT http://localhost:8080/api/v1/crew \
  -H "Content-Type: application/json" \
  -d '{
    "name": "research_crew",
    "execution_mode": "sequential",
    "agents": [
      {
        "agent_id": "researcher",
        "agent_class": "BaseAgent",
        "config": {"model": "gpt-4"}
      }
    ]
  }'
```

### Execute Crew
```bash
curl -X POST http://localhost:8080/api/v1/crew/execute \
  -H "Content-Type: application/json" \
  -d '{
    "crew_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "Research AI trends"
  }'
```

### Check Job Status
```bash
curl -X PATCH "http://localhost:8080/api/v1/crew/job?job_id=770f0622-g41d-63f6-c938-668877662222"
```

### List Crews
```bash
curl -X GET http://localhost:8080/api/v1/crew
```

### Delete Crew
```bash
curl -X DELETE "http://localhost:8080/api/v1/crew?name=research_crew"
```

---

## Error Handling

All endpoints return consistent error responses:

```json
{
  "error": "Error message description",
  "status": 400
}
```

Common HTTP status codes:
- `200 OK`: Request successful
- `201 Created`: Resource created successfully
- `202 Accepted`: Request accepted for processing
- `400 Bad Request`: Invalid request format
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error

---

## Best Practices

1. **Crew Design**
   - Keep agent responsibilities focused and clear
   - Use appropriate execution mode for your use case
   - Define clear flow dependencies in flow mode

2. **Job Management**
   - Poll job status at reasonable intervals (2-5 seconds)
   - Implement timeout handling for long-running jobs
   - Store job IDs for result retrieval

3. **Error Handling**
   - Always check job status for failures
   - Implement retry logic for transient failures
   - Log execution_log for debugging

4. **Performance**
   - Use parallel mode for independent tasks
   - Optimize max_parallel_tasks based on resources
   - Monitor elapsed_time in job responses

---

## Integration with BotManager

```python
from parrot.manager import BotManager
from parrot.handlers.crew_handler import CrewHandler
from parrot.handlers.job_manager import JobManager

# Setup BotManager with crew support
async def setup_app():
    manager = BotManager()

    # Initialize job manager
    job_manager = JobManager(
        cleanup_interval=3600,
        job_ttl=86400
    )
    await job_manager.start()

    # Add to app
    app = web.Application()
    app['bot_manager'] = manager
    app['job_manager'] = job_manager

    # Register handler
    app.router.add_view('/api/v1/crew', CrewHandler)

    return app
```
