# AI-Parrot MCP Server - AWS Deployment Guide

## Resumen

Este directorio contiene todo lo necesario para desplegar un **SimpleMCPServer** de AI-Parrot en AWS, ya sea usando **App Runner** o **Fargate**.

## Estructura de Archivos

```
.
├── Dockerfile              # Imagen base genérica para cualquier toolkit
├── Dockerfile.jira         # Imagen específica para Jira MCP Server
├── docker-compose.yml      # Testing local
├── deploy-mcp-aws.sh       # Script de despliegue automatizado
└── aws/
    ├── apprunner.yaml              # Configuración App Runner (source-based)
    └── fargate-task-definition.json # Task definition para Fargate/ECS
```

## Opción 1: App Runner (Recomendado para empezar)

### Ventajas
- Setup más simple (menos configuración de networking)
- Auto-scaling incluido
- TLS/HTTPS automático
- Pausable cuando no hay tráfico (ahorra costos)
- ~$5-15/mes para uso ligero

### Despliegue Rápido

```bash
# 1. Configurar variables
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 2. Ejecutar deploy
chmod +x deploy-mcp-aws.sh
./deploy-mcp-aws.sh apprunner
```

### Despliegue Manual

```bash
# 1. Crear repositorio ECR
aws ecr create-repository --repository-name jira-mcp-server

# 2. Build y push
docker build -f Dockerfile.jira -t jira-mcp-server .
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com
docker tag jira-mcp-server:latest ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/jira-mcp-server:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/jira-mcp-server:latest

# 3. Crear servicio en App Runner (via consola es más fácil la primera vez)
# https://console.aws.amazon.com/apprunner
```

### Configurar Variables de Entorno en App Runner

En la consola de App Runner, configurar:

| Variable | Descripción |
|----------|-------------|
| `JIRA_INSTANCE` | URL de Jira (ej: `https://company.atlassian.net`) |
| `JIRA_USERNAME` | Email del usuario |
| `JIRA_API_TOKEN` | Token de API de Jira |
| `JIRA_PROJECT` | Proyecto por defecto (opcional) |
| `MCP_API_KEY` | API key para autenticar clientes MCP (opcional) |

## Opción 2: Fargate/ECS

### Ventajas
- Más control sobre networking y configuración
- Mejor para producción enterprise
- Integración con ALB para load balancing
- VPC privada posible

### Despliegue

```bash
# 1. Build y push a ECR
./deploy-mcp-aws.sh ecr

# 2. Crear secret en Secrets Manager
./deploy-mcp-aws.sh secrets

# 3. Editar el secret con valores reales
aws secretsmanager update-secret --secret-id jira-mcp/config --secret-string '{
    "JIRA_INSTANCE": "https://real-instance.atlassian.net",
    "JIRA_USERNAME": "real@email.com",
    "JIRA_API_TOKEN": "real-token",
    "JIRA_PROJECT": "PROJ"
}'

# 4. Registrar task definition
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
envsubst < aws/fargate-task-definition.json > /tmp/task-def.json
aws ecs register-task-definition --cli-input-json file:///tmp/task-def.json

# 5. Crear cluster y servicio (si no existen)
aws ecs create-cluster --cluster-name mcp-cluster

# 6. Crear servicio (requiere VPC, subnets, security groups)
aws ecs create-service \
    --cluster mcp-cluster \
    --service-name jira-mcp-server \
    --task-definition jira-mcp-server \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```

## Testing Local

```bash
# 1. Crear archivo .env
cat > .env << EOF
JIRA_INSTANCE=https://your-instance.atlassian.net
JIRA_USERNAME=your@email.com
JIRA_API_TOKEN=your-api-token
JIRA_PROJECT=PROJ
EOF

# 2. Ejecutar con docker-compose
docker compose up --build

# 3. Probar
curl http://localhost:8080/
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## Comparativa

| Aspecto | App Runner | Fargate |
|---------|------------|---------|
| **Setup inicial** | ⭐⭐⭐ Muy fácil | ⭐⭐ Más configuración |
| **Costo mínimo** | ~$5/mes (pause) | ~$10/mes (siempre on) |
| **Auto-scaling** | Automático | Configurable |
| **HTTPS/TLS** | Incluido | Requiere ACM + ALB |
| **VPC privada** | No soportado | ✅ Sí |
| **SSE support** | ✅ Sí | ✅ Sí |
| **WebSocket** | ❌ No | ✅ Sí (con ALB) |

## Notas Importantes

### Sobre SSE en AWS

Tanto App Runner como Fargate soportan **Server-Sent Events (SSE)**, pero:

- **App Runner**: Timeout máximo de conexión de 120 segundos por defecto (configurable hasta 300s)
- **Fargate + ALB**: Idle timeout configurable (hasta 4000 segundos)

Para sesiones SSE largas, Fargate con ALB es mejor opción.

### Sobre Lambda

**No recomendado** para MCP Servers con SSE porque:
- Lambda tiene timeout máximo de 15 minutos
- No mantiene conexiones persistentes
- El modelo request-response no es ideal para SSE

Si solo necesitas **HTTP transport** (stateless JSON-RPC), Lambda + API Gateway es viable con un adapter específico.

### Seguridad

1. **Siempre** usar Secrets Manager para credenciales
2. Configurar **security groups** restrictivos en Fargate
3. Habilitar **MCP_API_KEY** para autenticar clientes
4. Usar **HTTPS** (automático en App Runner, requiere ACM en Fargate)

## Crear Otros MCP Servers

Para crear un MCP server con otro toolkit (ej: O365, SharePoint):

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

Y modificar el Dockerfile para usar ese script.