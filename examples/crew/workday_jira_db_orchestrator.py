"""
Complete Working Example - Workday, Jira, and Database Orchestrator

This example demonstrates an OrchestratorAgent coordinating three specialized agents:
1. Workday Agent - For HR operations and employee data
2. Jira Agent - For issue tracking and project management
3. Database Agent - For data querying and analysis

Copy this file and run it to test the orchestrator system.
"""
import sys
import asyncio
from navconfig import config
from parrot.bots.agent import BasicAgent
from parrot.bots.orchestration.agent import OrchestratorAgent
from parrot.tools.workday.tool import WorkdayToolkit
from parrot.tools.jiratoolkit import JiraToolkit
from parrot.tools.databasequery import DatabaseQueryTool
from parrot.tools.qsource import QSourceTool


async def create_enterprise_orchestrator():
    """
    Create a working enterprise orchestrator with Workday, Jira, and Database agents.

    Returns a configured orchestrator ready to use.
    """

    # ========================================================================
    # 1. CREATE SPECIALIST AGENTS
    # ========================================================================

    print("📦 Creating specialist agents...")

    # Workday HR Specialist
    workday_specialist = BasicAgent(
        name="WorkdaySpecialist",
        agent_id="workday_specialist",
        role="HR and Employee Data Expert",
        goal="Access employee information, time off balances, and HR data from Workday",
        capabilities="Employee lookups, time off queries, organization data, job information",
        system_prompt="""You are a Workday HR specialist.

Your expertise:
- Employee data retrieval (workers, contact info, job data)
- Time off balances and absence management
- Organization structure and hierarchy
- Worker searches and filtering

IMPORTANT: Always use your Workday tools to fetch current, accurate HR information.

Response format:
- Start with the employee name or ID
- Present data in clear, organized sections
- Include relevant dates and IDs
- Be specific with numbers and units""",
        use_llm='google'
    )

    # Jira Project Management Specialist
    jira_specialist = BasicAgent(
        name="JiraSpecialist",
        agent_id="jira_specialist",
        role="Project Management and Issue Tracking Expert",
        goal="Access and manage Jira issues, projects, and workflows",
        capabilities="Issue retrieval, JQL searches, issue transitions, assignments",
        system_prompt="""You are a Jira project management expert.

Your expertise:
- Retrieving Jira issues and their details
- Searching issues using JQL
- Finding issues by assignee or project
- Transitioning and updating issues

IMPORTANT: Always use your Jira tools to find current project information.

Response format:
- List issues with key and summary
- Include status and assignee
- Show relevant dates
- Be specific with issue details and links""",
        use_llm='google'
    )

    # Database Query Specialist
    database_specialist = BasicAgent(
        name="DatabaseSpecialist",
        agent_id="database_specialist",
        role="Data Analysis and Database Query Expert",
        goal="Execute database queries and analyze data",
        capabilities="SQL queries, data retrieval, query source operations, data analysis",
        system_prompt="""You are a database and data analysis expert.

Your expertise:
- Executing SQL queries on various databases
- Using QuerySource for pre-defined queries
- Analyzing and summarizing data
- Working with structured data outputs

IMPORTANT: Always use your database tools to fetch current, accurate data.

Response format:
- Present query results in clear tables or lists
- Include row counts and summary statistics
- Highlight key findings
- Be specific with data values and units""",
        use_llm='google'
    )

    # ========================================================================
    # 2. CONFIGURE TOOLS FOR EACH SPECIALIST
    # ========================================================================

    print("🔧 Configuring tools for specialists...")

    # Configure Workday Agent
    workday_toolkit = WorkdayToolkit(redis_url="redis://localhost:6379/4")
    for tool in workday_toolkit.get_tools():
        workday_specialist.tool_manager.add_tool(tool)

    # Configure Jira Agent
    jira_instance = config.get("JIRA_INSTANCE")
    jira_api_token = config.get("JIRA_API_TOKEN")
    jira_username = config.get("JIRA_USERNAME")
    jira_project = config.get("JIRA_PROJECT")

    jira_toolkit = JiraToolkit(
        server_url=jira_instance,
        auth_type="basic_auth",
        username=jira_username,
        password=jira_api_token,
        default_project=jira_project
    )
    for tool in jira_toolkit.get_tools():
        jira_specialist.tool_manager.add_tool(tool)

    # Configure Database Agent
    db_query_tool = DatabaseQueryTool()
    qsource_tool = QSourceTool()
    database_specialist.tool_manager.add_tool(db_query_tool)
    database_specialist.tool_manager.add_tool(qsource_tool)

    # Configure all agents
    agents = [workday_specialist, jira_specialist, database_specialist]
    for specialist in agents:
        await specialist.configure()

    print("✅ Specialists configured")

    # ========================================================================
    # 3. CREATE ORCHESTRATOR
    # ========================================================================

    print("\n🎭 Creating orchestrator...")

    orchestrator = OrchestratorAgent(
        name="EnterpriseCoordinator",
        agent_id="enterprise_coordinator",
        use_llm='google',
        orchestration_prompt="""You are an Enterprise Coordinator that delegates to specialist agents.

═══════════════════════════════════════════════════════════════
⚠️  CRITICAL INSTRUCTION: You MUST use specialist tools to answer
    questions. You do NOT answer from your own knowledge.
═══════════════════════════════════════════════════════════════

🔧 AVAILABLE SPECIALIST TOOLS:

1. workdayspecialist
   Purpose: Access HR and employee data from Workday
   Use for: employee info, time off balances, organization structure, job data
   Example: workdayspecialist(question="What is the time off balance for employee 12345?")

2. jiraspecialist
   Purpose: Access Jira for project and issue management
   Use for: issue details, JQL searches, issue assignments, project status
   Example: jiraspecialist(question="Find all open issues assigned to john.doe")

3. databasespecialist
   Purpose: Query databases and analyze data
   Use for: SQL queries, data retrieval, analytics, QuerySource operations
   Example: databasespecialist(question="Get sales data for the last 30 days")

📋 HOW TO ANSWER QUESTIONS:

Step 1: Analyze what information the user needs
Step 2: Call the appropriate specialist tool(s)
Step 3: Wait for their responses
Step 4: Synthesize the information into a clear answer

🎯 EXAMPLES:

User: "What is the time off balance for employee 12345?"
→ Action: Call workdayspecialist(question="What is the time off balance for employee 12345?")

User: "Show me all critical bugs in project ABC"
→ Action: Call jiraspecialist(question="Find all critical bugs in project ABC")

User: "Get sales data from the database for last month"
→ Action: Call databasespecialist(question="Query sales data for last month")

User: "Find employee 12345's info and their assigned Jira issues"
→ Action 1: Call workdayspecialist(question="Get employee info for worker 12345")
→ Action 2: Call jiraspecialist(question="Find Jira issues assigned to employee 12345")
→ Combine: Synthesize both responses into one comprehensive answer

⚡ RULES:

1. ALWAYS use tools - never answer from your knowledge
2. Pass clear, specific questions to each specialist
3. If query needs multiple systems, call MULTIPLE tools
4. Synthesize responses into a natural, comprehensive answer
5. Credit specialists when appropriate (e.g., "According to our HR specialist...")"""
    )

    await orchestrator.configure()

    print("✅ Orchestrator configured")

    # ========================================================================
    # 4. REGISTER SPECIALISTS AS TOOLS
    # ========================================================================

    print("\n🔌 Registering specialists as tools...")

    workday_specialist.register_as_tool(
        orchestrator,
        tool_name="workdayspecialist",
        tool_description="HR and employee data expert. Use this to access Workday for employee information, time off balances, organization data, and job details."
    )

    jira_specialist.register_as_tool(
        orchestrator,
        tool_name="jiraspecialist",
        tool_description="Project management expert. Use this to access Jira for issue details, JQL searches, issue assignments, and project tracking."
    )

    database_specialist.register_as_tool(
        orchestrator,
        tool_name="databasespecialist",
        tool_description="Data analysis expert. Use this to execute database queries, retrieve data using QuerySource, and analyze structured data."
    )

    # Verify registration
    registered_tools = orchestrator.tool_manager.list_tools()
    print(f"✅ Registered tools: {registered_tools}")
    print(f"✅ Total tools: {orchestrator.get_tools_count()}")

    return orchestrator


async def test_orchestrator():
    """
    Test the orchestrator with various queries.
    """

    # Create orchestrator
    orchestrator = await create_enterprise_orchestrator()

    # Test queries
    test_queries = [
        {
            "name": "Workday Only",
            "query": "What is the time off balance for employee 12345?",
            "expected_tools": ["workdayspecialist"]
        },
        {
            "name": "Jira Only",
            "query": "Find all open critical bugs in project NAV",
            "expected_tools": ["jiraspecialist"]
        },
        {
            "name": "Database Only",
            "query": "Query the sales data for the last 30 days",
            "expected_tools": ["databasespecialist"]
        },
        {
            "name": "Workday + Jira",
            "query": "Get employee 12345's information and their assigned Jira issues",
            "expected_tools": ["workdayspecialist", "jiraspecialist"]
        },
        {
            "name": "All Three Systems",
            "query": "Get employee 12345's HR info, their Jira assignments, and run a database query for their sales performance",
            "expected_tools": ["workdayspecialist", "jiraspecialist", "databasespecialist"]
        },
    ]

    print("\n" + "="*80)
    print("TESTING ORCHESTRATOR")
    print("="*80)

    for i, test in enumerate(test_queries, 1):
        print(f"\n{'='*80}")
        print(f"TEST {i}: {test['name']}")
        print(f"{'='*80}")
        print(f"Query: {test['query']}")
        print(f"Expected tools: {test['expected_tools']}")
        print()

        # Execute query
        response = await orchestrator.conversation(
            question=test['query'],
            use_conversation_history=False
        )

        # Display response
        print(f"📝 RESPONSE:")
        print("-" * 80)
        print(response.content)
        print()

        # Check tool usage
        if response.tool_calls:
            tools_used = [tc.name for tc in response.tool_calls]
            print(f"✅ Tools used: {tools_used}")

            # Verify expected tools
            all_expected = all(tool in tools_used for tool in test['expected_tools'])
            if all_expected:
                print(f"✅ All expected tools were called")
            else:
                print(f"⚠️  Expected {test['expected_tools']}, got {tools_used}")

            # Show tool details
            for tc in response.tool_calls:
                print(f"\n  🔧 {tc.name}:")
                print(f"     Input: {tc.arguments}")
        else:
            print("❌ FAILED: No tools were used!")
            print("   This is a problem - orchestrator should always use tools")

        print()


async def interactive_mode():
    """
    Interactive mode to test orchestrator with custom queries.
    """

    orchestrator = await create_enterprise_orchestrator()

    print("\n" + "="*80)
    print("INTERACTIVE MODE")
    print("="*80)
    print("\nYou can now ask questions about HR, Jira, or Database.")
    print("The orchestrator will delegate to specialist agents.")
    print("\nExamples:")
    print("  - Get employee 12345's time off balance")
    print("  - Find all Jira issues assigned to john.doe")
    print("  - Query the sales database for last month")
    print("  - Get employee info and their Jira assignments")
    print("\nType 'quit' to exit\n")

    while True:
        try:
            query = input("Your question: ").strip()

            if query.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            if not query:
                continue

            print(f"\n🤔 Processing...")

            response = await orchestrator.conversation(
                question=query,
                use_conversation_history=False
            )

            print(f"\n📝 Response:")
            print("-" * 80)
            print(response.content)

            if response.tool_calls:
                print(f"\n🔧 Tools used: {[tc.name for tc in response.tool_calls]}")
            else:
                print(f"\n⚠️  No tools used")

            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


async def main():
    """
    Main entry point.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        await interactive_mode()
    else:
        await test_orchestrator()


if __name__ == "__main__":
    asyncio.run(main())
