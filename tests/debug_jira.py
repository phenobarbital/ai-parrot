import os
import asyncio
from parrot.tools.jiratoolkit import JiraToolkit
# Try to import navconfig
try:
    from navconfig import config as nav_config
except ImportError:
    nav_config = None

async def main():
    print("Testing JiraToolkit directly...")
    
    # Simulate HR Agent logic
    if nav_config:
        jira_instance = nav_config.get("JIRA_INSTANCE")
        jira_api_token = nav_config.get("JIRA_API_TOKEN")
        jira_username = nav_config.get("JIRA_USERNAME")
        jira_project = nav_config.get("JIRA_PROJECT")
    else:
        jira_instance = os.getenv("JIRA_INSTANCE")
        jira_api_token = os.getenv("JIRA_API_TOKEN") or os.getenv("JIRA_PASSWORD")
        jira_username = os.getenv("JIRA_USERNAME")
        jira_project = os.getenv("JIRA_PROJECT", "NAV")

    print(f"URL: {jira_instance}")
    print(f"User: {jira_username}")
    print(f"Token (len): {len(str(jira_api_token)) if jira_api_token else 0}")
    
    print("Initializing JiraToolkit with auth_type='basic_auth'...")
    try:
        toolkit = JiraToolkit(
            server_url=jira_instance,
            auth_type="basic_auth",
            username=jira_username,
            password=jira_api_token,
            default_project=jira_project
        )
        print(f"Toolkit initialized. Auth Type: {toolkit.auth_type}")
        
        issue_key = "NAV-7010"
        print(f"Getting issue {issue_key} via toolkit...")
        issue = await toolkit.jira_get_issue(issue_key)
        print(f"Success! Issue Key: {issue.get('key')}")
        print(f"Summary: {issue.get('fields', {}).get('summary')}")
        
    except Exception as e:
        print(f"Toolkit Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
