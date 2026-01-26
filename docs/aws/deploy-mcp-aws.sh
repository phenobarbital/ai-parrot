#!/bin/bash
# =============================================================================
# deploy-mcp-aws.sh - Deploy MCP Server to AWS
# =============================================================================
# Este script ayuda a desplegar el MCP Server en App Runner o Fargate
#
# Uso:
#   ./deploy-mcp-aws.sh apprunner   # Desplegar en App Runner
#   ./deploy-mcp-aws.sh fargate     # Desplegar en Fargate
#   ./deploy-mcp-aws.sh ecr         # Solo push a ECR
# =============================================================================

set -e

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ECR_REPO_NAME="${ECR_REPO_NAME:-jira-mcp-server}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
SERVICE_NAME="${SERVICE_NAME:-jira-mcp-server}"

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ─────────────────────────────────────────────────────────────────────────────
# Functions
# ─────────────────────────────────────────────────────────────────────────────

create_ecr_repo() {
    log_info "Creating ECR repository: ${ECR_REPO_NAME}"
    aws ecr describe-repositories --repository-names "${ECR_REPO_NAME}" 2>/dev/null || \
    aws ecr create-repository \
        --repository-name "${ECR_REPO_NAME}" \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256
}

build_and_push() {
    log_info "Building Docker image..."
    docker build -f Dockerfile.jira -t "${ECR_REPO_NAME}:${IMAGE_TAG}" .

    log_info "Logging into ECR..."
    aws ecr get-login-password --region "${AWS_REGION}" | \
        docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

    log_info "Tagging and pushing image..."
    docker tag "${ECR_REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
    docker push "${ECR_URI}:${IMAGE_TAG}"
    
    log_info "Image pushed: ${ECR_URI}:${IMAGE_TAG}"
}

create_secrets() {
    log_info "Creating Secrets Manager secret..."
    
    # Check if secret exists
    if aws secretsmanager describe-secret --secret-id "jira-mcp/config" 2>/dev/null; then
        log_warn "Secret already exists. Use AWS console to update values."
        return
    fi
    
    # Create secret (placeholder values - update via console)
    aws secretsmanager create-secret \
        --name "jira-mcp/config" \
        --description "Jira MCP Server credentials" \
        --secret-string '{
            "JIRA_INSTANCE": "https://your-instance.atlassian.net",
            "JIRA_USERNAME": "your@email.com",
            "JIRA_API_TOKEN": "your-token",
            "JIRA_PROJECT": "PROJ"
        }'
    
    log_warn "Secret created with placeholder values. Update via AWS Console!"
}

deploy_apprunner() {
    log_info "Deploying to App Runner..."
    
    # Create App Runner service
    aws apprunner create-service \
        --service-name "${SERVICE_NAME}" \
        --source-configuration "{
            \"ImageRepository\": {
                \"ImageIdentifier\": \"${ECR_URI}:${IMAGE_TAG}\",
                \"ImageRepositoryType\": \"ECR\",
                \"ImageConfiguration\": {
                    \"Port\": \"8080\",
                    \"RuntimeEnvironmentVariables\": {
                        \"ENVIRONMENT\": \"production\",
                        \"MCP_TRANSPORT\": \"http\"
                    }
                }
            },
            \"AutoDeploymentsEnabled\": true,
            \"AuthenticationConfiguration\": {
                \"AccessRoleArn\": \"arn:aws:iam::${AWS_ACCOUNT_ID}:role/AppRunnerECRAccessRole\"
            }
        }" \
        --instance-configuration "{
            \"Cpu\": \"0.25 vCPU\",
            \"Memory\": \"0.5 GB\"
        }" \
        --health-check-configuration "{
            \"Protocol\": \"HTTP\",
            \"Path\": \"/\",
            \"Interval\": 10,
            \"Timeout\": 5,
            \"HealthyThreshold\": 1,
            \"UnhealthyThreshold\": 5
        }"
    
    log_info "App Runner service created. Check AWS Console for URL."
}

deploy_fargate() {
    log_info "Deploying to Fargate..."
    
    # Substitute variables in task definition
    envsubst < aws/fargate-task-definition.json > /tmp/task-def.json
    
    # Register task definition
    aws ecs register-task-definition --cli-input-json file:///tmp/task-def.json
    
    log_info "Task definition registered."
    log_warn "Next steps:"
    log_warn "  1. Create ECS Cluster (if not exists)"
    log_warn "  2. Create ECS Service with ALB"
    log_warn "  3. Configure Security Groups"
    
    echo ""
    echo "Manual commands:"
    echo "  aws ecs create-cluster --cluster-name mcp-cluster"
    echo "  aws ecs create-service --cluster mcp-cluster --service-name ${SERVICE_NAME} \\"
    echo "    --task-definition ${SERVICE_NAME} --desired-count 1 --launch-type FARGATE \\"
    echo "    --network-configuration 'awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}'"
}

show_help() {
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  ecr        - Create ECR repo and push image"
    echo "  secrets    - Create Secrets Manager secret"
    echo "  apprunner  - Deploy to App Runner (includes ECR push)"
    echo "  fargate    - Deploy to Fargate (includes ECR push)"
    echo "  help       - Show this help"
    echo ""
    echo "Environment variables:"
    echo "  AWS_REGION      - AWS region (default: us-east-1)"
    echo "  AWS_ACCOUNT_ID  - AWS account ID (auto-detected)"
    echo "  ECR_REPO_NAME   - ECR repository name (default: jira-mcp-server)"
    echo "  IMAGE_TAG       - Docker image tag (default: latest)"
    echo "  SERVICE_NAME    - Service name (default: jira-mcp-server)"
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

case "${1:-help}" in
    ecr)
        create_ecr_repo
        build_and_push
        ;;
    secrets)
        create_secrets
        ;;
    apprunner)
        create_ecr_repo
        build_and_push
        create_secrets
        deploy_apprunner
        ;;
    fargate)
        create_ecr_repo
        build_and_push
        create_secrets
        deploy_fargate
        ;;
    help|*)
        show_help
        ;;
esac