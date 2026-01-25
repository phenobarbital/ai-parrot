"""
Start a MCP server for Jira
"""
import argparse
from navconfig import config
from parrot.services.mcp.simple import SimpleMCPServer
from parrot.tools.jiratoolkit import JiraToolkit

def main():
    parser = argparse.ArgumentParser(description="Start Jira MCP Server")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--transport", type=str, default="http", choices=["http", "sse"], help="Transport type")
    parser.add_argument("--api-key", type=str, required=False, help="API Key for auth")
    parser.add_argument("--jira-url", type=str, required=True, help="Jira Server URL")
    parser.add_argument("--user", type=str, required=True, help="Jira Username/Email")
    parser.add_argument("--token", type=str, required=True, help="Jira API Token")
    parser.add_argument("--ssl-cert", type=str, help="Path to SSL Certificate")
    parser.add_argument("--ssl-key", type=str, help="Path to SSL Private Key")
    
    args = parser.parse_args()

    # Initialize Toolkit
    # This Toolkit provides multiple methods (GetIssue, TransitionIssue, etc.)
    # The SimpleMCPServer will register all of them automatically.
    jira_instance = config.get("JIRA_INSTANCE")
    jira_api_token = config.get("JIRA_API_TOKEN")
    jira_username = config.get("JIRA_USERNAME")
    jira_project = config.get("JIRA_PROJECT")
    jira_tools = JiraToolkit(
        server_url=args.jira_url or jira_instance,
        username=args.user or jira_username,
        token=args.token or jira_api_token,
        default_project=jira_project,
        auth_type="basic_auth",
    )

    # Auth configuration
    auth_method = "none"
    if args.api_key:
        auth_method = "api_key"

    print(
        f"Starting Jira MCP Server on port {args.port}..."
    )
    
    # Start the Server
    server = SimpleMCPServer(
        tool=jira_tools,
        name="JiraMCP",
        port=args.port,
        transport=args.transport,
        auth_method=auth_method,
        api_key=args.api_key,
        ssl_cert=args.ssl_cert,
        ssl_key=args.ssl_key
    )
    
    server.run()

if __name__ == "__main__":
    main()
