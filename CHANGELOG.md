# Changelog

All notable changes to AI-Parrot are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — FEAT-319: EventBus Consolidation

### Changed

- **navigator-eventbus pinned to `>=0.1.0,<0.2`** (was a git commit hash).
  The published 0.1.0 release includes envelope `schema_version` support and
  tri-state `route_to_bus` on `HookManager`.

### Behavior Change

- **`HookManager.route_to_bus` auto-routing**: `navigator-eventbus>=0.1.0`
  changes `route_to_bus` to auto-enable when a bus is attached via
  `set_event_bus`. Any deployment that previously called `set_event_bus` and
  relied on the implicit `route_to_bus=False` default will now route hooks
  traffic to the bus. Pass `route_to_bus=False` explicitly to restore the old
  behavior. This is currently latent in ai-parrot (zero `route_to_bus` call
  sites).

### Added

- `test_no_internal_bus_copy` migration guard — asserts the deleted
  `parrot/core/events/bus/` directory stays deleted and no `parrot.*` module
  defines `BusCore`.

---

## [Unreleased] — FEAT-202: ai-parrot-integrations

### Breaking Changes

#### Dependencies removed from `ai-parrot` BASE install

The following SDKs are **no longer installed** when you run `pip install ai-parrot`.
Install the new satellite package with the appropriate extra instead:

| Removed dependency | Reason | Replacement |
|---|---|---|
| `pywa>=3.8.0` | WhatsApp SDK only needed for WA channel | `pip install ai-parrot-integrations[whatsapp]` |
| `aiogram>=3.12` | Telegram SDK only needed for Telegram channel | `pip install ai-parrot-integrations[telegram]` |
| `azure-teambots>=0.1.1` | MS Teams SDK only needed for Teams channel | `pip install ai-parrot-integrations[msteams]` |
| `mautrix>=0.20` | Matrix SDK only needed for Matrix channel | `pip install ai-parrot-integrations[matrix]` |
| `python-olm>=3.2.16` | Matrix E2E encryption only needed for Matrix | `pip install ai-parrot-integrations[matrix]` |
| `async-notify[default]` | Channel-specific; now in messaging extra | `pip install ai-parrot-integrations[messaging]` |

**If your code breaks** after upgrading `ai-parrot`, install the extras you need:

```bash
# Individual channels
pip install "ai-parrot-integrations[telegram]"
pip install "ai-parrot-integrations[slack]"
pip install "ai-parrot-integrations[msteams]"
pip install "ai-parrot-integrations[whatsapp]"
pip install "ai-parrot-integrations[matrix]"

# All channels
pip install "ai-parrot-integrations[all]"

# Backward-compat alias via ai-parrot meta-extra
pip install "ai-parrot[messaging]"  # maps to ai-parrot-integrations[messaging]
```

#### OAuth2 import path changed

```python
# OLD (raises ImportError with guidance)
from parrot.integrations.oauth2.service import IntegrationsService

# NEW
from parrot.auth.oauth2.service import IntegrationsService
```

All sub-modules moved identically:

| Old path | New path |
|---|---|
| `parrot.integrations.oauth2.service` | `parrot.auth.oauth2.service` |
| `parrot.integrations.oauth2.registry` | `parrot.auth.oauth2.registry` |
| `parrot.integrations.oauth2.models` | `parrot.auth.oauth2.models` |
| `parrot.integrations.oauth2.persistence` | `parrot.auth.oauth2.persistence` |
| `parrot.integrations.oauth2.jira_provider` | `parrot.auth.oauth2.jira_provider` |
| `parrot.integrations.oauth2.o365_provider` | `parrot.auth.oauth2.o365_provider` |

#### Zoom import path changed

```python
# OLD (raises ImportError with guidance)
from parrot.integrations.zoom.client import ZoomUsInterface

# NEW
from parrot_tools.zoom.client import ZoomUsInterface
```

### New Features

- **`ai-parrot-integrations`** satellite package with granular extras:
  `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`
- **`MessagingHook` Protocol** in `parrot.core.hooks.base` — pluggable interface
  for messaging channel hooks
- **`HookRegistry`** in `parrot.core.hooks.base` — allows satellite packages to
  self-register hook implementations
- **`ChannelRegistry`** in `parrot.human.channels` — allows satellite packages to
  register `HumanChannel` implementations for auto-discovery
- Matrix hook (`MatrixHook`) now in `parrot.integrations.matrix.hook` and
  auto-registers on import

### Non-Breaking Changes

- All `from parrot.integrations.X import Y` paths continue to work unchanged
  when `ai-parrot-integrations` is installed (PEP 420 namespace extension)
- `from parrot.voice import ...` continues to work via PEP 420
- `from parrot.human import TelegramHumanChannel` continues to work via PEP 420
- `BotManager` (`parrot.manager.manager`) is **unchanged** and remains in `ai-parrot`
- `IntegrationBotManager` lazy import from `BotManager` and `orchestrator.py`
  continues to work via PEP 420
- Zoom toolkit: `parrot_tools/zoomtoolkit.py` updated to import from new location

---

See [Migration Guide](docs/migration/feat-202-ai-parrot-integrations.md) for
detailed upgrade instructions.
