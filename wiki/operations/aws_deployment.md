---
title: "AI Parrot MCP Server AWS Deployment Guide"
---

# AI-Parrot MCP Server - AWS Deployment Guide

## Overview

This directory contains everything needed to deploy an AI-Parrot **SimpleMCPServer** on AWS, using either **App Runner** or **Fargate**.

## File Structure

```
.
├── Dockerfile              # Generic base image for any toolkit
├── Dockerfile.jira         # Image specific to the Jira MCP Server
├── docker-compose.yml      # Local testing
├── deploy-mcp-aws.sh       # Automated deployment script
└── aws/
    ├── apprunner.yaml              # App Runner configuration (source-based)
    └── fargate-task-definition.json # Task definition for Fargate/ECS
```

## Option 1: App Runner (Recommended to get started)

### Advantages
- Simplest setup (less networking configuration)
- Auto-scaling included
- Automatic TLS/HTTPS
- Pausable when there is no traffic (saves costs)
- ~$5-15/month for light usage

### Quick Deployment

```bash
# 1. Configure variables
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 2. Run the deploy
chmod +x deploy-mcp-aws.sh
./deploy-mcp-aws.sh apprunner
```

### Manual Deployment

```bash
# 1. Create the ECR repository
aws ecr create-repository --repository-name jira-mcp-server

# 2. Build and push
docker build -f Dockerfile.jira -t jira-mcp-server .
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com
docker tag jira-mcp-server:latest ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/jira-mcp-server:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/jira-mcp-server:latest

# 3. Create the service in App Runner (easier via the console the first time)
# https://console.aws.amazon.com/apprunner
```

### Configure Environment Variables in App Runner

In the App Runner console, set:

| Variable | Description |
|----------|-------------|
| `JIRA_INSTANCE` | Jira URL (e.g. `https://company.atlassian.net`) |
| `JIRA_USERNAME` | User email |
| `JIRA_API_TOKEN` | Jira API token |
| `JIRA_PROJECT` | Default project (optional) |
| `MCP_API_KEY` | API key to authenticate MCP clients (optional) |

## Option 2: Fargate/ECS

### Advantages
- More control over networking and configuration
- Better for enterprise production
- ALB integration for load balancing
- Private VPC possible

### Deployment

```bash
# 1. Build and push to ECR
./deploy-mcp-aws.sh ecr

# 2. Create the secret in Secrets Manager
./deploy-mcp-aws.sh secrets

# 3. Edit the secret with real values
aws secretsmanager update-secret --secret-id jira-mcp/config --secret-string '{
    "JIRA_INSTANCE": "https://real-instance.atlassian.net",
    "JIRA_USERNAME": "real@email.com",
    "JIRA_API_TOKEN": "real-token",
    "JIRA_PROJECT": "PROJ"
}'

# 4. Register the task definition
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
envsubst < aws/fargate-task-definition.json > /tmp/task-def.json
aws ecs register-task-definition --cli-input-json file:///tmp/task-def.json

# 5. Create the cluster and service (if they do not exist)
aws ecs create-cluster --cluster-name mcp-cluster

# 6. Create the service (requires VPC, subnets, security groups)
aws ecs create-service \
    --cluster mcp-cluster \
    --service-name jira-mcp-server \
    --task-definition jira-mcp-server \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```

## Local Testing

```bash
# 1. Create the .env file
cat > .env << EOF
JIRA_INSTANCE=https://your-instance.atlassian.net
JIRA_USERNAME=your@email.com
JIRA_API_TOKEN=your-api-token
JIRA_PROJECT=PROJ
EOF

# 2. Run with docker-compose
docker compose up --build

# 3. Test
curl http://localhost:8080/
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## Comparison

| Aspect | App Runner | Fargate |
|--------|------------|---------|
| **Initial setup** | ⭐⭐⭐ Very easy | ⭐⭐ More configuration |
| **Minimum cost** | ~$5/month (paused) | ~$10/month (always on) |
| **Auto-scaling** | Automatic | Configurable |
| **HTTPS/TLS** | Included | Requires ACM + ALB |
| **Private VPC** | Not supported | ✅ Yes |
| **SSE support** | ✅ Yes | ✅ Yes |
| **WebSocket** | ❌ No | ✅ Yes (with ALB) |

## Important Notes

### About SSE on AWS

Both App Runner and Fargate support **Server-Sent Events (SSE)**, but:

- **App Runner**: Maximum connection timeout of 120 seconds by default (configurable up to 300s)
- **Fargate + ALB**: Configurable idle timeout (up to 4000 seconds)

For long SSE sessions, Fargate with ALB is the better option.

### About Lambda

**Not recommended** for MCP Servers with SSE because:
- Lambda has a maximum timeout of 15 minutes
- It does not keep persistent connections
- The request-response model is not ideal for SSE

If you only need **HTTP transport** (stateless JSON-RPC), Lambda + API Gateway is viable with a specific adapter.

### Security

1. **Always** use Secrets Manager for credentials
2. Configure restrictive **security groups** on Fargate
3. Enable **MCP_API_KEY** to authenticate clients
4. Use **HTTPS** (automatic on App Runner, requires ACM on Fargate)

## Creating Other MCP Servers

To create an MCP server with another toolkit (e.g. O365, SharePoint):

```python
# start_o365_mcp.py
from parrot.services.mcp.simple import SimpleMCPServer
from parrot.tools.o365toolkit import O365Toolkit

tools = O365Toolkit(
    client_id=os.environ["O365_CLIENT_ID"],
    client_secret=os.environ["O365_CLIENT_SECRET"],
    tenant_id=os.environ["O365_TENANT_ID"],
)

server = SimpleMCPServer(
    tool=tools,
    name="O365MCP",
    port=8080,
    transport="http",
)
server.run()
```

And modify the Dockerfile to use that script.