"""
Jira Ticket Evaluation Crew

This script creates a crew of agents to evaluate a Jira ticket.
"""
import asyncio
from parrot.bots.agent import BasicAgent
from parrot.tools.core import tool
from jira import JIRA
from parrot.bots.orchestration.crew import AgentCrew


@tool
def get_issue(issue_id: str) -> str:
    """
    Get a Jira issue by its ID.
    """
    # This is a public Jira instance, so no auth is needed for public issues.
    # For a real-world scenario, you'd pass credentials here.
    jira = JIRA('https://jira.atlassian.com')
    try:
        issue = jira.issue(issue_id)
        return f"Summary: {issue.fields.summary}\nDescription: {issue.fields.description}"
    except Exception as e:
        return f"Error fetching issue: {e}"


class JiraAgent(BasicAgent):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tool_manager.add_tool(get_issue)


class SummarizerAgent(BasicAgent):
    def __init__(self, **kwargs):
        super().__init__(
            name="SummarizerAgent",
            system_prompt="You are a summarizer agent. Your task is to summarize the provided Jira ticket information.",
            **kwargs
        )


class ImpactAnalyzerAgent(BasicAgent):
    def __init__(self, **kwargs):
        super().__init__(
            name="ImpactAnalyzerAgent",
            system_prompt="You are an impact analyzer agent. Your task is to analyze the Jira ticket summary and define which changes are needed and what projects are impacted.",
            **kwargs
        )


# 1. Create the agents
jira_agent = JiraAgent(name="JiraAgent", use_llm='google')
summarizer_agent = SummarizerAgent(name="SummarizerAgent", use_llm='google')
impact_analyzer_agent = ImpactAnalyzerAgent(name="ImpactAnalyzerAgent", use_llm='google')

# 2. Create the crew with a sequential workflow
crew = AgentCrew(agents=[jira_agent, summarizer_agent, impact_analyzer_agent])


async def main():
    """
    Run the Jira evaluation crew.
    """
    print("Configuring agents...")
    for agent in crew.agents:
        await agent.configure()

    # A public Jira issue we can use for testing
    issue_id = "JRA-9"
    initial_query = f"Get Jira issue {issue_id}"

    print(f"\nRunning crew for issue: {issue_id}...")
    result = await crew.run_sequential(
        initial_query=initial_query,
        pass_full_context=True
    )

    print("\n\n" + "="*80)
    print("✅ Crew execution complete.")
    print("="*80)
    print("\nFinal Result:\n")
    print(result['final_result'])

    summary = crew.get_execution_summary()
    print(f"\n⏱️ Total time: {summary['total_execution_time']:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
