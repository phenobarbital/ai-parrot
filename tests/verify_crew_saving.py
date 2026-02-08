
import asyncio
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append('/home/jesuslara/proyectos/ai-parrot')

# Do NOT import AgentCrew here to allow fresh import in test

class TestCrewSaving(unittest.IsolatedAsyncioTestCase):
    async def test_save_crew_result_called(self):
        """Verify that _save_crew_result is called during execution."""
        
        # 1. Force unload of crew module to ensure clean import with patched dependencies
        if 'parrot.bots.orchestration.crew' in sys.modules:
            del sys.modules['parrot.bots.orchestration.crew']
        if 'parrot.bots.orchestration' in sys.modules:
             del sys.modules['parrot.bots.orchestration']

        # 2. Patch the SOURCE of DocumentDb
        with patch('parrot.interfaces.documentdb.DocumentDb') as mock_db_cls:
            mock_db = MagicMock()
            mock_db.__aenter__.return_value = mock_db
            # Make db.write return an awaitable
            write_future = asyncio.Future()
            write_future.set_result(None)
            mock_db.write.return_value = write_future
            mock_db_cls.return_value = mock_db

            # 3. Import AgentCrew inside the patch context
            from parrot.bots.orchestration.crew import AgentCrew
            # Also import CrewResult here to avoid early import
            from parrot.models.crew import CrewResult

            # Mock LLM and Agents
            mock_llm = MagicMock()
            mock_llm.ask = MagicMock()
            future = asyncio.Future()
            future.set_result(MagicMock(content="Synthesized result"))
            mock_llm.ask.return_value = future

            mock_agent = MagicMock()
            mock_agent.name = "TestAgent"
            
            # Setup Crew
            crew = AgentCrew(agents=[mock_agent], llm=mock_llm)
            crew.name = "TestCrew"
            
            # Spy on _save_crew_result
            original_save = crew._save_crew_result
            save_finished = asyncio.Event()
            
            async def side_effect(*args, **kwargs):
                print(f"DEBUG: _save_crew_result called")
                try:
                    await original_save(*args, **kwargs)
                except Exception as e:
                    print(f"DEBUG: Error in save: {e}")
                finally:
                    save_finished.set()
                
            crew._save_crew_result = side_effect

            # Test run_parallel
            print("Running crew.run_parallel...")
            tasks = [{'agent_id': 'agent_1', 'query': 'test'}]
            
            async def mock_execute(*args, **kwargs):
                return "Agent output"
            crew._execute_agent = mock_execute
            
            crew.agents = {'agent_1': mock_agent}

            result = await crew.run_parallel(tasks=tasks, generate_summary=True)
            
            print("Wait for save task...")
            try:
                await asyncio.wait_for(save_finished.wait(), timeout=2.0)
                print("Save task completed!")
            except asyncio.TimeoutError:
                self.fail("Timed out waiting for _save_crew_result to complete")

            # Verify DocumentDb interaction
            mock_db_cls.assert_called()

if __name__ == '__main__':
    unittest.main()
