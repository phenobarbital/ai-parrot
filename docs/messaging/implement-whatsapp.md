# WhatsApp Integration - Resumen de Implementación

## 📋 Resumen Ejecutivo

He implementado una integración completa de WhatsApp para AI-Parrot que te permite:

1. **Enviar mensajes** desde agentes usando `WhatsAppTool`
2. **Recibir mensajes** como comandos usando `WhatsAppHook`
3. **Generar QR** para autenticación web (sin necesidad de Facebook App)
4. **Integrar** fácilmente con tu `AutonomousOrchestrator` existente

## 🏗️ Arquitectura Implementada

```
┌─────────────────────────────────────────────────────────┐
│  AI-Parrot (Python/aiohttp)                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ WhatsAppTool │  │ WhatsAppHook │  │ Orchestrator │  │
│  │ (Enviar)     │  │ (Recibir)    │  │ Hook         │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │ HTTP              │ Redis            │         │
└─────────┼───────────────────┼──────────────────┼─────────┘
          │                   │                  │
          ▼                   ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│  WhatsApp Bridge (Go/whatsmeow)                         │
│  • Gestión de sesión persistente (SQLite)               │
│  • Autenticación QR (web + terminal)                    │
│  • WebSocket para QR en tiempo real                     │
│  • HTTP API para envío de mensajes                      │
│  • Redis Pub/Sub para mensajes entrantes                │
└─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  WhatsApp (usando protocolo oficial)                    │
└─────────────────────────────────────────────────────────┘
```

## 📁 Archivos Creados

### 1. **Infraestructura Go (WhatsApp Bridge)**
```
services/whatsapp-bridge/
├── main.go              # Implementación completa del bridge
├── go.mod               # Dependencias Go
├── Dockerfile           # Imagen Docker multi-stage
└── README.md
```

**Características del Bridge:**
- ✅ Autenticación QR con interfaz web
- ✅ Sesión persistente en SQLite
- ✅ WebSocket para updates en tiempo real
- ✅ REST API para enviar mensajes
- ✅ Redis Pub/Sub para mensajes entrantes
- ✅ Soporte para texto, imágenes, videos, documentos
- ✅ Health check endpoint
- ✅ Manejo de grupos

### 2. **Python Integration (AI-Parrot)**

```
parrot/
├── tools/messaging/
│   └── whatsapp.py      # WhatsAppTool - Enviar mensajes
├── hooks/
│   └── whatsapp.py      # WhatsAppHook & WhatsAppOrchestratorHook
└── conf/
    └── whatsapp.py      # Configuración

examples/
└── whatsapp_integration.py  # 5 ejemplos completos
```

**Características Python:**
- ✅ `WhatsAppTool`: Tool para enviar mensajes desde agentes
- ✅ `WhatsAppHook`: Hook para recibir mensajes (similar a webhooks)
- ✅ `WhatsAppOrchestratorHook`: Router multi-agente
- ✅ Filtrado por número de teléfono
- ✅ Filtrado por grupos
- ✅ Prefijos de comando configurables
- ✅ Auto-reply opcional
- ✅ Callbacks personalizados

### 3. **Build & Deploy**

```
Makefile                 # Comandos make para install/build/run
docker-compose.yml       # Stack completo (Redis + Bridge + AI-Parrot)
scripts/
└── whatsapp-quickstart.sh  # Script de inicio rápido
```

### 4. **Documentación**

```
docs/
└── WHATSAPP.md          # Guía completa de uso
```

## 🚀 Instalación y Uso

### Opción 1: Local

```bash
# 1. Instalar Go
make install-go

# 2. Construir bridge
make build-whatsapp-bridge

# 3. Ejecutar
make run-whatsapp-bridge

# 4. Autenticar
# Abrir http://localhost:8765/qr
# Escanear QR con WhatsApp
```

### Opción 2: Docker (Recomendado)

```bash
# Todo en un comando
docker-compose up -d

# Ver logs y obtener QR
docker-compose logs -f whatsapp-bridge

# O visitar http://localhost:8765/qr
```

### Opción 3: Script Rápido

```bash
./scripts/whatsapp-quickstart.sh
# Elige opción 1 (local) o 2 (Docker)
```

## 💡 Casos de Uso Implementados

### 1. **Agent que envía mensajes**

```python
from parrot.tools.messaging.whatsapp import WhatsAppTool

agent.tool_manager.add_tool(WhatsAppTool())

# El agente puede ahora:
await agent.ask("Envía un WhatsApp a +14155552671 diciendo que el reporte está listo")
```

### 2. **Agent que recibe comandos via WhatsApp**

```python
from parrot.hooks.whatsapp import WhatsAppHook

hook = WhatsAppHook(
    agent=my_agent,
    allowed_phones=["14155552671"],  # Solo este número
    command_prefix="!",  # Requiere ! al inicio
    auto_reply=True
)
await hook.start()

# Ahora envía desde WhatsApp:
# "!analiza las ventas de Q4"
```

### 3. **Multi-Agent Router por WhatsApp**

```python
from parrot.hooks.whatsapp import WhatsAppOrchestratorHook

hook = WhatsAppOrchestratorHook(orchestrator, default_agent)

# Routing por palabras clave
hook.register_route("sales", sales_agent, keywords=["precio", "compra"])
hook.register_route("soporte", support_agent, keywords=["ayuda", "error"])

# Routing por teléfono (VIP)
hook.register_route("vip", vip_agent, phones=["14155551234"])

await hook.start()
```

### 4. **Integración con AutonomousOrchestrator existente**

```python
# Si ya tienes webhooks, MQTT, RabbitMQ...
from parrot.hooks.whatsapp import WhatsAppHook

# Solo agrega WhatsApp como otro canal:
whatsapp_hook = WhatsAppHook(
    agent=orchestrator,
    command_prefix="/",
    auto_reply=True
)
await whatsapp_hook.start()

# Ahora el orchestrator recibe comandos de:
# - WhatsApp ✅
# - Webhooks ✅
# - MQTT ✅
# - RabbitMQ ✅
```

## 🔧 Configuración

### Variables de Entorno

```bash
# .env
WHATSAPP_BRIDGE_ENABLED=true
WHATSAPP_BRIDGE_URL=http://localhost:8765
REDIS_SERVICES_URL=redis://localhost:6379

# Seguridad (opcional)
WHATSAPP_ALLOWED_PHONES=14155552671,34612345678
WHATSAPP_ALLOWED_GROUPS=MiGrupo,OtroGrupo
WHATSAPP_COMMAND_PREFIX=!
```

### En `parrot/conf/__init__.py`

Agrega este snippet (ya está en `parrot/conf/whatsapp_config_snippet.py`):

```python
# WhatsApp Bridge Configuration
WHATSAPP_BRIDGE_ENABLED = config.getboolean('WHATSAPP_BRIDGE_ENABLED', fallback=True)
WHATSAPP_BRIDGE_URL = config.get('WHATSAPP_BRIDGE_URL', fallback='http://localhost:8765')
# ... (ver archivo completo)
```

## 🎯 Ventajas de esta Implementación

### vs. wacli (OpenClaw)
- ✅ **Mismo flujo de autenticación** (QR simple)
- ✅ **Integración nativa** en Python con tu arquitectura
- ✅ **Bidireccional** desde el inicio
- ✅ **Escalable** (múltiples instancias de AI-Parrot, un solo bridge)

### vs. pywa (Facebook API)
- ✅ **Sin Facebook App** necesaria
- ✅ **Sin aprobación** requerida
- ✅ **Setup en minutos** vs. días/semanas
- ✅ **Gratis** (no hay límites de API)

### vs. whatsapp-web.py (Selenium)
- ✅ **Más rápido** (no necesita navegador)
- ✅ **Más robusto** (whatsmeow es muy estable)
- ✅ **Menos recursos** (Go es más eficiente)
- ✅ **Mejor para producción**

## 📊 Flujo de Mensajes

### Mensaje Entrante (WhatsApp → Agent)

```
Usuario envía WhatsApp
        ↓
WhatsApp Bridge (whatsmeow)
        ↓
Redis Pub/Sub (channel: whatsapp:messages)
        ↓
WhatsAppHook (Python)
        ↓
Agent.ask() procesa mensaje
        ↓
Agent genera respuesta
        ↓
WhatsAppTool envía respuesta
        ↓
Bridge → WhatsApp
        ↓
Usuario recibe respuesta
```

### Mensaje Saliente (Agent → WhatsApp)

```
Agent decide enviar mensaje
        ↓
WhatsAppTool.execute(phone, message)
        ↓
HTTP POST a /send
        ↓
WhatsApp Bridge
        ↓
whatsmeow envía
        ↓
Usuario recibe
```

## 🔐 Autenticación

1. **Primera vez**: Escanea QR en http://localhost:8765/qr
2. **Sesión guardada** en `data/whatsapp/whatsapp.db`
3. **No requiere re-escaneo** en reinicio
4. **Persistente** incluso en Docker (con volumen montado)

## 🐛 Troubleshooting

### Bridge no conecta
```bash
# Ver logs
docker-compose logs -f whatsapp-bridge

# O si es local
./bin/whatsapp-bridge
```

### Mensajes no llegan al agent
```bash
# Verificar Redis Pub/Sub
redis-cli SUBSCRIBE whatsapp:messages

# Verificar que el hook esté corriendo
# (debe aparecer log: "WhatsApp hook started for agent 'X'")
```

### QR no aparece
```bash
# Verificar que el bridge esté corriendo
curl http://localhost:8765/health

# Debe responder con:
# {"success":true,"data":{"connected":false,"authenticated":false,"logged_in":false}}
```

## 📝 Próximos Pasos

1. **Revisar el código** en los archivos generados
2. **Probar localmente** con `make run-whatsapp-bridge`
3. **Autenticar** escaneando QR
4. **Ejecutar ejemplos** en `examples/whatsapp_integration.py`
5. **Integrar** con tus agentes existentes

## 📚 Archivos a Revisar

1. `docs/WHATSAPP.md` - Documentación completa
2. `examples/whatsapp_integration.py` - 5 ejemplos de uso
3. `services/whatsapp-bridge/main.go` - Implementación del bridge
4. `parrot/tools/messaging/whatsapp.py` - Tool para enviar
5. `parrot/hooks/whatsapp.py` - Hooks para recibir
6. `Makefile` - Comandos de build/install
7. `docker-compose.yml` - Stack completo

## 🎉 ¡Listo para Usar!

```bash
# Opción más rápida:
./scripts/whatsapp-quickstart.sh

# O manualmente:
make install-go
make build-whatsapp-bridge
make run-whatsapp-bridge

# Luego:
# 1. Abre http://localhost:8765/qr
# 2. Escanea QR con WhatsApp
# 3. Ejecuta tus agentes
```

---

**¿Preguntas?** Revisa `docs/WHATSAPP.md` para más detalles.