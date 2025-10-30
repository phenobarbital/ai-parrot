import asyncio
from navconfig import config
from parrot.tools.jiratoolkit import JiraToolkit


async def main():
    jira_instance = config.get("JIRA_INSTANCE")
    jira_api_token = config.get("JIRA_API_TOKEN")
    jira_username = config.get("JIRA_USERNAME")
    jira_project = config.get("JIRA_PROJECT")
    jira_secret_token = config.get("JIRA_SECRET_TOKEN")
    toolkit = JiraToolkit(
        server_url=jira_instance,
        auth_type="basic_auth",
        username=jira_username,
        password=jira_api_token,
        # token=jira_api_token,
        default_project=jira_project
    )
    tools = toolkit.get_tools()
    print("Available tools:", [tool.name for tool in tools])

    # Example: Get issue by key
    issue = await toolkit.jira_get_issue(
        "NAV-5932",
        structured={
        "mapping": {
                "key": "key",
                "summary": "fields.summary",
                "description": "fields.description",
                "assignee": "fields.assignee.displayName",
                "comments": "fields.comment.comments"
            }
        }
    )


    print("Issue NAV-5932:", issue)


if __name__ == "__main__":
    asyncio.run(main())
