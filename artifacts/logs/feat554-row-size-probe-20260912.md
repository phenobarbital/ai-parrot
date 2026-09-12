# FEAT-554 row-size and turn-series probes (2026-09-12)

Run while resolving the adversarial review's R6 and its closing note. Probe
executed the spec's data models with the installed Pydantic.

## 1. R6 reproduced and fixed

- v0.1's `List[List[int]]` rejects `[1, None, None]` → 2 validation errors.
  The adversarial review's finding is exact.
- v0.2's `List[Tuple[int, Optional[int], Optional[int]]]` round-trips
  `(7, None, None)` through `AttemptTelemetry` → `AttemptUsageRow`.

## 2. Worst-case serialized row size

Every string field at its `max_length`, every token field at 7 digits, full
turn series:

| MAX_TURN_SERIES | worst-case row |
|---|---|
| 120 | 3,924 bytes |
| 100 | 3,524 bytes |
|  80 | 3,141 bytes |

Against a 4,096-byte budget that leaves 172 bytes of margin at 120 turns — one
added field away from silent row drops. Two corrections followed:

- `MAX_TURN_SERIES = 101`: the real maximum a loop can produce
  (`max_turns` is capped at 100, models/llm.py:23, plus the one post-loop
  salvage call, llm.py:552). Chosen to never truncate rather than to fit a size.
- `MAX_LINE_BYTES = 8192`: the 4,096 figure was borrowed from `PIPE_BUF`, which
  governs pipes, not regular files. POSIX requires the seek-to-end and write of
  an `O_APPEND` write to a regular file to be atomic with respect to other
  appenders, so a single `os.write()` keeps lines whole at any size on a local
  filesystem. The budget exists to keep each row one bounded syscall and to fail
  loudly if a row grows unexpectedly — not to satisfy PIPE_BUF.
