# EventBus v2 Configuration Reference (`[bus]` / `[bus.alerts]`)

Configuration flows through **navconfig**. TOML sections map to flattened
`BUS_*` keys (env vars or INI/TOML config files); every knob can also be
passed programmatically as a constructor kwarg — kwargs win over config.

## `[bus]` — core dispatcher

Read by the `EventBus` facade (`parrot/core/events/evb.py`) at
construction and forwarded to `BusCore`.

| TOML idea | navconfig key | Default | Meaning |
|---|---|---|---|
| `bus.workers` | `BUS_WORKERS` | `4` | dispatch worker tasks |
| `bus.queue_size` | `BUS_QUEUE_SIZE` | `1024` | size of EACH per-priority queue (0 = unbounded) |
| `bus.handler_timeout` | `BUS_HANDLER_TIMEOUT` | `30.0` | per-handler timeout (s); timeout counts as a failure |
| `bus.retry_attempts` | `BUS_RETRY_ATTEMPTS` | `3` | delivery attempts per handler before DLQ |
| `bus.retry_base_delay` | `BUS_RETRY_BASE_DELAY` | `0.1` | backoff base (s); attempt *n* waits `base × 2^(n−1)` |
| `bus.default_backpressure` | `BUS_DEFAULT_BACKPRESSURE` | `block` | `block` / `drop_oldest` / `reject` |
| `bus.drain_timeout` | `BUS_DRAIN_TIMEOUT` | `5.0` | graceful-shutdown drain deadline (s) |

Per-topic-class backpressure overrides are programmatic
(`BusCore(backpressure={"orders": "reject"})`) — lookup order: exact topic
→ topic class (first dot segment) → default.

```python
from parrot.core.events import EventBus

# kwargs override BUS_* config
bus = EventBus(redis_url="redis://...", use_redis=True, workers=8)
```

## `[bus.alerts]` — NotificationSubscriber

Scalar knobs via navconfig (`AlertsConfig.from_navconfig()`); rule tables
(`[[bus.alerts]]`-style) via `AlertsConfig.from_dict()` or programmatic
`AlertRule` lists.

| TOML idea | navconfig key | Default | Meaning |
|---|---|---|---|
| `bus.alerts.dedup_window_seconds` | `BUS_ALERTS_DEDUP_WINDOW` | `300.0` | identical `(rule_id, topic_class)` alerts suppressed after first delivery; repeat count appended when the window closes |
| `bus.alerts.channel_throttle_max` | `BUS_ALERTS_CHANNEL_THROTTLE` | `10` | max notifications per channel per window |
| `bus.alerts.channel_throttle_window_seconds` | `BUS_ALERTS_THROTTLE_WINDOW` | `60.0` | throttle window ⇒ default 10/min; overflow folds into ONE digest |
| `bus.alerts.storm_threshold_events` | `BUS_ALERTS_STORM_THRESHOLD` | `25` | ERROR+ events that trigger the storm guard |
| `bus.alerts.storm_window_seconds` | `BUS_ALERTS_STORM_WINDOW` | `30.0` | storm counting window; storm ⇒ one CRITICAL alert, per-rule alerts silenced until the rate drops |
| `bus.alerts.include_bus_internal` | — (programmatic) | `false` | alert on internal `bus.*` topics (loop guard) |

### Rule shape (`[[bus.alerts]]` → `AlertRule`)

```toml
[[bus.alerts]]
rule_id      = "order-errors"
pattern      = "orders.*"          # topic glob
min_severity = 40                  # ERROR
provider     = "slack"             # email | slack | telegram | teams
recipients   = ["#ops"]
# window rule (optional — both fields together):
window_seconds  = 30.0
count_threshold = 5                # "5 events ≥ ERROR in 30 s"
```

```python
from parrot.core.events.bus.subscribers import (
    AlertRule, AlertsConfig, NotificationSubscriber,
)

alerter = NotificationSubscriber(
    sender,  # anything exposing NotificationMixin.send_notification
    config=AlertsConfig.from_navconfig(),
    rules=[AlertRule(rule_id="order-errors", pattern="orders.*",
                     provider="slack", recipients=["#ops"])],
)
alerter.attach(bus._core)
```

## Ingress / persistence knobs

| navconfig key | Default | Used by |
|---|---|---|
| `BUS_INGRESS_TOKEN` | *(unset ⇒ ALL ingress refused)* | `WebSocketIngress`, `GrpcIngress` — auth required by default |
| `AUTONOMOUS_HOOKS_VIA_BUS` | `false` | orchestrator flag: **switches** hook consumption from the direct callback to a bus subscription (mutually exclusive — never both, or executions would double). Bus mode also picks up hook events published by other instances on a distributed backend |
| Postgres DSN (`parrot.conf.default_dsn` / `DBHOST`…) | — | `DLQHandler` (`navigator.evb_dlq`), `AuditSubscriber` (`navigator.evb_audit`); missing DSN disables persistence with a loud warning |

## Redis Streams backend (programmatic)

`RedisStreamsBackend(redis_url, group="parrot-bus", dedup_ttl=86400,
min_idle_time_ms=60000, autoclaim_interval=30.0, maxlen=100000, ...)` —
consumer name defaults to `<hostname>-<pid>`. Requires reachable
Memorystore/Upstash from every instance.
