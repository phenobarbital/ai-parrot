---
kind: inline
jira_key: null
fetched_at: 2026-06-10T00:00:00Z
summary_oneline: Expand AnthropicClient to support AWS Bedrock and AWS-native (workspace) backends
---

# AnthropicClient expansion

La API nativa de Anthropic soporta usar AWS Bedrock y AWS Native:

```python
from anthropic import AnthropicBedrock

client = AnthropicBedrock(
    # Si no pasas claves, usa la cadena estándar de credenciales de AWS
    # (~/.aws/credentials o las variables AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
    aws_access_key="<access key>",
    aws_secret_key="<secret key>",
    aws_session_token="<session_token>",  # opcional, para credenciales temporales
    aws_region="us-east-1",               # por defecto lee AWS_REGION
)
```

y AWS:

```python
from anthropic import AnthropicAWS

client = AnthropicAWS(api_key=os.environ["ANTHROPIC_API_KEY"], aws_workspace_id=, aws_region="us-east-1")
```

Instalable via:

```
uv pip install -U "anthropic[aws]"
```

Con la diferencia de que el modelo en AnthropicAWS es de tipo sin prefijo
("claude-fable-5") y en Bedrock usa IDs de tipo ARN (habría que hacer una clase
que convierta de uno en otro).

Las credenciales deberían leerse primero desde parrot.conf, de ser nulas, se usan
desde environment (ej: ANTHROPIC_API_KEY o ANTHROPIC_AWS_WORKSPACE_ID).
