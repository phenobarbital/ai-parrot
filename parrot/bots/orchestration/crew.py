"""
Enhanced Agent Crew with Parallel and Sequential Execution
"""
from __future__ import annotations
from typing import List, Dict, Any, Union, Optional, Literal
import asyncio
import uuid
from dataclasses import dataclass, field
from navconfig.logging import logging
from ..agent import BasicAgent
from ..abstract import AbstractBot
from ...clients.base import AbstractClient
from ...tools.manager import ToolManager
from ...tools.abstract import AbstractTool
from ...tools.agent import AgentContext
from ...models.responses import (
    AIMessage,
    AgentResponse
)


@dataclass
class CrewTask:
    """Represents a task to be executed by an agent in the crew."""
    task_id: str
    agent_name: str
    query: str
    dependencies: List[str] = field(default_factory=list)  # IDs of tasks this depends on
    context: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    status: Literal["pending", "running", "completed", "failed"] = "pending"


class AgentCrew:
    """
    Crew that supports both sequential and parallel execution.

    Features:
    - Sequential execution (pipeline pattern)
    - Parallel execution using asyncio.gather()
    - Task dependencies and DAG execution
    - Shared tool manager across agents
    - Comprehensive execution logging
    """

    def __init__(
        self,
        name: str = "AgentCrew",
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None,
        max_parallel_tasks: int = 10,
        llm: Optional[AbstractClient] = None
    ):
        """
        Initialize the AgentCrew.

        Args:
            name: Name of the crew
            agents: List of agents to add to the crew
            shared_tool_manager: Optional shared tool manager for all agents
            max_parallel_tasks: Maximum number of parallel tasks (for rate limiting)
        """
        self.name = name
        self.agents: Dict[str, Union[BasicAgent, AbstractBot]] = {}
        self.shared_tool_manager = shared_tool_manager or ToolManager()
        self.max_parallel_tasks = max_parallel_tasks
        self.execution_log: List[Dict[str, Any]] = []
        self.logger = logging.getLogger(f"parrot.crews.{self.name}")
        self.semaphore = asyncio.Semaphore(max_parallel_tasks)
        self._llm = llm  # Optional LLM for orchestration tasks

        # Add agents if provided
        if agents:
            for agent in agents:
                self.add_agent(agent)

    def add_agent(self, agent: Union[BasicAgent, AbstractBot], agent_id: str = None) -> None:
        """Add an agent to the crew."""
        agent_id = agent_id or agent.name
        self.agents[agent_id] = agent

        # Share tools with new agent
        if self.shared_tool_manager:
            for tool_name in self.shared_tool_manager.list_tools():
                tool = self.shared_tool_manager.get_tool(tool_name)
                if tool and not agent.tool_manager.get_tool(tool_name):
                    agent.tool_manager.add_tool(tool, tool_name)

        self.logger.info(f"Added agent '{agent_id}' to crew")

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent from the crew."""
        if agent_id in self.agents:
            del self.agents[agent_id]
            self.logger.info(f"Removed agent '{agent_id}' from crew")
            return True
        return False

    def add_shared_tool(self, tool: AbstractTool, tool_name: str = None) -> None:
        """Add a tool shared across all agents."""
        self.shared_tool_manager.add_tool(tool, tool_name)

        # Add to all existing agents
        for agent in self.agents.values():
            if not agent.tool_manager.get_tool(tool_name or tool.name):
                agent.tool_manager.add_tool(tool, tool_name)

    async def execute_sequential(
        self,
        initial_query: str,
        agent_sequence: List[str] = None,
        user_id: str = None,
        session_id: str = None,
        pass_full_context: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute agents in sequence (pipeline pattern).

        Args:
            initial_query: Initial query
            agent_sequence: Ordered list of agent IDs to execute (None = all agents)
            user_id: User identifier
            session_id: Session identifier
            pass_full_context: Whether to pass full context or just previous result
            **kwargs: Additional arguments
        """
        if not self.agents:
            return {
                'final_result': 'No agents in crew',
                'execution_log': [],
                'success': False
            }

        # Determine agent sequence
        if agent_sequence is None:
            agent_sequence = list(self.agents.keys())

        # Setup session
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'

        # Initialize context
        current_input = initial_query
        crew_context = AgentContext(
            user_id=user_id,
            session_id=session_id,
            original_query=initial_query,
            shared_data=kwargs,
            agent_results={}
        )

        self.execution_log = []

        # Execute agents in sequence
        for i, agent_id in enumerate(agent_sequence):
            if agent_id not in self.agents:
                self.logger.warning(f"Agent '{agent_id}' not found in crew, skipping")
                continue

            agent = self.agents[agent_id]

            try:
                agent_start_time = asyncio.get_event_loop().time()

                # Prepare input
                if i == 0:
                    agent_input = initial_query
                else:
                    if pass_full_context:
                        context_summary = self._build_context_summary(crew_context)
                        agent_input = f"""Original query: {initial_query}

Previous processing:
{context_summary}

Current task: {current_input}"""
                    else:
                        agent_input = current_input

                # Execute agent
                response = await self._execute_agent(
                    agent, agent_input, session_id, user_id, i, crew_context
                )

                result = self._extract_result(response)
                agent_end_time = asyncio.get_event_loop().time()

                # Log execution
                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': agent.name,
                    'agent_index': i,
                    'input': agent_input[:200] + "..." if len(agent_input) > 200 else agent_input,
                    'output': result[:200] + "..." if len(result) > 200 else result,
                    'full_output': result,
                    'execution_time': agent_end_time - agent_start_time,
                    'success': True
                }
                self.execution_log.append(log_entry)

                # Store result
                crew_context.agent_results[agent_id] = result
                current_input = result

            except Exception as e:
                error_msg = f"Error executing agent {agent_id}: {str(e)}"
                self.logger.error(error_msg, exc_info=True)

                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': agent.name,
                    'agent_index': i,
                    'input': current_input,
                    'output': error_msg,
                    'execution_time': 0,
                    'success': False,
                    'error': str(e)
                }
                self.execution_log.append(log_entry)
                current_input = error_msg

        return {
            'final_result': current_input,
            'execution_log': self.execution_log,
            'agent_results': crew_context.agent_results,
            'success': all(log['success'] for log in self.execution_log)
        }

    async def execute_parallel(
        self,
        tasks: List[Dict[str, Any]],
        user_id: str = None,
        session_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute multiple agents in parallel using asyncio.gather().

        Args:
            tasks: List of task dicts with 'agent_id' and 'query' keys
            user_id: User identifier
            session_id: Session identifier
            **kwargs: Additional arguments

        Returns:
            Dict with results from all parallel executions
        """
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'

        crew_context = AgentContext(
            user_id=user_id,
            session_id=session_id,
            original_query=tasks[0]['query'] if tasks else "",
            shared_data=kwargs,
            agent_results={}
        )

        self.execution_log = []

        # Create async tasks
        async_tasks = []
        task_metadata = []

        for i, task in enumerate(tasks):
            agent_id = task.get('agent_id')
            query = task.get('query')

            if agent_id not in self.agents:
                self.logger.warning(f"Agent '{agent_id}' not found, skipping")
                continue

            agent = self.agents[agent_id]
            task_metadata.append({
                'agent_id': agent_id,
                'agent_name': agent.name,
                'query': query,
                'index': i
            })
            async_tasks.append(
                self._execute_agent(
                    agent, query, session_id, user_id, i, crew_context
                )
            )

            if not async_tasks:
                return {
                    'results': {},
                    'execution_log': [],
                    'total_execution_time': 0,
                    'success': False,
                    'error': 'No valid tasks to execute'
                }

        # Execute all tasks in parallel using asyncio.gather()
        start_time = asyncio.get_event_loop().time()
        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        end_time = asyncio.get_event_loop().time()

        # Process results
        parallel_results = {}

        for i, (result, metadata) in enumerate(zip(results, task_metadata)):
            agent_id = metadata['agent_id']

            if isinstance(result, Exception):
                error_msg = f"Error: {str(result)}"
                parallel_results[agent_id] = error_msg

                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': metadata['agent_name'],
                    'agent_index': i,
                    'input': metadata['query'],
                    'output': error_msg,
                    'execution_time': 0,
                    'success': False,
                    'error': str(result)
                }
            else:
                extracted_result = self._extract_result(result)
                parallel_results[agent_id] = extracted_result
                crew_context.agent_results[agent_id] = extracted_result

                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': metadata['agent_name'],
                    'agent_index': i,
                    'input': metadata['query'],
                    'output': extracted_result[:200] + "..." if len(extracted_result) > 200 else extracted_result,
                    'full_output': extracted_result,
                    'execution_time': end_time - start_time,  # Total parallel time
                    'success': True
                }

            self.execution_log.append(log_entry)

        return {
            'results': parallel_results,
            'execution_log': self.execution_log,
            'total_execution_time': end_time - start_time,
            'success': all(log['success'] for log in self.execution_log)
        }

    async def execute_with_dependencies(
        self,
        tasks: List[CrewTask],
        user_id: str = None,
        session_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute tasks respecting dependencies (DAG execution).

        Uses asyncio.gather() to execute independent tasks in parallel
        while respecting dependency constraints.

        Args:
            tasks: List of CrewTask objects with dependencies
            user_id: User identifier
            session_id: Session identifier
            **kwargs: Additional arguments
        """
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'

        crew_context = AgentContext(
            user_id=user_id,
            session_id=session_id,
            original_query=tasks[0].query if tasks else "",
            shared_data=kwargs,
            agent_results={}
        )

        self.execution_log = []
        task_map = {task.task_id: task for task in tasks}
        completed_tasks = set()

        # Execute tasks in dependency order
        while len(completed_tasks) < len(tasks):
            # Find tasks ready to execute (all dependencies met)
            ready_tasks = [
                task for task in tasks
                if task.status == "pending" and
                all(dep in completed_tasks for dep in task.dependencies)
            ]

            if not ready_tasks:
                # Check if we're stuck
                pending_tasks = [t for t in tasks if t.status == "pending"]
                if pending_tasks:
                    error_msg = f"Circular dependency or missing tasks detected"
                    self.logger.error(error_msg)
                    return {
                        'results': crew_context.agent_results,
                        'execution_log': self.execution_log,
                        'success': False,
                        'error': error_msg
                    }
                break

            # Execute ready tasks in parallel using asyncio.gather()
            async_tasks = []
            task_metadata = []

            for task in ready_tasks:
                task.status = "running"

                if task.agent_name not in self.agents:
                    task.status = "failed"
                    task.error = f"Agent '{task.agent_name}' not found"
                    continue

                agent = self.agents[task.agent_name]

                # Build context from dependencies
                dep_context = self._build_dependency_context(task, task_map, crew_context)
                full_query = f"{task.query}\n\n{dep_context}" if dep_context else task.query

                task_metadata.append(task)
                async_tasks.append(
                    self._execute_agent(
                        agent, full_query, session_id, user_id, 0, crew_context
                    )
                )

            # Execute batch in parallel
            start_time = asyncio.get_event_loop().time()
            results = await asyncio.gather(*async_tasks, return_exceptions=True)
            end_time = asyncio.get_event_loop().time()

            # Process results
            for task, result in zip(task_metadata, results):
                if isinstance(result, Exception):
                    task.status = "failed"
                    task.error = str(result)

                    log_entry = {
                        'task_id': task.task_id,
                        'agent_name': task.agent_name,
                        'input': task.query,
                        'output': f"Error: {task.error}",
                        'execution_time': 0,
                        'success': False,
                        'error': task.error
                    }
                else:
                    task.status = "completed"
                    task.result = self._extract_result(result)
                    task.execution_time = end_time - start_time

                    crew_context.agent_results[task.task_id] = task.result
                    completed_tasks.add(task.task_id)

                    log_entry = {
                        'task_id': task.task_id,
                        'agent_name': task.agent_name,
                        'input': task.query,
                        'output': task.result[:200] + "..." if len(task.result) > 200 else task.result,
                        'full_output': task.result,
                        'execution_time': task.execution_time,
                        'success': True
                    }

                self.execution_log.append(log_entry)

        return {
            'results': crew_context.agent_results,
            'tasks': {task.task_id: task for task in tasks},
            'execution_log': self.execution_log,
            'success': all(log['success'] for log in self.execution_log)
        }

    async def _execute_agent(
        self,
        agent: Union[BasicAgent, AbstractBot],
        query: str,
        session_id: str,
        user_id: str,
        index: int,
        context: AgentContext
    ) -> Any:
        """Execute a single agent."""
        async with self.semaphore:
            if hasattr(agent, 'conversation'):
                return await agent.conversation(
                    question=query,
                    session_id=f"{session_id}_agent_{index}",
                    user_id=user_id,
                    use_conversation_history=True,
                    **context.shared_data
                )
            elif hasattr(agent, 'ask'):
                return await agent.ask(
                    question=query,
                    session_id=f"{session_id}_agent_{index}",
                    user_id=user_id,
                    use_conversation_history=True,
                    **context.shared_data
                )
            elif hasattr(agent, 'invoke'):
                return await agent.invoke(
                    question=query,
                    session_id=f"{session_id}_agent_{index}",
                    user_id=user_id,
                    use_conversation_history=False,
                    **context.shared_data
                )
            else:
                raise ValueError(
                    f"Agent {agent.name} does not support conversation or invoke methods"
                )

    def _extract_result(self, response: Any) -> str:
        """Extract result string from response."""
        if isinstance(response, (AIMessage, AgentResponse)):
            return response.content
        elif hasattr(response, 'content'):
            return response.content
        else:
            return str(response)

    def _build_context_summary(self, context: AgentContext) -> str:
        """Build summary of previous results."""
        summaries = []
        for agent_name, result in context.agent_results.items():
            truncated = result[:200] + "..." if len(result) > 200 else result
            summaries.append(f"- {agent_name}: {truncated}")
        return "\n".join(summaries)

    def _build_dependency_context(
        self,
        task: CrewTask,
        task_map: Dict[str, CrewTask],
        context: AgentContext
    ) -> str:
        """Build context from task dependencies."""
        if not task.dependencies:
            return ""

        dep_results = []
        for dep_id in task.dependencies:
            if dep_id in task_map and task_map[dep_id].result:
                dep_task = task_map[dep_id]
                dep_results.append(f"From {dep_task.agent_name}: {dep_task.result}")

        if dep_results:
            return "Context from dependencies:\n" + "\n\n".join(dep_results)
        return ""

    def get_execution_summary(self) -> Dict[str, Any]:
        """Get summary of last execution."""
        if not self.execution_log:
            return {'message': 'No executions yet'}

        total_time = sum(log['execution_time'] for log in self.execution_log)
        success_count = sum(1 for log in self.execution_log if log['success'])

        return {
            'total_agents': len(self.agents),
            'executed_agents': len(self.execution_log),
            'successful_agents': success_count,
            'total_execution_time': total_time,
            'average_time_per_agent': total_time / len(self.execution_log) if self.execution_log else 0
        }

    async def task(
        self,
        task: Union[str, Dict[str, str]],
        synthesis_prompt: Optional[str] = None,
        user_id: str = None,
        session_id: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        **kwargs
    ) -> AIMessage:
        """
        Execute all agents in parallel with a task, then synthesize results with LLM.

        This is a simplified interface for the common pattern:
        1. Multiple agents research/gather information in parallel
        2. LLM synthesizes all findings into a coherent response

        Args:
            task: The task/prompt for agents. Can be:
                  - str: Same prompt for all agents
                  - dict: Custom prompt per agent {agent_id: prompt}
            synthesis_prompt: Prompt for LLM to synthesize results.
                            If None, uses default synthesis prompt.
                            Aliases: conclusion, summary_prompt, final_prompt
            user_id: User identifier
            session_id: Session identifier
            max_tokens: Max tokens for synthesis LLM
            temperature: Temperature for synthesis LLM
            **kwargs: Additional arguments passed to LLM

        Returns:
            AIMessage: Synthesized response from the LLM

        Example:
            >>> crew = AgentCrew(
            ...     agents=[info_agent, price_agent, review_agent],
            ...     llm=ClaudeClient()
            ... )
            >>> result = await crew.task(
            ...     task="Research iPhone 15 Pro",
            ...     synthesis_prompt="Create an executive summary"
            ... )
            >>> print(result.content)

        Raises:
            ValueError: If no LLM is configured for synthesis
        """
        if not self._llm:
            raise ValueError(
                "No LLM configured for synthesis. "
                "Pass llm parameter to AgentCrew constructor: "
                "AgentCrew(agents=[...], llm=ClaudeClient())"
            )

        if not self.agents:
            raise ValueError(
                "No agents in crew. Add agents first."
            )

        # Setup session
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'

        # Prepare tasks for each agent
        tasks_list = []

        if isinstance(task, str):
            # Same task for all agents
            for agent_id, _ in self.agents.items():
                tasks_list.append({
                    'agent_id': agent_id,
                    'query': task
                })
        elif isinstance(task, dict):
            # Custom task per agent
            for agent_id, agent_task in task.items():
                if agent_id in self.agents:
                    tasks_list.append({
                        'agent_id': agent_id,
                        'query': agent_task
                    })
                else:
                    self.logger.warning(
                        f"Agent '{agent_id}' in task dict not found in crew"
                    )
        else:
            raise ValueError(
                f"task must be str or dict, got {type(task)}"
            )

        # Execute agents in parallel
        self.logger.info(
            f"Executing {len(tasks_list)} agents in parallel for research"
        )

        parallel_result = await self.execute_parallel(
            tasks=tasks_list,
            user_id=user_id,
            session_id=session_id,
            **kwargs
        )

        if not parallel_result['success']:
            raise RuntimeError(
                f"Parallel execution failed: {parallel_result.get('error', 'Unknown error')}"
            )

        # Build context from all agent results
        context_parts = []
        context_parts.append("# Research Findings from Specialist Agents\n")

        for agent_id, result in parallel_result['results'].items():
            agent = self.agents[agent_id]
            agent_name = agent.name

            context_parts.append(f"\n## {agent_name}\n")
            context_parts.append(result)
            context_parts.append("\n---\n")

        research_context = "\n".join(context_parts)

        # Default synthesis prompt if none provided
        if not synthesis_prompt:
            synthesis_prompt = """Based on the research findings from our specialist agents above,
provide a comprehensive synthesis that:
1. Integrates all the key findings
2. Highlights the most important insights
3. Identifies any patterns or contradictions
4. Provides actionable conclusions

Create a clear, well-structured response."""

        # Build final prompt for LLM
        final_prompt = f"""{research_context}

{synthesis_prompt}"""

        # Call LLM for synthesis
        self.logger.info("Synthesizing results with LLM coordinator")

        async with self._llm as client:
            synthesis_response = await client.ask(
                prompt=final_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                user_id=user_id,
                session_id=f"{session_id}_synthesis",
                **kwargs
            )

        # Enhance response with crew metadata
        if hasattr(synthesis_response, 'metadata'):
            synthesis_response.metadata['crew_name'] = self.name
            synthesis_response.metadata['agents_used'] = list(parallel_result['results'].keys())
            synthesis_response.metadata['total_execution_time'] = parallel_result['total_execution_time']

        return synthesis_response
