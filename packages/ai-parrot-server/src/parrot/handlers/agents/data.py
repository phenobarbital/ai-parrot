import uuid
from aiohttp import web
from navigator.views import BaseView
from navigator.responses import JSONResponse
from navconfig.logging import logging

from parrot.bots.data import PandasAgent
from parrot.registry import agent_registry
from parrot.utils.paths import validate_path_segment

class DataAnalystHandler(BaseView):
    """
    Handler for creating in-memory empty PandasAgent instances.
    
    This handles spinning up instances of empty PandasAgents which are 
    used for in-session data analysis (Dataframes can be appended later).
    These agents are intentionally ephemeral and not persistent unless specified.
    """
    async def post(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        name = payload.get("name", "In-Memory Data Analyst")
        agent_id = payload.get("agent_id") or str(uuid.uuid4())
        chatbot_id = payload.get("chatbot_id") or str(uuid.uuid4())

        # ``agent_id`` becomes an on-disk path component (STATIC_DIR/<agent_id>/…),
        # so an unsafe value is a path-traversal vector (CWE-22). Reject it here
        # with a 400 instead of letting it fail deeper as a 500.
        try:
            validate_path_segment(agent_id, name="agent_id")
        except ValueError as exc:
            return JSONResponse(
                {"status": "error", "message": str(exc)},
                status=400
            )
        agent_name = payload.get("agent_name", name)
        
        # Accept LLM config to be similar to other agent creations:
        use_llm = payload.get("use_llm", "google")
        llm = payload.get("llm", None)
        system_prompt = payload.get("system_prompt", None)
        instructions = payload.get("instructions", "Analyze the provided datasets.")

        # Create the agent instance
        try:
            agent = PandasAgent(
                name=name,
                agent_id=agent_id,
                chatbot_id=chatbot_id,
                agent_name=agent_name,
                use_llm=use_llm,
                llm=llm,
                system_prompt=system_prompt,
                instructions=instructions,
                dataframes={}  # Explicitly empty dict
            )
            
            # Optionally configure instance logic and AI clients:
            if hasattr(agent, 'configure'):
                await agent.configure(request.app)
            
            bot_manager = request.app.get('bot_manager')
            if bot_manager:
                bot_manager.add_agent(agent)
                
            agent_registry.register_instance(
                name=chatbot_id,
                instance=agent,
                replace=True
            )

            return JSONResponse({
                "status": "success",
                "message": "Empty PandasAgent created successfully",
                "chatbot_id": chatbot_id,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "llm": llm,
                "use_llm": use_llm
            })
            
        except Exception as e:
            logging.error(f"Failed to create PandasAgent: {e}", exc_info=True)
            return JSONResponse({
                "status": "error",
                "message": f"Failed to instantiate agent: {str(e)}"
            }, status=500)
