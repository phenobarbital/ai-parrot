"""
HR-specific orchestrator and crew factories.
"""
from typing import List, Dict
from ..agent import BasicAgent
from .agent import OrchestratorAgent
from .crew import AgentCrew
from ...tools.abstract import AbstractTool
from ...tools.manager import ToolManager
from ...stores.abstract import AbstractStore


class HRAgentFactory:
    """Factory for creating HR-specific agent orchestration systems."""

    @staticmethod
    def create_hr_orchestrator(
        hr_agent: BasicAgent = None,
        employee_data_agent: BasicAgent = None,
        shared_tools: List[AbstractTool] = None
    ) -> OrchestratorAgent:
        """
        Create an HR orchestrator with specialized agents.

        Args:
            hr_agent: Agent for HR policies and procedures
            employee_data_agent: Agent for employee data access
            shared_tools: Tools to share between agents
        """
        orchestrator = OrchestratorAgent(
            name="HROrchestrator",
            orchestration_prompt="""
You are an HR assistance orchestrator that helps employees with their questions
by consulting specialized agents for different types of information.

Your available agents:
- HR Policy Agent: Handles company policies, procedures, benefits, and general HR questions
- Employee Data Agent: Provides employee profile information, job details, salary, and organizational data

For employee questions:
- Use hr_policy_agent for policy, procedure, and general HR questions
- Use employee_data_agent for specific employee information (profile, salary, position)
- Combine responses when both perspectives are needed
- Always ensure data privacy and access controls are respected
- Provide a unified, comprehensive answer that addresses all aspects of the question
"""
        )

        # Add shared tools if provided
        if shared_tools:
            for tool in shared_tools:
                orchestrator.tool_manager.add_tool(tool)

        # Add HR agent if provided
        if hr_agent:
            orchestrator.add_agent(
                hr_agent,
                tool_name="hr_policy_agent",
                description="Handles HR policies, procedures, benefits, and general HR questions using company knowledge base"
            )

        # Add employee data agent if provided
        if employee_data_agent:
            orchestrator.add_agent(
                employee_data_agent,
                tool_name="employee_data_agent",
                description="Provides employee profile information, job details, salary, and organizational data"
            )

        return orchestrator

    @staticmethod
    def create_hr_crew(
        agents: List[BasicAgent],
        shared_tools: List[AbstractTool] = None
    ) -> AgentCrew:
        """
        Create an HR processing crew that processes requests in sequence.

        Example sequence: Policy Check → Data Validation → Response Generation
        """
        shared_tool_manager = ToolManager()

        # Add shared tools
        if shared_tools:
            for tool in shared_tools:
                shared_tool_manager.add_tool(tool)

        crew = AgentCrew(
            name="HRProcessingCrew",
            agents=agents,
            shared_tool_manager=shared_tool_manager
        )

        return crew

class RAGHRAgent(BasicAgent):
    """
    HR Agent with RAG capabilities using your existing vector store system.

    This agent specializes in company policies, procedures, and HR documentation.
    """

    def __init__(
        self,
        vector_store: AbstractStore = None,
        knowledge_threshold: float = 0.7,
        max_context_docs: int = 5,
        **kwargs
    ):
        # Set HR-specific system prompt
        hr_system_prompt = kwargs.pop('system_prompt', None) or """
You are an HR Policy Specialist with comprehensive knowledge of company policies, procedures, and HR documentation.

Your expertise covers:
- Employee benefits and compensation policies
- Leave policies (vacation, sick, personal, parental)
- Performance review processes and procedures
- Company policies and employee handbook
- Compliance requirements and regulations
- Employee development and training programs
- Workplace policies and guidelines

When answering questions:
1. Always search the knowledge base first for accurate, current information
2. Provide specific policy references when available
3. Explain both the policy and its practical implications
4. If information isn't in the knowledge base, clearly state this limitation
5. Maintain confidentiality and follow data privacy guidelines
6. Provide actionable guidance when possible

Always base your responses on official company documentation.
"""

        super().__init__(
            name="HRPolicyAgent",
            system_prompt=hr_system_prompt,
            **kwargs
        )

        self.vector_store = vector_store
        self.knowledge_threshold = knowledge_threshold
        self.max_context_docs = max_context_docs

        # Add RAG capabilities if vector store is provided
        if self.vector_store:
            self._setup_rag_tools()

    def _setup_rag_tools(self):
        """Setup RAG tools for HR knowledge base search."""

        class HRKnowledgeSearchTool(AbstractTool):
            """Tool for searching HR knowledge base."""

            def __init__(self, vector_store, threshold, max_docs):
                super().__init__()
                self.vector_store = vector_store
                self.threshold = threshold
                self.max_docs = max_docs
                self.name = "search_hr_policies"
                self.description = "Search the HR knowledge base for company policies, procedures, and documentation"

                self.input_schema = {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for HR policies and procedures"
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["similarity", "mmr", "ensemble"],
                            "description": "Type of search to perform",
                            "default": "similarity"
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }

            async def _execute(self, query: str, search_type: str = "similarity", **kwargs) -> str:
                """Execute knowledge base search."""
                try:
                    # Use your existing vector store search
                    results = await self.vector_store.asearch(
                        query=query,
                        search_type=search_type,
                        limit=self.max_docs,
                        score_threshold=self.threshold
                    )

                    if not results:
                        return "No relevant policy information found in the knowledge base."

                    # Format results for context
                    context_parts = []
                    for i, result in enumerate(results, 1):
                        # Assuming your vector store returns documents with content and metadata
                        title = getattr(result, 'title', f'Document {i}')
                        content = getattr(result, 'content', str(result))
                        source = getattr(result, 'source', 'Unknown')

                        context_parts.append(f"**Policy Document {i}: {title}**")
                        context_parts.append(f"Source: {source}")
                        context_parts.append(f"Content: {content}")
                        context_parts.append("---")

                    return "\n".join(context_parts)

                except Exception as e:
                    return f"Error searching HR knowledge base: {str(e)}"

        # Add the HR knowledge search tool
        hr_search_tool = HRKnowledgeSearchTool(
            self.vector_store,
            self.knowledge_threshold,
            self.max_context_docs
        )
        self.tool_manager.add_tool(hr_search_tool)


class EmployeeDataAgent(BasicAgent):
    """
    Agent specialized in employee profile and organizational data.

    This agent handles employee-specific information like profiles, positions, salary data.
    """

    def __init__(
        self,
        employee_database=None,
        access_control_rules: Dict[str, List[str]] = None,
        **kwargs
    ):
        employee_system_prompt = kwargs.pop('system_prompt', None) or """
You are an Employee Data Specialist with secure access to employee information and organizational data.

Your capabilities include:
- Employee profiles and contact information
- Current job positions and organizational hierarchy
- Salary and compensation data (when authorized)
- Performance records (when authorized)
- Team and department assignments
- Employment history and tenure information

Security and Privacy Guidelines:
- Always verify user authorization before accessing sensitive data
- Only provide information the requesting user is authorized to see
- Log all data access requests for audit purposes
- Never expose raw database queries or technical implementation details
- Respect confidentiality levels and data classification
- Follow GDPR and other applicable privacy regulations

When handling requests:
1. Check user authorization for the requested data type
2. Query only the specific information needed
3. Format responses in a clear, professional manner
4. Include appropriate disclaimers for sensitive information
5. Suggest alternative approaches if access is restricted
"""

        super().__init__(
            name="EmployeeDataAgent",
            system_prompt=employee_system_prompt,
            **kwargs
        )

        self.employee_database = employee_database
        self.access_rules = access_control_rules or {
            'salary_data': ['self', 'manager', 'hr'],
            'personal_info': ['self', 'hr'],
            'performance_data': ['self', 'manager', 'hr'],
            'contact_info': ['all'],
            'organizational_data': ['all']
        }

        # Add employee data tools if database is provided
        if self.employee_database:
            self._setup_employee_data_tools()

    def _setup_employee_data_tools(self):
        """Setup employee data access tools with security controls."""

        class EmployeeProfileTool(AbstractTool):
            """Tool for accessing employee profile information."""

            def __init__(self, database, access_rules):
                super().__init__()
                self.database = database
                self.access_rules = access_rules
                self.name = "get_employee_profile"
                self.description = "Get employee profile information including position, department, and contact details"

                self.input_schema = {
                    "type": "object",
                    "properties": {
                        "employee_id": {
                            "type": "string",
                            "description": "Employee ID to lookup"
                        },
                        "requesting_user_id": {
                            "type": "string",
                            "description": "ID of user making the request"
                        },
                        "data_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["profile", "position", "contact", "salary", "performance"]
                            },
                            "description": "Types of data to retrieve"
                        }
                    },
                    "required": ["employee_id", "requesting_user_id"],
                    "additionalProperties": False
                }

            async def _execute(
                self,
                employee_id: str,
                requesting_user_id: str,
                data_types: List[str] = None,
                **kwargs
            ) -> str:
                """Execute employee data query with access controls."""
                try:
                    # Check authorization for each data type
                    authorized_data = []
                    denied_data = []

                    data_types = data_types or ['profile', 'position', 'contact']

                    for data_type in data_types:
                        if self._check_access(requesting_user_id, employee_id, data_type):
                            authorized_data.append(data_type)
                        else:
                            denied_data.append(data_type)

                    if not authorized_data:
                        return f"Access denied: No authorization for requested data types: {', '.join(data_types)}"

                    # Query database for authorized data
                    # This is where you'd integrate with your actual employee database
                    result_parts = []

                    if 'profile' in authorized_data:
                        # Mock data - replace with actual database query
                        result_parts.append(f"Employee Profile for {employee_id}:")
                        result_parts.append(f"- Name: [Retrieved from database]")
                        result_parts.append(f"- Employee ID: {employee_id}")
                        result_parts.append(f"- Start Date: [Retrieved from database]")

                    if 'position' in authorized_data:
                        result_parts.append(f"Position Information:")
                        result_parts.append(f"- Title: [Retrieved from database]")
                        result_parts.append(f"- Department: [Retrieved from database]")
                        result_parts.append(f"- Manager: [Retrieved from database]")

                    if 'salary' in authorized_data:
                        result_parts.append(f"Compensation Information:")
                        result_parts.append(f"- Salary: [Retrieved from database]")
                        result_parts.append(f"- Last Review: [Retrieved from database]")

                    result = "\n".join(result_parts)

                    if denied_data:
                        result += f"\n\nNote: Access denied for: {', '.join(denied_data)}"

                    return result

                except Exception as e:
                    return f"Error retrieving employee data: {str(e)}"

            def _check_access(self, requesting_user: str, target_employee: str, data_type: str) -> bool:
                """Check if user has access to specific data type."""
                # Simplified access control - replace with your actual logic

                # Users can always access their own basic info
                if requesting_user == target_employee and data_type in ['profile', 'position', 'contact']:
                    return True

                # Check access rules
                allowed_roles = self.access_rules.get(data_type, [])

                # This is where you'd check the user's actual role
                # For demo purposes, we'll assume some basic logic
                if 'all' in allowed_roles:
                    return True

                # Add your actual role checking logic here
                return False

        class VacationBalanceTool(AbstractTool):
            """Tool for checking vacation day balances."""

            def __init__(self, database):
                super().__init__()
                self.database = database
                self.name = "get_vacation_balance"
                self.description = "Get current vacation day balance and accrual information"

                self.input_schema = {
                    "type": "object",
                    "properties": {
                        "employee_id": {
                            "type": "string",
                            "description": "Employee ID to check balance for"
                        }
                    },
                    "required": ["employee_id"],
                    "additionalProperties": False
                }

            async def _execute(self, employee_id: str, **kwargs) -> str:
                """Get vacation balance information."""
                try:
                    # Mock vacation data - replace with actual database query
                    return f"""Vacation Balance for Employee {employee_id}:
- Current Available Days: 15.5 days
- Used This Year: 4.5 days
- Total Annual Allocation: 20 days
- Accrual Rate: 1.67 days per month
- Next Accrual Date: End of current month
- Rollover Limit: 5 days maximum"""

                except Exception as e:
                    return f"Error retrieving vacation balance: {str(e)}"

        # Add employee data tools
        profile_tool = EmployeeProfileTool(self.employee_database, self.access_rules)
        vacation_tool = VacationBalanceTool(self.employee_database)

        self.tool_manager.add_tool(profile_tool)
        self.tool_manager.add_tool(vacation_tool)
