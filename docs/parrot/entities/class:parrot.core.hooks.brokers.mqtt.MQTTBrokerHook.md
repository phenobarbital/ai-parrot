---
type: Wiki Entity
title: MQTTBrokerHook
id: class:parrot.core.hooks.brokers.mqtt.MQTTBrokerHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Subscribes to MQTT topics using gmqtt.
relates_to:
- concept: class:parrot.core.hooks.brokers.base.BaseBrokerHook
  rel: extends
---

# MQTTBrokerHook

Defined in [`parrot.core.hooks.brokers.mqtt`](../summaries/mod:parrot.core.hooks.brokers.mqtt.md).

```python
class MQTTBrokerHook(BaseBrokerHook)
```

Subscribes to MQTT topics using gmqtt.

## Methods

- `async def connect(self) -> None`
- `async def disconnect(self) -> None`
- `async def start_consuming(self) -> None` — Keep alive — gmqtt handles messages via callbacks.
