---
kind: inline
jira_key: null
fetched_at: 2026-07-17T00:00:00Z
summary_oneline: Refactor NovaSonicClient into a unified NovaClient (parrot/clients/nova/) covering all Amazon Nova models, styled after the Google client package
---

# novaclient-amazon-aws

Actualmente se creo un cliente llamado `NovaSonicClient` con fallback a Nova text
en algunos casos. La idea es hacer un refactor al estilo del cliente de google
`parrot/clients/google/client.py` y llamarlo `NovaClient`, para la cobertura de
todos los modelos Nova: Nova 2 Lite, Sonic, Premier, Micro o Pro, Nova Reel,
Nova Canvas.

Al igual que google, los metodos de generación (imagen/video) podrían ir a
`parrot/clients/nova/generation.py`, permitiendo que un único cliente se use
para distintos modos en vez de tener múltiples clientes separados.

- Métodos de stream voice en `parrot/clients/nova/audio.py`, documentados en:
  https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModelWithBidirectionalStream.html
  (InvokeModelWithBidirectionalStream)
- Métodos `ask()` / `ask_stream()` / `invoke()` en `parrot/clients/nova/client.py`
  cubriendo los modelos de texto: Nova 2 Lite, Micro y Premier.
- Para conexión: pide las credenciales o usa desde `parrot.conf` la variable
  `AWS_CREDENTIALS` con un `aws_id` (tal como el Bedrock client).
