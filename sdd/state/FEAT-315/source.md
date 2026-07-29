---
kind: inline
jira_key: null
fetched_at: 2026-07-17T00:00:00Z
summary_oneline: Refactor NovaSonicClient into a unified NovaClient covering all Amazon Nova models (text, voice, image, video)
---

# novaclient-amazon-aws

Actualmente se creó un cliente llamado `NovaSonicClient` con fallback a Nova
text en algunos casos. La idea es hacer un refactor al estilo del cliente de
Google (`parrot/clients/google/client.py`) y llamarlo **NovaClient**, para la
cobertura de todos los modelos Nova:

- **Texto**: Nova 2 Lite, Nova Micro, Nova Pro, Nova Premier
- **Voz (speech-to-speech)**: Nova Sonic
- **Video**: Nova Reel
- **Imagen**: Nova Canvas

## Estructura propuesta (espejo del cliente Google)

- `parrot/clients/nova/client.py` — métodos `ask()`, `ask_stream()`, `invoke()`
  cubriendo los modelos de texto (Nova 2 Lite, Micro, Premier).
- `parrot/clients/nova/audio.py` — métodos de stream de voz (Nova Sonic),
  basados en la API `InvokeModelWithBidirectionalStream`:
  https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModelWithBidirectionalStream.html
- `parrot/clients/nova/generation.py` — generación de imagen/video
  (Nova Canvas, Nova Reel), igual que Google.

Así un único cliente se usa para distintos modos, en lugar de múltiples
clientes separados.

## Conexión / credenciales

Pedir credenciales explícitas o usar desde `parrot.conf` la variable
`AWS_CREDENTIALS` con un `aws_id` (tal como lo hace el Bedrock client).
