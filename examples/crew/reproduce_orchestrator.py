import asyncio
import logging
import sys
import os

# Ensure we can import parrot
sys.path.append(os.getcwd())

from parrot.bots.orchestration.agent import OrchestratorAgent
from parrot.bots.agent import BasicAgent

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    print("--- Starting OrchestratorAgent Evaluation ---")

    # 1. Create OrchestratorAgent
    print("Creating OrchestratorAgent...")
    orchestrator = OrchestratorAgent(
        name="MainOrchestrator",
        model="gemini-2.5-flash" # explicit model to be sure
    )

    # 2. Create 3 specialized agents
    print("Creating specialized agents...")
    
    math_agent = BasicAgent(
        name="MathAgent",
        system_prompt="You are a helpful math assistant. Solve problems concisely.",
        model="gemini-2.5-flash"
    )
    
    poetry_agent = BasicAgent(
        name="PoetryAgent",
        system_prompt="You are a creative poet. Write poems when asked.",
        model="gemini-2.5-flash"
    )
    
    history_agent = BasicAgent(
        name="HistoryAgent",
        system_prompt="You are a historian. Answer history questions accurately.",
        model="gemini-2.5-flash"
    )

    # Orchestrator also needs it? No, if fixed in class.

    # 3. Add agents to orchestrator
    print("Adding agents to orchestrator...")
    orchestrator.add_agent(math_agent, description="Useful for solving math problems.")
    orchestrator.add_agent(poetry_agent, description="Useful for writing poetry and creative writing.")
    orchestrator.add_agent(history_agent, description="Useful for answering history questions.")

    # 4. Do questions related to each agent
    questions = [
        ("Math", "What is the square root of 144 plus 10?"),
        ("Poetry", "Write a short haiku about a red fox."),
        ("History", "In what year did the French Revolution start?"),
        ("General", "Hello, who are you and what can you do?")
    ]

    results = []

    for category, question in questions:
        print(f"\n--- Asking {category} Question: '{question}' ---")
        try:
            # We use invoke or conversation. BasicAgent uses conversation by default usually.
            # OrchestratorAgent inherits BasicAgent.
            response = await orchestrator.conversation(question)
            print(f"Response: {response.output}")
            results.append({
                "category": category,
                "question": question,
                "response": response.output,
                "tool_usage": orchestrator.get_orchestration_stats()
            })
        except Exception as e:
            logger.error(f"Error asking question '{question}': {e}")
            results.append({
                "category": category,
                "question": question,
                "error": str(e)
            })

    # 5. Return summary log of findings
    print("\n--- Summary Log ---")
    stats = orchestrator.get_orchestration_stats()
    print("Orchestration Statistics:", stats)
    
    for res in results:
        print(f"\nCategory: {res.get('category')}")
        print(f"Question: {res.get('question')}")
        if 'error' in res:
            print(f"Error: {res.get('error')}")
        else:
            print(f"Response Length: {len(res.get('response'))} chars")
            # We can't easily see exactly which tool was called from the response object wrapper 
            # unless we inspect the inner steps, but stats should show usage.

if __name__ == "__main__":
    asyncio.run(main())
