# example_autonomy.py
import asyncio
from aiohttp import web

from parrot.autonomy import AutonomyOrchestrator
from parrot.registry import AgentRegistry
from parrot.bots import Agent


async def main():
    # 1. Crear agentes
    order_processor = Agent(
        name="OrderProcessor",
        llm="anthropic:claude-sonnet-4-20250514",
        system_prompt="Process incoming orders and extract key information."
    )
    
    notification_agent = Agent(
        name="NotificationAgent", 
        llm="openai:gpt-4o-mini",
        system_prompt="Send notifications based on processed orders."
    )
    
    # 2. Registrar agentes
    registry = AgentRegistry()
    registry.register(order_processor)
    registry.register(notification_agent)
    
    # 3. Crear orquestador
    orchestrator = AutonomyOrchestrator(
        redis_url="redis://localhost:6379",
        use_event_bus=True,
        use_webhooks=True,
        agent_registry=registry
    )
    
    await orchestrator.start()
    
    # 4. Configurar webhooks
    orchestrator.register_webhook(
        path="/shopify/orders",
        agent_name="OrderProcessor",
        secret="whsec_xxx",
        transform_fn=lambda p: f"New order: {p.get('order_id')} - {p.get('items')}"
    )
    
    orchestrator.register_webhook(
        path="/github/push",
        agent_name="CodeReviewer",
        secret="ghsec_xxx"
    )
    
    # 5. Configurar eventos reactivos
    @orchestrator.event_bus.on("agent.completed")
    async def chain_notification(event):
        if event.payload.get("agent_name") == "OrderProcessor":
            # Cuando OrderProcessor completa, disparar NotificationAgent
            await orchestrator.trigger_agent(
                "NotificationAgent",
                f"Send notification for: {event.payload.get('result')}"
            )
    
    # 6. Setup web app
    app = web.Application()
    orchestrator.setup_routes(app)
    
    # 7. Run
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8080)
    await site.start()
    
    print("Autonomy server running on http://localhost:8080")
    print("Webhooks available at /webhooks/*")
    
    # Keep running
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())