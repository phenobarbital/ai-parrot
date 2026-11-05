# Deploy Your Agent

> **Time**: ~15 minutes
> **Prerequisites**: AI-Parrot installed, API key configured, agent code ready

## What You'll Build

A production-ready aiohttp service that serves your agent over HTTP. The service will:
- Accept requests via HTTP POST
- Run with production configuration (workers, logging, health checks)
- Be served under the `/ai-parrot/` project prefix

In this tutorial, you'll learn how to:
- Create an aiohttp web application that serves your agent
- Handle JSON requests and responses
- Configure gunicorn for production deployment
- Add health checks and error handling
- Use environment variables for configuration
- Deploy your agent as a production service

By the end of this tutorial, you'll have a running HTTP service that can answer questions using your agent, ready to be deployed to a production environment.

## Step 1: Set Up the Service

Create a new file called `agent_server.py` in your project directory. This file will contain the HTTP server that serves your agent.

```bash
touch agent_server.py
```

Now open `agent_server.py` in your editor and add the following code:

```python
import asyncio
from aiohttp import web
from parrot.bots import Agent
from parrot.clients.anthropic import AnthropicClient

# Create your agent
agent = Agent(
    name="ProductionAgent",
    llm="anthropic",
    from_database=False
)

async def handle_request(request: web.Request) -> web.Response:
    """Handle incoming HTTP requests."""
    try:
        # Get the question from the request body
        data = await request.json()
        question = data.get("question", "")

        if not question:
            return web.json_response(
                {"error": "Missing 'question' field in request body"},
                status=400
            )

        # Invoke the agent
        response = await agent.invoke(question)

        return web.json_response({
            "answer": response.output,
            "model": response.model
        })

    except Exception as e:
        return web.json_response(
            {"error": str(e)},
            status=500
        )

async def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    app.router.add_post("/ask", handle_request)
    return app

if __name__ == "__main__":
    # Run the server with production configuration
    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=8000,
        access_log=None,  # Disable access logging in production
        print=None
    )
```

This code creates an aiohttp web application that:
- Exposes a POST endpoint at `/ask` that accepts JSON requests
- Extracts the `question` field from the request body
- Invokes the agent with the question
- Returns a JSON response with the answer and model information
- Handles errors gracefully with appropriate HTTP status codes

## Step 2: Configure Production Settings

For production, you should use gunicorn with multiple workers. Gunicorn is a production-grade WSGI HTTP server that can handle multiple worker processes, making your service more scalable and resilient.

Create a `gunicorn_config.py` file in your project directory:

```bash
touch gunicorn_config.py
```

Now open `gunicorn_config.py` and add the following configuration:

```python
# gunicorn_config.py

# Number of workers (typically 2-4x CPU cores)
workers = 4

# Worker class (async for aiohttp)
worker_class = "aiohttp.GunicornWebWorker"

# Timeout for worker processes (in seconds)
timeout = 120

# Keep-alive connections
keepalive = 5

# Bind to all interfaces on port 8000
bind = "0.0.0.0:8000"

# Disable access logging
accesslog = None

# Error logging
errorlog = "-"

# Log level
loglevel = "info"

# Preload application
preload_app = True
```

**Key configuration options:**
- `workers`: Number of worker processes. Each worker can handle one request at a time, so more workers = more concurrent requests.
- `worker_class`: The worker class. For aiohttp, use `aiohttp.GunicornWebWorker`.
- `timeout`: Maximum time a worker can spend processing a request. Set this higher than your LLM's typical response time.
- `keepalive`: Number of seconds to keep connections open. Reduces connection overhead for repeated requests.
- `preload_app`: Load the application code once and share it across workers. This reduces memory usage and startup time.
- `accesslog` and `errorlog`: Where to write logs. Use `-` for stdout/stderr.

## Step 3: Run with Gunicorn

Start the server with gunicorn:

```bash
gunicorn -c gunicorn_config.py agent_server:app
```

This will start 4 worker processes, each running the aiohttp server. The `preload_app=True` flag loads the application code once and shares it across workers, reducing memory usage.

You should see output like:

```
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:8000 (4)
[INFO] Using worker: aiohttp.GunicornWebWorker
[INFO] Booting worker with pid: 12345
[INFO] Booting worker with pid: 12346
[INFO] Booting worker with pid: 12347
[INFO] Booting worker with pid: 12348
```

Each line shows a worker process starting. The workers are now ready to handle requests.

## Step 4: Test the Service

Make a request to your deployed agent:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the capital of France?"}'
```

You should receive a JSON response like:

```json
{
  "answer": "Paris",
  "model": "claude-3-5-sonnet-20241022"
}
```

**What just happened?**
1. The client sent a POST request to `/ask` with a JSON body containing the question
2. Gunicorn routed the request to one of the 4 worker processes
3. The worker called `handle_request`, which invoked the agent
4. The agent used the LLM to process the question
5. The response was formatted as JSON and returned to the client

You can test with multiple requests to see how gunicorn distributes them across workers.

## Step 5: Deploy to Production

For a real deployment, you'll want to:

1. **Use a reverse proxy** (nginx, Caddy) in front of gunicorn
   - Handle SSL/TLS termination
   - Serve static files
   - Add rate limiting
   - Add caching for repeated requests

2. **Use environment variables** for configuration
   ```python
   import os
   from dotenv import load_dotenv

   load_dotenv()

   agent = Agent(
       name="ProductionAgent",
       llm=os.getenv("LLM_PROVIDER", "anthropic"),
       from_database=False
   )
   ```

3. **Add health checks**
   ```python
   async def health_check(request: web.Request) -> web.Response:
       return web.json_response({"status": "healthy"})

   app.router.add_get("/health", health_check)
   ```

4. **Use a process manager** (systemd, supervisord) to keep the service running
   - Auto-restart on failure
   - Log rotation
   - Graceful shutdown

5. **Monitor and scale**
   - Set up metrics (Prometheus, Grafana)
   - Configure auto-scaling based on load
   - Set up alerts for failures and slow responses

## What's Next

- [Your First Chatbot](first-chatbot.md) — Learn how to create a chatbot instead of an agent
- [Wiki: Server & APIs](https://github.com/phenobarbital/ai-parrot/wiki/Home) — Deep dive into HTTP servers and API design
- [Wiki: Integrations](https://github.com/phenobarbital/ai-parrot/wiki/Home) — Learn about integrations with other systems
