---
type: Wiki Overview
title: 'Feature Specification: ai-parrot-integrations'
id: doc:sdd-specs-ai-parrot-integrations-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: fuente y, vía sus dependencias, arrastra al core de ai-parrot SDKs
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.auth.oauth2.service
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.core
  rel: mentions
- concept: mod:parrot.integrations.manager
  rel: mentions
- concept: mod:parrot.integrations.matrix.client
  rel: mentions
- concept: mod:parrot.integrations.matrix.hook
  rel: mentions
- concept: mod:parrot.integrations.models
  rel: mentions
- concept: mod:parrot.integrations.slack.wrapper
  rel: mentions
- concept: mod:parrot.integrations.telegram.combined_callback
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
- concept: mod:parrot.loaders
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot_tools.zoom
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: ai-parrot-integrations

**Feature ID**: FEAT-202
**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.1.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot/src/parrot/integrations/` pesa ~1.6 MB en código
fuente y, vía sus dependencias, arrastra al core de ai-parrot SDKs
de mensajería pesados que no se necesitan en deployments CLI o de
agentes que solo usan un canal puntual:

- `pywa` (WhatsApp) está declarado en **BASE deps** de `ai-parrot`
  (`packages/ai-parrot/pyproject.toml:83`).
- `aiogram` (Telegram) viene como **transitivo de `async-notify[default]`**
  que también está en BASE deps (`packages/ai-parrot/pyproject.toml:82`).
- `azure-teambots` está en extra `[integrations]` mezclado con
  `querysource` y `async-notify[all]`.
- `mautrix` + `python-olm` viven en extra `[matrix]` separado.

Además, hay tres acoplamientos que cruzan el límite hacia
`parrot.integrations`:

1. **`parrot/core/hooks/matrix.py`** importa `MatrixClientWrapper`
   directamente — coupling inverso del core a un canal.
2. **`parrot/manager/manager.py::BotManager`** y
   **`parrot/autonomous/orchestrator.py`** importan
   `IntegrationBotManager` (lazy, dentro de función).
3. **`parrot/auth/{routes,oauth2_routes}`,
   `parrot/handlers/{integrations,user_objects}`,
   `parrot/manager/manager.py`** consumen `integrations/oauth2/`
   (5 archivos de producción).

**Quién está afectado**:
- Operadores que instalan `ai-parrot` para un agente CLI o un servidor
  sin canales — pagan instalación de `pywa`/`aiogram`/SDKs sin usarlos.
- Quienes solo usan un canal — instalan todos los SDKs.
- El equipo, porque cualquier cambio en `parrot/integrations/` requiere
  publicar versión completa de `ai-parrot` (sin granularidad de release).

### Goals

- Extraer los 5 canales de mensajería (slack, telegram, msteams,
  whatsapp, matrix) + piezas comunes a un paquete satélite
  `ai-parrot-integrations` con extras granulares por canal.
- Preservar todos los import paths (`from parrot.integrations.X import Y`)
  via PEP 420 namespace extension — cero breaking changes para
  consumidores que instalen el paquete correcto.
- Eliminar `pywa` y reducir `async-notify` transitivos de BASE deps
  del core.
- Reubicar `integrations/oauth2/` a `parrot/auth/oauth2/` (trasciende
  canales; es infraestructura de autenticación genérica).
- Mover `parrot/voice/` completo al nuevo paquete (cero consumers
  fuera de integrations).
- Mover `parrot/human/channels/` al nuevo paquete con un registry en
  core para auto-discovery.
- Mover `parrot/integrations/zoom/` a `ai-parrot-tools` (no es un bot
  de mensajería; su único consumer real es `zoomtoolkit.py`).
- Refactorizar `parrot/core/hooks/matrix.py` a interface pluggable
  (`MessagingHook`) + registro externo desde el paquete satélite.
- Limpieza de `packages/ai-parrot/pyproject.toml`: deps BASE, extras
  reorganizadas, meta-extra `[messaging]` que aliasa al nuevo paquete.

### Non-Goals (explicitly out of scope)

- **No mover `BotManager`** (`parrot/manager/manager.py`) — queda en
  `ai-parrot` (lo consumen ~22 sitios en handlers/autonomous/auth/bots).
  Decisión explícita del usuario.
- **No reescribir wrappers de canales** — la extracción es puramente de
  packaging. Lógica de canales se mueve byte-idéntica.
- **No tocar `parrot.bots` ni `parrot.conf`** — fuera de scope.
- Runtime fallback-on-failure fue descartado en brainstorm
  (ver `sdd/proposals/ai-parrot-integrations.brainstorm.md` Option C).

---

## 2. Architectural Design

### Overview

Nuevo paquete satélite `packages/ai-parrot-integrations/` que contribuye
submódulos bajo el namespace existente `parrot.integrations.*` vía
`pkgutil.extend_path` (la convención que ya está en
`parrot/__init__.py:9-12`). Un solo PR (big-bang) mueve los 5 canales
(slack, telegram, msteams, whatsapp, matrix) + voice + human/channels
+ refactor del hook matrix + traslado de oauth2 a `parrot/auth/oauth2/`
+ traslado de zoom a `ai-parrot-tools`.

**Estrategia de namespace**: PEP 420 (consistente con FEAT-201
ai-parrot-embeddings). Los consumidores siguen importando
`from parrot.integrations.X import Y` sin cambios. El layout del nuevo
paquete NO incluye `parrot/__init__.py` propio en `src/` para que
`extend_path` funcione correctamente.

**Instalación granular resultante**:
```bash
pip install ai-parrot                                # core agentes/CLI, ~80MB menos
pip install ai-parrot-integrations[slack]             # solo Slack
pip install ai-parrot-integrations[telegram,msteams]  # selectivo
pip install ai-parrot-integrations[messaging]         # combo: slack+telegram+msteams+whatsapp
pip install ai-parrot-integrations[all]               # todos los canales + voice
```

### Component Diagram

```
packages/ai-parrot/                         packages/ai-parrot-integrations/
  src/parrot/                                 src/parrot/
    __init__.py (extend_path) ◄─── namespace ───► integrations/
    integrations/                                   __init__.py (lazy PEP 562)
      __init__.py (stub: error-guía)                manager.py (IntegrationBotManager)
                                                    models.py (IntegrationBotConfig)
    auth/                                           parser.py (ResponseParser)
      oauth2/  ◄── relocated from                   core/state.py
                   integrations/oauth2/              slack/
                                                    telegram/
    core/hooks/                                     msteams/
      base.py (MessagingHook Protocol) ◄── impl ──► whatsapp/
                                                    matrix/
    human/                                        voice/  (parrot.voice.*)
      __init__.py (HumanInteractionManager)       human/channels/  (parrot.human.channels.*)
      channels/
        __init__.py (ChannelRegistry)
        base.py (HumanChannel ABC)            packages/ai-parrot-tools/
                                                src/parrot_tools/
    manager/                                      zoom/  ◄── relocated from
      manager.py (BotManager — STAYS)                      integrations/zoom/
                                                  zoomtoolkit.py (imports locally)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/__init__.py` (extend_path) | uses | Enables PEP 420 namespace merging; no changes needed |
| `parrot/manager/manager.py` (BotManager) | imports from | Lazy import of `IntegrationBotManager` — works via PEP 420 |
| `parrot/autonomous/orchestrator.py` | imports from | Lazy import of `IntegrationBotManager` — works via PEP 420 |
| `parrot/auth/{routes,oauth2_routes}.py` | modifies | oauth2 imports updated to `parrot.auth.oauth2.*` |
| `parrot/handlers/{integrations,user_objects}.py` | modifies | oauth2 imports updated to `parrot.auth.oauth2.*` |
| `parrot/core/hooks/base.py` | extends | New `MessagingHook` Protocol / abstract class |
| `parrot/core/hooks/matrix.py` | removes | Replaced by pluggable hook from satellite package |
| `parrot/bots/jira_specialist.py` | imports from | `TelegramOAuthNotifier` — works via PEP 420 |
| `parrot/handlers/agent.py` | imports from | `telegram.combined_callback` — works via PEP 420 |
| `parrot_tools/zoomtoolkit.py` | modifies | Import changes to local `parrot_tools.zoom` |
| `parrot/human/__init__.py` | modifies | Lazy export of `TelegramHumanChannel` updated for PEP 420 |

### Data Models

No new Pydantic models. Existing models (`IntegrationBotConfig`,
`TelegramAgentConfig`, `MSTeamsAgentConfig`, `WhatsAppAgentConfig`,
`SlackAgentConfig`) move as-is to the satellite package.

New configuration:

```python
# packages/ai-parrot-integrations/pyproject.toml (extras)
[project.optional-dependencies]
slack = ["slack-sdk>=3.0", "slack-bolt>=1.18"]
telegram = ["aiogram>=3.12"]
msteams = ["azure-teambots>=0.1.1", "parrot-formdesigner"]
whatsapp = ["pywa>=3.8.0"]
matrix = ["mautrix>=0.20", "python-olm>=3.2.16"]
voice = ["faster-whisper", "openai"]
messaging = [
    "ai-parrot-integrations[slack]",
    "ai-parrot-integrations[telegram]",
    "ai-parrot-integrations[msteams]",
    "ai-parrot-integrations[whatsapp]",
]
all = [
    "ai-parrot-integrations[messaging]",
    "ai-parrot-integrations[matrix]",
    "ai-parrot-integrations[voice]",
]
```

### New Public Interfaces

```python
# parrot/core/hooks/base.py — new Protocol
class MessagingHook(Protocol):
    """Interface for messaging-channel hooks (e.g. matrix, telegram)."""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def on_message(self, message: Any) -> None: ...

# parrot/human/channels/__init__.py — new registry
class ChannelRegistry:
    """Discovers HumanChannel implementations from satellite packages."""
    def register(self, name: str, channel_cls: type) -> None: ...
    def get(self, name: str) -> type: ...
    def available(self) -> list[str]: ...
```

---

## 3. Module Breakdown

### Module 1: Package Scaffold
- **Path**: `packages/ai-parrot-integrations/`
- **Responsibility**: Create the satellite package structure with
  `pyproject.toml`, `src/parrot/integrations/`, extras, README.
  No `parrot/__init__.py` in `src/` (PEP 420).
- **Depends on**: none

### Module 2: Slack Channel Extraction
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/`
- **Responsibility**: Move `slack/` directory byte-identical; update
  test imports.
- **Depends on**: Module 1

### Module 3: Telegram Channel Extraction
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/`
- **Responsibility**: Move `telegram/` directory byte-identical + tests.
- **Depends on**: Module 1

### Module 4: MS Teams Channel Extraction
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`
- **Responsibility**: Move `msteams/` directory byte-identical + tests.
  Extra `[msteams]` declares `parrot-formdesigner` (resolves FEAT-199 U2).
- **Depends on**: Module 1

### Module 5: WhatsApp Channel Extraction
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/`
- **Responsibility**: Move `whatsapp/` directory byte-identical + tests.
- **Depends on**: Module 1

### Module 6: Matrix Channel Extraction
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/`
- **Responsibility**: Move `matrix/` directory byte-identical + tests +
  matrix hook implementation.
- **Depends on**: Module 1, Module 11 (hook interface)

### Module 7: Common Integrations Files
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/`
- **Responsibility**: Move `__init__.py` (lazy PEP 562), `manager.py`
  (IntegrationBotManager), `models.py` (IntegrationBotConfig),
  `parser.py` (ResponseParser), `core/state.py` (InMemoryStateStore).
  Leave a stub `__init__.py` in core with error-guía.
- **Depends on**: Module 1

### Module 8: Voice Extraction
- **Path**: `packages/ai-parrot-integrations/src/parrot/voice/`
- **Responsibility**: Move entire `parrot/voice/` to satellite under
  `parrot.voice.*` namespace.
- **Depends on**: Module 1

### Module 9: Human Channels Extraction + Registry
- **Path**: `packages/ai-parrot-integrations/src/parrot/human/channels/`
  + `packages/ai-parrot/src/parrot/human/channels/__init__.py` (registry)
- **Responsibility**: Move channel implementations (telegram.py) to
  satellite; create `ChannelRegistry` in core; keep `base.py` in core.
- **Depends on**: Module 1

### Module 10: OAuth2 Relocation
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/`
- **Responsibility**: Move `integrations/oauth2/` to `parrot/auth/oauth2/`
  in core. Update imports in the 5 production consumers:
  `auth/{routes,oauth2_routes}`, `handlers/{integrations,user_objects}`,
  `manager/manager.py`.
- **Depends on**: none (core-internal, no satellite dependency)

### Module 11: Pluggable Hooks Refactor
- **Path**: `packages/ai-parrot/src/parrot/core/hooks/`
- **Responsibility**: Define `MessagingHook` Protocol in `base.py`;
  add hook registry; remove `matrix.py` from core. Matrix hook
  implementation moves to satellite (Module 6).
- **Depends on**: none

### Module 12: Zoom Relocation to ai-parrot-tools
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/zoom/`
- **Responsibility**: Move `integrations/zoom/` to `ai-parrot-tools`;
  update `zoomtoolkit.py` to import locally.
- **Depends on**: none

### Module 13: Core pyproject.toml Cleanup
- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**: Remove `pywa` from BASE deps (line 83); evaluate
  `async-notify[default]` reduction (line 82); remove `azure-teambots`
  from `[integrations]` extra; remove `[matrix]` extra; add meta-extra
  `messaging = ["ai-parrot-integrations[messaging]"]`; update workspace
  root pyproject.
- **Depends on**: Modules 2-8 (all channels moved)

### Module 14: CHANGELOG & Documentation
- **Path**: `CHANGELOG.md`, `docs/migration/`
- **Responsibility**: Document breaking changes (deps removed from
  BASE), migration guide, updated install instructions.
- **Depends on**: Module 13

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_namespace_extension` | Module 1 | `from parrot.integrations import IntegrationBotManager` works with satellite installed |
| `test_stub_error_guia` | Module 7 | Importing channel without extra gives clear error message |
| `test_slack_wrapper_import` | Module 2 | `from parrot.integrations.slack.wrapper import SlackWrapper` works |
| `test_telegram_wrapper_import` | Module 3 | `from parrot.integrations.telegram.wrapper import TelegramWrapper` works |
| `test_msteams_import` | Module 4 | MS Teams imports functional |
| `test_whatsapp_import` | Module 5 | WhatsApp imports functional |
| `test_matrix_import` | Module 6 | Matrix imports functional |
| `test_voice_import` | Module 8 | `from parrot.voice import ...` works |
| `test_channel_registry` | Module 9 | Registry discovers TelegramHumanChannel from satellite |
| `test_oauth2_relocated` | Module 10 | `from parrot.auth.oauth2.service import IntegrationsService` works |
| `test_messaging_hook_protocol` | Module 11 | MessagingHook Protocol enforced |
| `test_zoom_in_tools` | Module 12 | `from parrot_tools.zoom import ZoomUsInterface` works |
| `test_no_pywa_in_base` | Module 13 | `pip install ai-parrot` does NOT install `pywa` |

### Integration Tests

| Test | Description |
|---|---|
| `test_botmanager_loads_integration_bots` | BotManager lazy-imports IntegrationBotManager via PEP 420 |
| `test_hook_registry_discovers_matrix` | Matrix hook auto-registers when `ai-parrot-integrations[matrix]` installed |
| `test_oauth2_routes_with_relocated` | Auth routes work with oauth2 at new location |
| `test_jira_specialist_telegram` | jira_specialist.py imports TelegramOAuthNotifier via PEP 420 |

### Test Data / Fixtures

```python
@pytest.fixture
def satellite_installed():
    """Ensure ai-parrot-integrations is importable."""
    import importlib
    importlib.import_module("parrot.integrations.manager")

@pytest.fixture
def mock_integration_config():
    from parrot.integrations.models import IntegrationBotConfig
    return IntegrationBotConfig(...)
```

---

## 5. Acceptance Criteria

- [ ] `pip install ai-parrot` does NOT install `pywa`, `aiogram`,
      `azure-teambots`, `mautrix`, or `python-olm` as direct or
      transitive dependencies.
- [ ] `pip install ai-parrot-integrations[all]` installs all channel
      SDKs and all existing `from parrot.integrations.X import Y`
      statements work unchanged.
- [ ] Extras `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`
      each install only the declared SDKs for that channel.
- [ ] `from parrot.auth.oauth2.service import IntegrationsService` works;
      old path `from parrot.integrations.oauth2.service import ...` raises
      `ImportError` with migration guidance.
- [ ] `from parrot_tools.zoom import ZoomUsInterface` works; old path
      `from parrot.integrations.zoom.client import ZoomUsInterface` raises
      `ImportError` with migration guidance.
- [ ] `parrot/core/hooks/matrix.py` is removed from core; `MessagingHook`
      Protocol exists in `parrot/core/hooks/base.py`; matrix hook
      auto-registers from satellite package on import.
- [ ] `parrot/voice/` is empty/removed in core; all voice modules resolve
      via PEP 420 from the satellite package.
- [ ] `parrot/human/channels/telegram.py` lives in satellite; a
      `ChannelRegistry` in core discovers it when the extra is installed.
- [ ] All existing tests pass (both `ai-parrot` and `ai-parrot-integrations`).
- [ ] `BotManager` (`parrot/manager/manager.py`) is untouched and remains
      in `ai-parrot`.
- [ ] `IntegrationBotManager` lazy import from `BotManager` and
      `orchestrator.py` works via PEP 420.
- [ ] Workspace root `pyproject.toml` includes `ai-parrot-integrations`
      in `[tool.uv.sources]`.
- [ ] CHANGELOG documents breaking changes and migration guide.
- [ ] No `parrot/__init__.py` in `packages/ai-parrot-integrations/src/`
      (would break namespace extension).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Namespace extension infrastructure — verified
from pkgutil import extend_path            # parrot/__init__.py:9
__path__ = extend_path(__path__, __name__)  # parrot/__init__.py:12

# Lazy PEP 562 exports — verified
# parrot/integrations/__init__.py:17-36
_LAZY_EXPORTS = {
    "IntegrationBotConfig": ".models",
    "TelegramAgentConfig": ".models",
    "MSTeamsAgentConfig": ".models",
    "WhatsAppAgentConfig": ".models",
    "SlackAgentConfig": ".models",
    "IntegrationBotManager": ".manager",
}

# IntegrationBotManager imports — verified
from aiogram import Bot, Dispatcher               # integrations/manager.py:12
from ..human import (                              # integrations/manager.py:18-22
    HumanInteractionManager,
    TelegramHumanChannel,
    set_default_human_manager,
)

# Hook system — verified
from .base import BaseHook                         # core/hooks/matrix.py:10
from .models import HookType, MatrixHookConfig     # core/hooks/matrix.py:11
# Dynamic (inside method): from parrot.integrations.matrix.client import MatrixClientWrapper
#                                                  # core/hooks/matrix.py:63

# OAuth2 consumers (imports to update) — verified
from parrot.integrations.oauth2.service import IntegrationsService  # auth/routes.py:34
from parrot.integrations.oauth2.service import IntegrationsService  # auth/oauth2_routes.py:28
from parrot.integrations.oauth2 import ...         # handlers/integrations.py:27
# manager/manager.py:1659-1660 (lazy import inside function)

# Zoom consumer — verified
from parrot.integrations.zoom.client import ZoomUsInterface  # parrot_tools/zoomtoolkit.py:6

# Cross-integration imports — verified
from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier  # bots/jira_specialist.py
from parrot.integrations.telegram.combined_callback import ...                # handlers/agent.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/core/hooks/base.py
class BaseHook(ABC):                                # line 12
    async def start(self) -> None: ...              # abstract
    async def stop(self) -> None: ...               # abstract

# packages/ai-parrot/src/parrot/core/hooks/matrix.py
class MatrixHook(BaseHook):                         # line 14
    # imports MatrixClientWrapper dynamically at line 63

# packages/ai-parrot/src/parrot/integrations/manager.py
class IntegrationBotManager:                        # line 42
    human_manager: Optional[HumanInteractionManager]  # line ~70

# packages/ai-parrot/src/parrot/integrations/models.py
class IntegrationBotConfig:                         # line 13 (dataclass)
    # Union of TelegramAgentConfig | MSTeamsAgentConfig | WhatsAppAgentConfig | SlackAgentConfig

# packages/ai-parrot/src/parrot/human/__init__.py
# Lazy export: TelegramHumanChannel                 # lines 30-32 (PEP 562)
# Direct exports: HumanInteractionManager + models  # lines 10-26

# packages/ai-parrot/src/parrot/human/channels/base.py
# HumanChannel ABC                                  # ~7.4KB

# packages/ai-parrot/src/parrot/integrations/zoom/client.py
class ZoomUsInterface:                              # ~4.5KB file
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| satellite `parrot.integrations.*` | `parrot/__init__.py` extend_path | PEP 420 namespace | `parrot/__init__.py:9-12` |
| `parrot.auth.oauth2.*` | `auth/routes.py` | updated import | `auth/routes.py:34` |
| `parrot.auth.oauth2.*` | `auth/oauth2_routes.py` | updated import | `auth/oauth2_routes.py:28` |
| `parrot.auth.oauth2.*` | `handlers/integrations.py` | updated import | `handlers/integrations.py:27` |
| `parrot.auth.oauth2.*` | `manager/manager.py` | updated lazy import | `manager/manager.py:1659` |
| `MessagingHook` Protocol | `core/hooks/base.py` | new abstract | `core/hooks/base.py:12` (extend) |
| `ChannelRegistry` | `human/channels/__init__.py` | new registry | `human/__init__.py:30` (extend) |
| `parrot_tools.zoom` | `zoomtoolkit.py` | updated import | `parrot_tools/zoomtoolkit.py:6` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.integrations.HumanChannelRegistry`~~ — does not exist; must
  be created in `parrot/human/channels/__init__.py` core.
- ~~`parrot.core.hooks.MessagingHook`~~ — does not exist; must be
  created in `parrot/core/hooks/base.py`.
- ~~`parrot.integrations.matrix.hook.MatrixHook`~~ — does not exist;
  must be created when refactoring the hook (today lives at
  `parrot/core/hooks/matrix.py`).
- ~~`ai-parrot-integrations` package~~ — does not exist; this FEAT creates it.
- ~~`parrot.auth.oauth2.*`~~ — does not exist; this FEAT creates it by
  relocating from `parrot.integrations.oauth2`.
- ~~`parrot_tools.zoom`~~ — does not exist; this FEAT creates it by
  relocating from `parrot.integrations.zoom`.
- ~~`packages/ai-parrot-loaders` with namespace `parrot.loaders.*`~~ —
  NOT namespace-extended. `ai-parrot-loaders` uses top-level
  `parrot_loaders.*` (verified in
  `packages/ai-parrot-loaders/pyproject.toml`). Only
  `ai-parrot-integrations` and `ai-parrot-embeddings` (FEAT-201) use
  PEP 420 namespace extension to `parrot.*`.
- ~~`parrot.integrations.core.hooks`~~ — does not exist. The hook
  system lives at `parrot/core/hooks/`, not inside integrations.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **PEP 420 namespace extension** (same pattern as FEAT-201
  ai-parrot-embeddings): satellite contributes to `parrot.*` namespace
  without its own `parrot/__init__.py`.
- **Lazy PEP 562 `__getattr__`** in `__init__.py` files to defer heavy
  SDK imports (`aiogram`, `mautrix`, `botbuilder`, `pywa`).
- **`[tool.setuptools.packages.find]`** with `include = ["parrot*"]`
  and `namespaces = true` in satellite pyproject (same as FEAT-201).
- **Extras granulares** per channel (same pattern as FEAT-201's
  `[pgvector,milvus,huggingface]`).
- **Stub `__init__.py`** in core `parrot/integrations/` with
  `__getattr__` that detects missing extras and raises `ImportError`
  with migration guidance.

### Known Risks / Gotchas

- **PR grande (~1.6 MB de código movido)**: mitigar con commits
  granulares (uno por canal + uno por refactor estructural) para
  facilitar review incremental.
- **`parrot/__init__.py` en satellite package**: NEVER create one.

…(truncated)…
