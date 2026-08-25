"""Input sanitization for values handed to APScheduler.

The scheduler receives loosely-typed values from two sources that are outside
the type system's reach:

* **navconfig environment variables** — ``CACHE_HOST`` / ``CACHE_PORT``.
  navconfig's ``fallback=`` only applies when a key is *absent*; a key that is
  present-but-empty (``CACHE_PORT=`` in a ``.env`` file) resolves to ``''``.
* **the ``navigator.agents_scheduler`` table** — ``schedule_type``,
  ``scheduler_type`` and the free-form ``schedule_config`` JSONB column, all of
  which are written by API callers and hand-edited by operators.

Neither source guarantees a trimmed, non-empty, correctly-typed value, and
APScheduler/redis-py fail *late* and *opaquely* when handed one. The production
symptom that motivated this module::

    apscheduler.scheduler(base.py:1162) :: Error getting due jobs from job
    store 'redis': invalid literal for int() with base 10: ''

``CACHE_PORT=''`` reached ``RedisJobStore(port='')``. redis-py builds
connections lazily, so ``int(port)`` did not run at construction — it ran on the
first real command, which is ``get_due_jobs()`` inside APScheduler's job-
processing loop. The result was a repeating error every scheduler tick with no
pointer back to the misconfigured environment variable.

The helpers here apply a single, consistent policy at the boundary:

* **trim** every string value;
* **filter** blank strings and null-ish tokens (``""``, ``"none"``, ``"null"``,
  ``"nil"``, ``"undefined"``, ``"~"``, ``"-"``) down to "not provided";
* **coerce** numeric values, range-checking them where APScheduler has a
  documented domain (ports, hours, minutes, days);
* **fall back** to a safe documented default and emit a ``WARNING`` naming the
  offending field, or raise :class:`SchedulerConfigError` when no safe default
  exists.

.. important::
   "Null if invalid" deliberately does **not** mean passing ``None`` through to
   a trigger. ``CronTrigger(hour=None, minute=None)`` is silently accepted by
   APScheduler and produces ``cron[]`` — a job that fires **every minute**. A
   blank cron field therefore falls back to its documented default (``0``),
   never to ``None``.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, FrozenSet, Iterable, Optional, Set, Tuple

__all__ = (
    "SchedulerConfigError",
    "clean_bool",
    "clean_int",
    "clean_str",
    "normalize_jobstore_alias",
    "normalize_schedule_type",
    "sanitize_redis_settings",
    "sanitize_schedule_config",
)

logger = logging.getLogger("Parrot.Scheduler.sanitize")

#: Case-insensitive tokens that operators and JSON serializers use to mean
#: "no value". Treated identically to a missing key.
NULL_TOKENS: FrozenSet[str] = frozenset(
    {"", "none", "null", "nil", "nan", "undefined", "n/a", "~", "-"}
)

_TRUE_TOKENS: FrozenSet[str] = frozenset({"true", "t", "yes", "y", "on", "1"})
_FALSE_TOKENS: FrozenSet[str] = frozenset({"false", "f", "no", "n", "off", "0"})

#: Weekday names APScheduler's cron ``day_of_week`` field accepts.
WEEKDAYS: Tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: Keyword arguments ``CronTrigger.__init__`` accepts. Anything else raises
#: ``TypeError`` when ``schedule_type == 'cron'`` splats the JSONB config.
CRON_TRIGGER_FIELDS: FrozenSet[str] = frozenset(
    {
        "year", "month", "day", "week", "day_of_week", "hour", "minute", "second",
        "start_date", "end_date", "timezone", "jitter",
    }
)

#: Defaults used when the environment supplies nothing usable.
DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379
DEFAULT_REDIS_JOBSTORE_DB = 6

_MIN_PORT, _MAX_PORT = 1, 65535
_MIN_REDIS_DB, _MAX_REDIS_DB = 0, 15

#: Generous upper bounds for interval components — these reject nonsense
#: (negative values, absurd magnitudes), not legitimate long intervals.
_INTERVAL_MAX: Dict[str, int] = {
    "weeks": 520,        # ~10 years
    "days": 3650,
    "hours": 87600,
    "minutes": 5256000,
    "seconds": 315360000,
}


class SchedulerConfigError(ValueError):
    """Raised when a schedule's configuration cannot be made safe.

    Used only where no defensible default exists — e.g. an ``interval``
    schedule with no non-zero component, which APScheduler would silently turn
    into a one-second hot loop.
    """


# ---------------------------------------------------------------------------
# Primitive cleaners
# ---------------------------------------------------------------------------
def clean_str(
    value: Any,
    *,
    default: Optional[str] = None,
    lower: bool = False,
    field: Optional[str] = None,
) -> Optional[str]:
    """Trim ``value`` and map blank/null-ish text to ``default``.

    Args:
        value: Raw value from the environment or a database column. Non-string
            values are coerced with ``str()`` before trimming.
        default: Returned when ``value`` is ``None``, blank, or a null token.
        lower: Lowercase the result. Useful for enum-like fields.
        field: Field name used in the warning emitted on fallback.

    Returns:
        The trimmed string, or ``default`` when nothing usable was supplied.
    """
    if value is None:
        return default
    text = value.strip() if isinstance(value, str) else str(value).strip()
    if text.lower() in NULL_TOKENS:
        if field and text:
            logger.warning(
                "Scheduler config: field %r had null-ish value %r; using %r",
                field, value, default,
            )
        return default
    return text.lower() if lower else text


def clean_int(
    value: Any,
    *,
    default: Optional[int],
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
    field: Optional[str] = None,
) -> Optional[int]:
    """Coerce ``value`` to an ``int``, falling back to ``default``.

    Accepts ints and numeric strings (``" 6380 "``, ``"6379.0"``). Booleans are
    rejected: Python treats ``True`` as ``1``, which is never what a port or an
    hour field means. Values outside ``[minimum, maximum]`` fall back rather
    than propagating to APScheduler, which would raise late and opaquely.

    Args:
        value: Raw value from the environment or a JSONB column.
        default: Returned when ``value`` is unusable. May be ``None``.
        minimum: Inclusive lower bound, when the field has a domain.
        maximum: Inclusive upper bound, when the field has a domain.
        field: Field name used in the warning emitted on fallback.

    Returns:
        The coerced integer, or ``default``.
    """

    def _fallback(reason: str) -> Optional[int]:
        logger.warning(
            "Scheduler config: %s %r (%s); using default %r",
            field or "value", value, reason, default,
        )
        return default

    if isinstance(value, bool):
        return _fallback("booleans are not valid integers")

    if isinstance(value, int):
        number = value
    else:
        text = clean_str(value)
        if text is None:
            return default
        try:
            number = int(text, 10)
        except ValueError:
            try:
                number = int(float(text))
            except (TypeError, ValueError):
                return _fallback("not a number")
            except OverflowError:
                # float('1e400') is inf, and int(inf) raises.
                return _fallback("numeric overflow")

    if minimum is not None and number < minimum:
        return _fallback(f"below minimum {minimum}")
    if maximum is not None and number > maximum:
        return _fallback(f"above maximum {maximum}")
    return number


def clean_bool(value: Any, *, default: bool) -> bool:
    """Coerce ``value`` to a ``bool``, falling back to ``default``.

    Args:
        value: Raw value; a ``bool``, or a token such as ``"yes"`` / ``"off"``.
        default: Returned when ``value`` is blank or unrecognized.

    Returns:
        The parsed boolean, or ``default``.
    """
    if isinstance(value, bool):
        return value
    text = clean_str(value, lower=True)
    if text is None:
        return default
    if text in _TRUE_TOKENS:
        return True
    if text in _FALSE_TOKENS:
        return False
    logger.warning(
        "Scheduler config: unrecognized boolean %r; using default %r", value, default
    )
    return default


# ---------------------------------------------------------------------------
# Redis / jobstore settings
# ---------------------------------------------------------------------------
def sanitize_redis_settings(
    host: Any,
    port: Any,
    db: Any = DEFAULT_REDIS_JOBSTORE_DB,
) -> Dict[str, Any]:
    """Build validated connection settings for ``RedisJobStore``.

    This is the direct fix for the reported production failure: redis-py defers
    ``int(port)`` to the first connection, so an empty ``CACHE_PORT`` only
    surfaces once APScheduler polls for due jobs.

    Args:
        host: Raw ``CACHE_HOST`` value.
        port: Raw ``CACHE_PORT`` value.
        db: Raw Redis database index for the jobstore.

    Returns:
        Mapping with ``host`` (``str``), ``port`` (``int``) and ``db`` (``int``),
        ready to splat into ``RedisJobStore(...)``.
    """
    return {
        "host": clean_str(host, default=DEFAULT_REDIS_HOST, field="CACHE_HOST"),
        "port": clean_int(
            port,
            default=DEFAULT_REDIS_PORT,
            minimum=_MIN_PORT,
            maximum=_MAX_PORT,
            field="CACHE_PORT",
        ),
        "db": clean_int(
            db,
            default=DEFAULT_REDIS_JOBSTORE_DB,
            minimum=_MIN_REDIS_DB,
            maximum=_MAX_REDIS_DB,
            field="redis jobstore db",
        ),
    }


def normalize_jobstore_alias(
    value: Any,
    *,
    available: Optional[Iterable[str]] = None,
    default: str = "default",
    strict: bool = False,
) -> str:
    """Normalize a ``scheduler_type`` column into a usable jobstore alias.

    ``AsyncIOScheduler.add_job(jobstore=...)`` raises ``KeyError`` for an alias
    that was never registered — which happens whenever a row says ``'redis'``
    but the scheduler started with ``use_redis=False``.

    The two callers want different behavior for an unregistered alias:

    * **recovering rows from the database** — fall back to the always-present
      ``'default'`` store, so an old row keeps running in memory instead of
      being dropped entirely (``strict=False``);
    * **an explicit API request** — raise, because silently downgrading a
      caller's stated durability choice to an in-memory store is worse than
      telling them Redis is not enabled (``strict=True``).

    Args:
        value: Raw ``scheduler_type`` value.
        available: Aliases registered on the scheduler. When ``None`` the
            registration check is skipped.
        default: Alias used when ``value`` is blank, or unregistered and not
            ``strict``.
        strict: Raise instead of falling back when the alias is unregistered.

    Returns:
        A jobstore alias safe to pass to ``add_job()``.

    Raises:
        SchedulerConfigError: When ``strict`` and the alias is unregistered.
    """
    alias = clean_str(value, default=default, lower=True) or default
    if available is not None:
        known: Set[str] = {str(item).lower() for item in available}
        if alias not in known:
            if strict:
                raise SchedulerConfigError(
                    f"Jobstore {alias!r} is not enabled on this scheduler "
                    f"(available: {', '.join(sorted(known)) or 'none'})"
                )
            logger.warning(
                "Scheduler config: jobstore %r is not registered (available: %s); "
                "falling back to %r",
                alias, sorted(known) or "none", default,
            )
            return default
    return alias


# ---------------------------------------------------------------------------
# Schedule type / config
# ---------------------------------------------------------------------------
def _known_schedule_types() -> Set[str]:
    """Return the accepted ``schedule_type`` values.

    Imported lazily so this module stays importable without pulling in
    ``manager`` (which imports aiohttp, asyncdb and navigator).
    """
    from .manager import ScheduleType  # local import — avoids a circular import

    return {member.value for member in ScheduleType}


def normalize_schedule_type(value: Any) -> str:
    """Trim, lowercase and validate a ``schedule_type``.

    Args:
        value: Raw ``schedule_type`` value.

    Returns:
        The canonical lowercase schedule type.

    Raises:
        SchedulerConfigError: When blank or not a supported type. A schedule
            with no type cannot be defaulted — there is no safe guess between
            "run once" and "run every minute".
    """
    schedule_type = clean_str(value, lower=True)
    if not schedule_type:
        raise SchedulerConfigError(
            f"schedule_type is required but was empty (got {value!r})"
        )
    known = _known_schedule_types()
    if schedule_type not in known:
        raise SchedulerConfigError(
            f"Unsupported schedule type: {schedule_type!r} "
            f"(expected one of {', '.join(sorted(known))})"
        )
    return schedule_type


def _clean_day_of_week(value: Any, *, default: str = "mon") -> str:
    """Normalize a cron ``day_of_week`` value.

    Accepts APScheduler weekday names (``"mon"``), full names (``"Monday"``),
    numeric strings (``"0"``-``"6"``) and range/list expressions
    (``"mon-fri"``, ``"mon,wed"``). Anything else falls back to ``default``.
    """
    text = clean_str(value, lower=True, field="day_of_week")
    if not text:
        return default
    # Numeric or expression form — hand to APScheduler, which validates it.
    if text.isdigit() or any(ch in text for ch in ",-/*"):
        return text
    abbreviated = text[:3]
    if abbreviated in WEEKDAYS:
        return abbreviated
    logger.warning(
        "Scheduler config: invalid day_of_week %r; using default %r", value, default
    )
    return default


def _clean_cron_int(value: Any, *, default: int, maximum: int, field: str) -> int:
    """Clean a numeric cron field, never yielding ``None``.

    Returning ``None`` here would be actively dangerous: APScheduler treats an
    explicit ``None`` as "field unspecified", and an unspecified ``hour``
    widens a daily job into an every-minute one.
    """
    cleaned = clean_int(value, default=default, minimum=0, maximum=maximum, field=field)
    return default if cleaned is None else cleaned


def _sanitize_once(config: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a ``once`` (``DateTrigger``) config."""
    raw = config.get("run_date")
    if isinstance(raw, (datetime, date)):
        return {"run_date": raw}
    text = clean_str(raw, field="run_date")
    if text is None:
        # An absent run_date is legal — the caller defaults to "now".
        return {}
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise SchedulerConfigError(
            f"Invalid run_date {raw!r} for a 'once' schedule: expected an "
            f"ISO-8601 datetime ({exc})"
        ) from exc
    return {"run_date": text}


def _sanitize_interval(config: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize an ``interval`` (``IntervalTrigger``) config.

    Raises:
        SchedulerConfigError: When every component resolves to zero.
            ``IntervalTrigger()`` with all-zero arguments silently becomes a
            **one-second** interval, which would hammer the target agent.
    """
    cleaned = {
        unit: _clean_cron_int(
            config.get(unit), default=0, maximum=_INTERVAL_MAX[unit], field=unit
        )
        for unit in ("weeks", "days", "hours", "minutes", "seconds")
    }
    if not any(cleaned.values()):
        raise SchedulerConfigError(
            "An 'interval' schedule needs at least one non-zero component "
            f"(weeks/days/hours/minutes/seconds); got {config!r}"
        )
    return cleaned


def _sanitize_cron(config: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a raw ``cron`` config splatted into ``CronTrigger(**config)``.

    Unknown keys are dropped (they would raise ``TypeError``) and blank values
    are dropped (they would raise ``ValueError: Unrecognized expression ""``).
    """
    cleaned: Dict[str, Any] = {}
    for key, value in config.items():
        field = clean_str(key, lower=True)
        if field is None:
            continue
        if field not in CRON_TRIGGER_FIELDS:
            logger.warning("Scheduler config: dropping unsupported cron field %r", key)
            continue
        if field in ("start_date", "end_date") and isinstance(value, (datetime, date)):
            cleaned[field] = value
            continue
        if field == "jitter":
            jitter = clean_int(value, default=None, minimum=0, field="jitter")
            if jitter is not None:
                cleaned[field] = jitter
            continue
        text = clean_str(value, field=field)
        if text is None:
            # Blank field: drop it so APScheduler applies its own default.
            continue
        cleaned[field] = text

    if not cleaned:
        raise SchedulerConfigError(
            f"A 'cron' schedule needs at least one usable field; got {config!r}"
        )
    return cleaned


def _sanitize_crontab(config: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a ``crontab`` config for ``CronTrigger.from_crontab()``.

    Only ``expr`` is kept: the caller passes ``timezone`` explicitly, so a
    ``timezone`` key in the config would raise ``TypeError: got multiple values
    for keyword argument 'timezone'``.
    """
    expr = clean_str(config.get("expr"), field="expr")
    if not expr:
        raise SchedulerConfigError(
            "A 'crontab' schedule requires a non-empty 'expr'; got "
            f"{config.get('expr')!r}"
        )
    expr = re.sub(r"\s+", " ", expr)
    field_count = len(expr.split(" "))
    if field_count != 5:
        raise SchedulerConfigError(
            f"Invalid crontab 'expr' {expr!r}: expected 5 fields, got {field_count}"
        )
    return {"expr": expr}


def sanitize_schedule_config(
    schedule_type: Any,
    config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Trim, filter and coerce a ``schedule_config`` for its schedule type.

    The single entry point used by the scheduler before building a trigger.
    Blank and null-ish values are replaced by the documented default for the
    field; unknown keys are dropped; numeric fields are coerced and
    range-checked. Configurations with no safe interpretation raise
    :class:`SchedulerConfigError`, so the offending schedule is skipped with a
    clear message instead of misfiring.

    Args:
        schedule_type: Raw schedule type; normalized internally.
        config: Raw ``schedule_config`` JSONB payload. ``None`` is treated as
            an empty mapping.

    Returns:
        A mapping safe to hand to the matching APScheduler trigger.

    Raises:
        SchedulerConfigError: When the type is unsupported or the config cannot
            be made safe.
    """
    stype = normalize_schedule_type(schedule_type)
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise SchedulerConfigError(
            f"schedule_config must be a mapping, got {type(config).__name__}"
        )

    if stype == "once":
        return _sanitize_once(config)

    if stype == "daily":
        return {
            "hour": _clean_cron_int(config.get("hour"), default=0, maximum=23, field="hour"),
            "minute": _clean_cron_int(config.get("minute"), default=0, maximum=59, field="minute"),
        }

    if stype == "weekly":
        return {
            "day_of_week": _clean_day_of_week(config.get("day_of_week")),
            "hour": _clean_cron_int(config.get("hour"), default=0, maximum=23, field="hour"),
            "minute": _clean_cron_int(config.get("minute"), default=0, maximum=59, field="minute"),
        }

    if stype == "monthly":
        day = clean_int(config.get("day"), default=1, minimum=1, maximum=31, field="day")
        return {
            "day": 1 if day is None else day,
            "hour": _clean_cron_int(config.get("hour"), default=0, maximum=23, field="hour"),
            "minute": _clean_cron_int(config.get("minute"), default=0, maximum=59, field="minute"),
        }

    if stype == "interval":
        return _sanitize_interval(config)

    if stype == "cron":
        return _sanitize_cron(config)

    if stype == "crontab":
        return _sanitize_crontab(config)

    # normalize_schedule_type() already rejects anything unknown; this guards
    # against a ScheduleType member being added without a branch here.
    raise SchedulerConfigError(f"No sanitizer implemented for schedule type {stype!r}")
