
import os
import argparse
from parrot.services.mcp.simple_server import SimpleMCPServer
from parrot.tools.jiratoolkit import JiraToolkit

def main():
    parser = argparse.ArgumentParser(description="Start Jira MCP Server")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--transport", type=str, default="http", choices=["http", "sse"], help="Transport type")
    parser.add_argument("--api-key", type=str, required=False, help="API Key for auth")
    parser.add_argument("--jira-url", type=str, required=True, help="Jira Server URL")
    parser.add_argument("--user", type=str, required=True, help="Jira Username/Email")
    parser.add_argument("--token", type=str, required=True, help="Jira API Token")
    
    args = parser.parse_args()

    # Initialize Toolkit
    # This Toolkit provides multiple methods (GetIssue, TransitionIssue, etc.)
    # The SimpleMCPServer will register all of them automatically.
    jira_tools = JiraToolkit(
        server_url=args.jira_url,
        username=args.user,
        token=args.token,
        auth_type="token_auth"
    )

    # Auth configuration
    auth_method = "none"
    if args.api_key:
        auth_method = "api_key"

    print(f"Starting Jira MCP Server on port {args.port}...")
    
    # Start the Server
    server = SimpleMCPServer(
        tool=jira_tools,  # Passing the Toolkit instance directly
        name="JiraMCP",
        port=args.port,
        transport=args.transport,
        auth_method=auth_method,
        api_key=args.api_key
    )
    
    server.run()

if __name__ == "__main__":
    main()
