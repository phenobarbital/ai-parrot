---
type: Wiki Entity
title: DriverConfig
id: class:parrot_tools.scraping.toolkit_models.DriverConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Frozen browser configuration passed to the driver factory.
---

# DriverConfig

Defined in [`parrot_tools.scraping.toolkit_models`](../summaries/mod:parrot_tools.scraping.toolkit_models.md).

```python
class DriverConfig(BaseModel)
```

Frozen browser configuration passed to the driver factory.

Captures all browser parameters needed to create a driver instance.
Use ``merge()`` to produce a new config with overrides applied.

Args:
    driver_type: Browser driver backend to use.
    browser: Browser name to launch.
    headless: Run browser without a visible window.
    mobile: Enable mobile emulation.
    mobile_device: Specific mobile device to emulate.
    auto_install: Automatically install/update the browser driver.
    default_timeout: Default timeout in seconds for page operations.
    retry_attempts: Number of retry attempts for failed operations.
    delay_between_actions: Seconds to wait between plan steps.
    overlay_housekeeping: Dismiss overlays/popups between actions.
    disable_images: Block image loading for faster scraping.
    custom_user_agent: Override the default user agent string.

## Methods

- `def merge(self, overrides: Optional[Dict[str, Any]]=None) -> DriverConfig` — Return a new DriverConfig with overrides applied.
