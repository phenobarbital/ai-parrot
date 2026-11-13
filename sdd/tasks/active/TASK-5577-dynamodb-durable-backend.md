# TASK-5577: DynamoDB backend — transactional turn writes, chronological companions, tombstones, index state

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 8)
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-5570
**Assigned-to**: unassigned

---

## Context

DynamoDB is the production cold tier of ChatStorage (180-day TTL). Today `ConversationDynamoDB.put_turn`
returns silently when disconnected and swallows `ClientError`/`BotoCoreError` (`dynamodb.py:285-286`,
`:307-311`), `query_turns` returns `[]` on any failure, and turns are only ordered by their ID
(`SK = THREAD#<session>#TURN#<turn_id>`). This task implements the M4 contract (TASK-5570) on DynamoDB,
which has no secondary-index-free way to order by timestamp, so it needs a DESIGN: a chronological
companion item per turn, written in ONE `TransactWriteItems` together with the canonical turn and two
tombstone `ConditionCheck`s. Semantics must match the SQLite reference (TASK-5574): same ordering key
`(timestamp, sequence, turn_id)`, same index-state semantics, same error mapping.

---

## Scope

- Key layout: canonical turn (unchanged) + chronological companion item + tombstone items + index-state marker item, all in the conversations table, same partition (see the design in Implementation Notes).
- `put_turn`: raises instead of returning silently (`StorageUnavailableError` / `StorageWriteError` / `ConversationDeletedError`); ONE `TransactWriteItems` (tombstone checks, canonical, companion, marker); ordering fields of an existing turn never change; floats are stored as `Decimal`.
- `query_turns` raises `StorageUnavailableError` instead of returning `[]` when disconnected or failing.
- New operations: `query_turn_window`, `max_sequence`, `put_tombstone`, `is_deleted`, `get_index_state`, `backfill_batch`.
- `delete_turn` also removes the companion item.
- Tests against a real DynamoDB API (moto in server mode); they skip when `moto` is not installed.

**NOT in scope**: the ABC and `durable_contract.py` (TASK-5570); the backfill driver (TASK-5578); thread / artifact methods; `delete_thread_cascade` keeps its behavior (it already deletes the whole `THREAD#<session>` prefix, which now includes the companions, and it must stay blind to the `TOMB#`/`INDEXSTATE#` items); table schema/GSIs (none are added); do not touch the other backends.

**Existing tests this behavior change breaks — OWNED by this task** (coordinator decision): root-tree `tests/storage/test_dynamodb_backend.py` (`TestNotInitialized::test_not_initialized_put_turn`, `::test_not_initialized_query_turns`, `TestPutTurn::*`) asserts the old behavior and is rewritten here (see the blueprint block). Checked and NOT affected: `packages/ai-parrot/tests/storage/backends/test_dynamodb_backend.py` (no `put_turn`/`query_turns` assertions; its `delete_turn` mock tests keep passing because the mocked `Attributes` carry no `chrono_sk`), `packages/ai-parrot/tests/storage/test_backend_contract.py` (connected backends only; its DynamoDB param needs moto and is owned by TASK-5574 if it ever needs edits).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` | MODIFY | Companion/tombstone/marker items, transactional `put_turn`, failure-contract `query_turns`, the six new operations, `delete_turn` companion cleanup |
| `packages/ai-parrot/tests/storage/backends/test_dynamodb_durable_contract.py` | CREATE | Shared contract suite + DynamoDB-specific durability tests (moto server mode) |
| `tests/storage/test_dynamodb_backend.py` | MODIFY | Rewrite the old-behavior `put_turn` / not-initialized assertions to the new failure contract (repo-root test tree) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import aioboto3                                                    # dynamodb.py:15 (aioboto3 13.2.0)
from botocore.exceptions import ClientError, BotoCoreError         # dynamodb.py:16
from parrot.storage.backends.base import ConversationBackend       # dynamodb.py:19
from boto3.dynamodb.conditions import Key as DKey, Attr           # boto3 conditions — used lazily at dynamodb.py:247,327,385; boto3 is guaranteed by aioboto3, so import at module level
# --- created by TASK-5570 (read its completion note before use) ---
from parrot.storage.backends.base import BackfillBatch
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError, InvalidTurnPayloadError,
                                   StorageError, StorageUnavailableError, StorageWriteError)
```
Standard library additions: `json`, `asyncio`, `from decimal import Decimal`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/storage/backends/dynamodb.py
class ConversationDynamoDB(ConversationBackend):                   # :22
    DEFAULT_TTL_DAYS = 180                                          # :40
    def __init__(self, conversations_table: str, artifacts_table: str, dynamo_params: dict)   # :42  self._resource (aioboto3 dynamodb RESOURCE), self._conv_table, self._art_table, self._conversations_table (name)
    async def initialize(self) -> None                              # :61  builds the resource :78-80 and Table objects :81-82; SWALLOWS failures :85-92 (backend then reports is_connected False)
    @property is_connected                                          # :107  _conv_table is not None and _art_table is not None
    @staticmethod _build_pk(user_id, agent_id) -> "USER#<u>#AGENT#<a>"                # :116
    @staticmethod _ttl_epoch(updated_at: datetime, days=180) -> int                   # :121  (updated_at + days).timestamp()
    def _now(self) -> datetime                                      # :125  UTC
    async def put_turn(self, user_id, agent_id, session_id, turn_id, data) -> None    # :276  SK f"THREAD#{session_id}#TURN#{turn_id}"; item {PK,SK,type:'turn',session_id,turn_id,ttl,**data}; datetimes -> isoformat; put_item; silent when disconnected :285-286; swallows ClientError/BotoCoreError :305-311
    async def query_turns(self, user_id, agent_id, session_id, limit=10, newest_first=True) -> List[dict]   # :313  Query SK begins_with THREAD#<s>#TURN#, ScanIndexForward=not newest_first, Limit; returns [] when disconnected :322-323 and on error :334-338
    async def delete_turn(self, user_id, agent_id, session_id, turn_id) -> bool       # :340  delete_item(ReturnValues="ALL_OLD") :361-364; `return bool(response.get("Attributes"))` :365
    async def delete_thread_cascade(...) -> int                     # :372  Query PK & SK begins_with "THREAD#<session>" then batch-delete 25 at a time — removes canonical turns, thread item AND companions (all start with THREAD#<session>)
# Table access: `self._conv_table` = `await resource.Table(name)` (aioboto3 high-level Table: native Python types).
# Low-level access for transactions: `self._resource.meta.client` — boto3's DynamoDBHighLevelResource registers the
#   TransformationInjector on THAT client (boto3/dynamodb/transform.py:39-74), so `transact_write_items`,
#   `batch_get_item` accept/return NATIVE Python types there too. UNVERIFIED for aioboto3: verify with the moto test
#   `test_transaction_accepts_native_types` first; fallback = serialize with `boto3.dynamodb.types.TypeSerializer`.
```
Key layout facts already in force: thread item `SK=THREAD#<session>` (`type='thread'`); `query_threads` queries `SK begins_with THREAD#` and FILTERS `type='thread'` (`:253-255`) — companion items (`type='chrono'`) and canonical turns are filtered out by that; `query_turns` prefix `THREAD#<session>#TURN#` never matches the `#CHRONO#` companions.

### Does NOT Exist

- ~~Companion items `THREAD#<s>#CHRONO#...`~~, ~~`TOMB#...` tombstone items~~, ~~`INDEXSTATE#...` marker items~~, ~~the `chrono_sk` attribute~~ — created by this task.
- ~~`query_turn_window`, `put_tombstone`, `is_deleted`, `max_sequence`, `get_index_state`, `backfill_batch`~~ on any backend — abstract in TASK-5570; implemented here.
- ~~`BackfillBatch`~~, ~~`parrot.storage.errors`~~ — created by TASK-5570.
- ~~A GSI / LSI on the conversations table~~ — none exists and none may be required (existing deployments and the moto tables have only `PK`/`SK`).
- ~~A `ttl` attribute on tombstone or index-state items~~ — they must NEVER carry one (DynamoDB TTL would delete the deletion guard).
- ~~Float support in DynamoDB items~~ — `boto3` rejects Python `float`; the existing `put_turn` never needed it (old rows had no floats). New rows have `cost_usd` and usage floats: convert with `_to_dynamo` (float → `Decimal(str(f))`).
- ~~Tombstone SKs under the `THREAD#<session>` prefix~~ — `delete_thread_cascade` deletes that whole prefix; tombstones therefore use `TOMB#...`.
- ~~`ConsistentRead` on a GSI~~ — irrelevant (no GSI); all reads in this task use the base table with `ConsistentRead=True`.
- ~~`moto` / `motor` / `pymongo` in the shared `.venv`~~ — moto is NOT installed there (checked 2026-11): the DynamoDB tests cannot run in that environment.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/backends/dynamodb.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/storage/backends/test_dynamodb_durable_contract.py",
      "action": "CREATE"
    },
    {
      "path": "tests/storage/test_dynamodb_backend.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/backends/dynamodb.py#ConversationDynamoDB",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend"
  ]
}
```

---

## Implementation Notes

### Design (the "design pass" the spec asks for)

All items live in the conversations table, partition `PK = USER#<u>#AGENT#<a>`:

| Item | `SK` | Key attributes | `ttl`? |
|---|---|---|---|
| canonical turn (existing) | `THREAD#<s>#TURN#<turn_id>` | `type='turn'`, payload, NEW `chrono_sk` (the companion SK, absent on legacy items / unindexed writes) | yes (existing rule) |
| chronological companion | `THREAD#<s>#CHRONO#<ts20>#<seq12>#<turn_id>` | `type='chrono'`, `session_id`, `turn_id`, `timestamp`, `sequence` — a SLIM reference, no payload | same value as the canonical |
| session tombstone | `TOMB#<s>` | `type='tombstone'`, `created_at` | **never** |
| turn tombstone | `TOMB#<s>#TURN#<turn_id>` | `type='tombstone'`, `turn_id`, `created_at` | **never** |
| index-state marker | `INDEXSTATE#<s>` | `type='index_state'`, `state` in `ready|pending|invalid`, `updated_at` | **never** |

- `<ts20>` = microseconds since the epoch, zero-padded to 20 digits (integer arithmetic: `(ts - EPOCH) // timedelta(microseconds=1)`); `<seq12>` = sequence zero-padded to 12 digits. Lexical order of the SK (UTF-8 byte order) == numeric `(ts, seq)` then `turn_id` bytes. `ScanIndexForward=False` + `Limit` therefore yields "newest N by (timestamp, sequence, turn_id)" with the limit applied descending AT THE BACKEND. A value outside the widths (`ts < 0`, `ts >= 10**20`, `seq >= 10**12`) raises `InvalidTurnPayloadError`.
- **One transaction per `put_turn`** (`TransactWriteItems`, ≤ 5 items): `ConditionCheck` session tombstone absent; `ConditionCheck` turn tombstone absent; `Put` canonical (condition `attribute_not_exists(PK)` only when this call found no existing turn, so a concurrent first writer aborts us instead of being overwritten); `Put` companion (only when the turn has a usable timestamp); `Update` marker. Item order is fixed because `CancellationReasons` is positional: `[tombstone-session, tombstone-turn, canonical, companion?, state?]`.
- **Ordering immutability**: before the transaction, `GetItem` the canonical turn (`ConsistentRead`). If it exists with a usable `timestamp`, ITS `timestamp`/`sequence` (and hence the companion SK) are reused and the incoming ones ignored. If the canonical `Put` condition fails (someone created it between our read and the write) the whole transaction aborts atomically → re-read and retry (max 3 attempts, then `StorageWriteError`).
- **Index state**: marker `ready` is trusted as a fast path; otherwise the state is derived: `ready` iff no turn item of the session lacks `chrono_sk` (`_has_unindexed`: session-bounded paginated `Query` with `FilterExpression=attribute_not_exists(chrono_sk)`), else `invalid` if the marker says so, else `pending`. Writers keep the marker honest: an indexed write initializes an ABSENT marker (`if_not_exists`) to `ready`/`pending` (pending iff legacy turns exist); an UNINDEXED write (no usable timestamp) sets `pending` unless the marker is `invalid`.
- **Reads**: `query_turn_window` = tombstone `GetItem` → index state → companion `Query` (descending, consistent) → `BatchGetItem` of the canonical turns AND their turn-tombstone keys (≤ 50 turns = 100 keys per request) → drop orphans (companion without canonical: TTL race / interrupted cleanup) and tombstoned turns → keep paging companions until `limit` valid turns are collected or the partition is exhausted → reverse to ascending.
- **Item size**: DynamoDB items are ≤ 400 KB; an oversize turn fails the transaction (`ValidationException`) → `StorageWriteError` (the bus retries then dead-letters it). Large tool outputs are expected to be offloaded before this point; do not truncate here.

### Pattern to Follow

The existing module: `ClientError`/`BotoCoreError` handling per method (now re-raised as typed errors), `self.logger`, helper statics for key building. Reference semantics: TASK-5574.

### Key Constraints

- **Error mapping**: `BotoCoreError` (transport: `EndpointConnectionError`, timeouts, ...) → `StorageUnavailableError`; `ClientError` → `StorageWriteError` for writes and `StorageUnavailableError` for reads; `TransactionCanceledException` is decoded through `CancellationReasons`: tombstone check failed → `ConversationDeletedError`; canonical condition failed → internal retry; anything else → `StorageWriteError` (include the reason codes in the message). Typed `StorageError`s pass through (`except StorageError: raise` first). Always `raise ... from exc`; nothing is swallowed. Not connected → `StorageUnavailableError` (also when `self._resource is None`).
- **`BackfillBatch.processed` = items INDEXED by the call** (TASK-5578 sums it; TASK-5570's `check_backfill_batch_resumable` expects a re-run to report `0`); unusable-timestamp legacy turns stay without `chrono_sk`, are listed in `invalid_sessions` on every run and keep their session `invalid`; `next_cursor` is the JSON-encoded `LastEvaluatedKey` of the `Scan` page (so a batch may have `processed == 0` and still return a cursor), `None` when the scan is complete. Backfill is a table `Scan` with `Limit=batch_size` (offline tool; never a request path).
- **`invalid_sessions` entry format**: whatever TASK-5570 documents on `BackfillBatch`; otherwise `"<user_id>/<agent_id>/<session_id>"` (state it in the Completion Note). The user/agent are recovered from the item's `PK` with `partition("#AGENT#")` (an agent id containing `#AGENT#` is not supported).
- **Floats/Decimals**: `_to_dynamo` (write) converts `float` → `Decimal(str(f))` recursively (NaN/inf → `None`); `_from_dynamo` (read of the NEW operations) converts `Decimal` → `int` when integral else `float`. `query_turns` keeps returning raw items (unchanged contract for the UI path).
- **`_chrono_fields`**: if TASK-5570's `backends/base.py` exposes a shared parser, import it (adapting to microseconds); otherwise keep the local copy below (naive = UTC; bad sequence = 0; additionally accepts `Decimal`, because items come back from DynamoDB with Decimal numbers).
- Async only; no new dependency; no f-string in condition expressions with user data (values go in `ExpressionAttributeValues`); Google-style docstrings; type hints. Each function ≤ 60 lines (split as the blueprint does).

### References in Codebase

- `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` — the file itself.
- `packages/ai-parrot/tests/storage/conftest.py:19-60` — the existing moto fixture (note: it uses `mock_aws()`, which does NOT intercept aiobotocore's aiohttp transport; this task's tests use moto SERVER mode instead).
- `packages/ai-parrot/tests/storage/durable_contract.py` (TASK-5570) — `DurableHarness`, `ALL_CHECKS`.
- TASK-5574 (`sdd/tasks/active/TASK-5574-sqlite-durable-backend.md`) — reference semantics.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block nearly verbatim, then complete
> every `# FILL IN:` marker. Never change a signature, class name, or file path.

### Steps (in order)
1. Confirm TASK-5570 is `done`; read `storage/errors.py`, the abstract signatures, `tests/storage/durable_contract.py` — *why*: implemented verbatim.
2. Write the moto-server fixture and `test_transaction_accepts_native_types` FIRST and run it — *why*: it settles the one UNVERIFIED assumption (native types through `meta.client`); adopt the `TypeSerializer` fallback if it fails.
3. Add imports, helpers (`_chrono_fields`, `_chrono_sk`, `_to_dynamo`, `_from_dynamo`) and key builders — *why*: pure functions, testable alone.
4. Replace `put_turn` (+ planners) and patch `query_turns` / `delete_turn` — *why*: failure contract and companion upkeep.
5. Add the six operations — *why*: the M4 surface.
6. Write the remaining tests; run mutation checks — *why*: Rule 6.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — imports and pure helpers
```python
# occurrences: 1 (verified: grep -c 'from typing import Any, Dict, List, Optional' packages/ai-parrot/src/parrot/storage/backends/dynamodb.py)  :13
# AFTER — replace that line with:
import asyncio
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# occurrences: 1 (verified: grep -c 'from botocore.exceptions import ClientError, BotoCoreError' ...)  :16
# AFTER — add directly below it:
from boto3.dynamodb.conditions import Attr, Key as DKey

# occurrences: 1 (verified: grep -c 'from parrot.storage.backends.base import ConversationBackend' ...)  :19
# AFTER — replace that line with the following (then the helpers, above `class ConversationDynamoDB`):
from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    InvalidTurnPayloadError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ONE_US = timedelta(microseconds=1)
_TS_WIDTH, _SEQ_WIDTH = 20, 12
_RESERVED_KEYS = frozenset({"PK", "SK", "type", "session_id", "turn_id", "ttl", "chrono_sk"})
_INTERNAL_KEYS = ("PK", "SK", "type", "ttl", "chrono_sk")


class _OrderingRace(Exception):
    """Internal: the canonical turn appeared between our read and our write — re-read and retry."""


def _chrono_fields(data: dict) -> Tuple[Optional[int], int]:
    """Return ``(timestamp_microseconds_utc, sequence)`` from a payload or stored item."""
    raw = data.get("timestamp")
    ts: Optional[datetime] = None
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            ts = datetime.fromisoformat(raw.strip())
        except ValueError:
            ts = None
    micros: Optional[int] = None
    if ts is not None:
        ts = (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts).astimezone(timezone.utc)
        micros = (ts - _EPOCH) // _ONE_US
        micros = micros if micros >= 0 else None
    seq = data.get("sequence")
    if isinstance(seq, Decimal):
        seq = int(seq)
    valid_seq = isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0
    return micros, (seq if valid_seq else 0)
```
*(continued — same file, same block, keep the order)*
```python
def _chrono_sk(session_id: str, micros: int, seq: int, turn_id: str) -> str:
    """Companion sort key: fixed-width timestamp and sequence so lexical order == chronological order."""
    if micros >= 10 ** _TS_WIDTH or seq >= 10 ** _SEQ_WIDTH:
        raise InvalidTurnPayloadError(f"turn {turn_id}: timestamp/sequence out of range for the chrono key")
    return f"THREAD#{session_id}#CHRONO#{micros:0{_TS_WIDTH}d}#{seq:0{_SEQ_WIDTH}d}#{turn_id}"


def _to_dynamo(value: Any) -> Any:
    """Recursively make ``value`` storable: ``float`` → ``Decimal`` (NaN/inf → ``None``), datetimes → ISO."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str, Decimal)):
        return value
    if isinstance(value, float):
        return Decimal(str(value)) if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_dynamo(v) for v in value]
    return str(value)


def _from_dynamo(value: Any) -> Any:
    """Recursively turn ``Decimal`` back into ``int`` (when integral) or ``float``."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value
```
**Why**: `datetime`, `timedelta`, `timezone` are already imported at `dynamodb.py:12`. `_chrono_sk` is the single place that defines the companion key layout; `_RESERVED_KEYS` are never taken from the caller's payload.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — key builders and low-level helpers
```python
# occurrences: 1 (verified: grep -c '    def _now(self) -> datetime:' ...)  :125
# AFTER — insert the following block directly ABOVE `def _now` (inside the class):
    @staticmethod
    def _sk_turn(session_id: str, turn_id: str) -> str:
        return f"THREAD#{session_id}#TURN#{turn_id}"

    @staticmethod
    def _sk_tomb(session_id: str, turn_id: Optional[str] = None) -> str:
        """Tombstone SKs deliberately live OUTSIDE ``THREAD#<session>`` so the cascade cannot delete them."""
        return f"TOMB#{session_id}" if turn_id is None else f"TOMB#{session_id}#TURN#{turn_id}"

    @staticmethod
    def _sk_state(session_id: str) -> str:
        return f"INDEXSTATE#{session_id}"

    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected or self._resource is None:
            raise StorageUnavailableError("DynamoDB conversation backend is not connected")

    async def _get_item(self, pk: str, sk: str) -> Optional[dict]:
        """Strongly consistent ``GetItem``; transport/API failures are ``StorageUnavailableError``."""
        try:
            response = await self._conv_table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True)
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB get_item failed for {sk}: {exc}") from exc
        return response.get("Item")

    async def _has_unindexed(self, pk: str, session_id: str) -> bool:
        """Whether any turn item of the session lacks ``chrono_sk`` (session-bounded paginated Query)."""
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": DKey("PK").eq(pk) & DKey("SK").begins_with(f"THREAD#{session_id}#TURN#"),
            "FilterExpression": Attr("chrono_sk").not_exists(),
            "ProjectionExpression": "SK",
            "ConsistentRead": True,
        }
        try:
            while True:
                response = await self._conv_table.query(**kwargs)
                if response.get("Items"):
                    return True
                if not response.get("LastEvaluatedKey"):
                    return False
                kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB index-state probe failed: {exc}") from exc
```
**Why**: every read in this task is strongly consistent: a tombstone or index marker written a moment ago must be visible.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — transaction plumbing
```python
# AFTER the helpers above (same insertion point) add:
    async def _transact(self, labelled: List[Tuple[str, dict]]) -> None:
        """Run ``TransactWriteItems``; decode cancellations into typed errors (labels are positional)."""
        try:
            await self._resource.meta.client.transact_write_items(
                TransactItems=[item for _, item in labelled])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                self._raise_for_cancellation(exc, [label for label, _ in labelled])
            raise StorageWriteError(f"DynamoDB transaction failed: {exc}") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError(f"DynamoDB transport failure: {exc}") from exc

    @staticmethod
    def _raise_for_cancellation(exc: ClientError, labels: List[str]) -> None:
        reasons = exc.response.get("CancellationReasons") or []
        codes = [r.get("Code") for r in reasons]
        for label, code in zip(labels, codes):
            if code != "ConditionalCheckFailed":
                continue
            if label.startswith("tombstone"):
                raise ConversationDeletedError("session or turn is tombstoned; write rejected") from exc
            if label == "canonical":
                raise _OrderingRace() from exc
        raise StorageWriteError(f"DynamoDB transaction cancelled: {codes}") from exc
```
**Why**: `CancellationReasons[i]` corresponds to `TransactItems[i]`; labels keep the mapping explicit when the optional companion/state items are absent.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — `put_turn` and planners
```python
# occurrences: 1 (verified: grep -c 'async def put_turn(' ...)  :276
# REPLACE the whole method (def line :276 through its `except` block ending at :311) with the methods below.
    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent transactional upsert of a turn and its chronological companion.

        Raises:
            StorageUnavailableError: not connected / transport failure.
            ConversationDeletedError: the session or this turn is tombstoned (nothing is written).
            InvalidTurnPayloadError: timestamp/sequence outside the chrono key range.
            StorageWriteError: the transaction failed (nothing is swallowed).
        """
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        try:
            for _ in range(3):
                existing = await self._get_item(pk, self._sk_turn(session_id, turn_id))
                marker = await self._get_item(pk, self._sk_state(session_id))
                payload, micros, seq = self._resolve_ordering(data, existing)
                state_op = await self._state_op(pk, session_id, marker, indexed=micros is not None)
                items = self._plan_put(pk, session_id, turn_id, payload, micros, seq, existing, state_op)
                try:
                    await self._transact(items)
                    return
                except _OrderingRace:
                    continue                                   # a concurrent first write won: re-read, reuse its ordering
        except StorageError:
            raise
        raise StorageWriteError(f"turn {turn_id}: lost the ordering race 3 times")

    @staticmethod
    def _resolve_ordering(data: dict, existing: Optional[dict]) -> Tuple[dict, Optional[int], int]:
        """Payload to store + the ordering to use (an existing turn's ordering always wins)."""
        payload = {k: (v.isoformat() if isinstance(v, datetime) else v)
                   for k, v in data.items() if k not in _RESERVED_KEYS}
        micros, seq = _chrono_fields(data)
        if existing is not None:
            e_micros, e_seq = _chrono_fields(existing)
            if e_micros is not None:
                micros, seq = e_micros, e_seq
                for name in ("timestamp", "sequence"):
                    if name in existing:
                        payload[name] = _from_dynamo(existing[name])
                    else:
                        payload.pop(name, None)
        return payload, micros, seq

    async def _state_op(self, pk: str, session_id: str, marker: Optional[dict], *, indexed: bool):
        """Marker update this write needs: ``None``, ``('set', state)`` or ``('init', state)``."""
        current = marker.get("state") if marker else None
        if not indexed:
            return None if current == "invalid" else ("set", "pending")
        if current is not None:
            return None
        return ("init", "pending" if await self._has_unindexed(pk, session_id) else "ready")
```
**Why**: ordering is resolved from the CURRENT canonical item (consistent read), so a retried event never moves a turn; the loop only repeats when the conditional `Put` proves a concurrent first writer won.

```python
    def _plan_put(self, pk, session_id, turn_id, payload, micros, seq, existing, state_op):
        """Positional ``[(label, transact_item)]`` — see ``_raise_for_cancellation``."""
        table = self._conversations_table
        chrono_sk = _chrono_sk(session_id, micros, seq, turn_id) if micros is not None else None
        ts = _EPOCH + timedelta(microseconds=micros) if micros is not None else self._now()
        ttl = self._ttl_epoch(ts, self.DEFAULT_TTL_DAYS)
        item = {**_to_dynamo(payload), "PK": pk, "SK": self._sk_turn(session_id, turn_id), "type": "turn",
                "session_id": session_id, "turn_id": turn_id, "ttl": ttl}
        if chrono_sk is not None:
            item["chrono_sk"] = chrono_sk
        canonical: Dict[str, Any] = {"TableName": table, "Item": item}
        if existing is None:
            canonical["ConditionExpression"] = "attribute_not_exists(PK)"
        absent = "attribute_not_exists(PK)"
        planned = [
            ("tombstone-session", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                   "Key": {"PK": pk, "SK": self._sk_tomb(session_id)}}}),
            ("tombstone-turn", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                "Key": {"PK": pk, "SK": self._sk_tomb(session_id, turn_id)}}}),
            ("canonical", {"Put": canonical}),
        ]
        if chrono_sk is not None:
            companion = {"PK": pk, "SK": chrono_sk, "type": "chrono", "session_id": session_id,
                         "turn_id": turn_id, "timestamp": payload.get("timestamp"), "sequence": seq, "ttl": ttl}
            planned.append(("companion", {"Put": {"TableName": table, "Item": companion}}))
        if state_op is not None:
            planned.append(("state", {"Update": self._state_update(pk, session_id, *state_op)}))
        return planned

    def _state_update(self, pk: str, session_id: str, mode: str, state: str) -> dict:
        """``set`` overwrites the state; ``init`` only fills an absent one. No ``ttl`` attribute, ever."""
        assign = "#s = :v" if mode == "set" else "#s = if_not_exists(#s, :v)"
        return {
            "TableName": self._conversations_table,
            "Key": {"PK": pk, "SK": self._sk_state(session_id)},
            "UpdateExpression": f"SET {assign}, #u = :now, #t = :t",
            "ExpressionAttributeNames": {"#s": "state", "#u": "updated_at", "#t": "type"},
            "ExpressionAttributeValues": {":v": state, ":now": self._now().isoformat(), ":t": "index_state"},
        }
```
**Why**: the f-string in `_state_update` interpolates only the two literal fragments chosen by `mode` (never user data). Tombstone `ConditionCheck`s are part of the SAME transaction as the writes, so "tombstoned" and "written" can never both be true.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — `query_turns`, `delete_turn`
```python
# occurrences: 1 (verified: grep -c 'async def query_turns(' ...)  :313
# In query_turns (:313-338): replace the guard (:322-323)
#     if not self.is_connected:
#         return []
# with `self._require_connection()`, and replace the `except` block (:334-338)
#     except (ClientError, BotoCoreError) as exc:
#         self.logger.warning(...)
#         return []
# with:
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB query_turns failed for session {session_id}: {exc}") from exc

# occurrences: 1 (verified: grep -c '            return bool(response.get("Attributes"))' ...)  :365  (inside delete_turn)
# BEFORE:            return bool(response.get("Attributes"))
# AFTER (same indentation):
            attrs = response.get("Attributes")
            if attrs and attrs.get("chrono_sk"):
                await self._delete_companion(pk, attrs["chrono_sk"])
            return bool(attrs)

# AFTER `delete_turn`, add:
    async def _delete_companion(self, pk: str, chrono_sk: str) -> None:
        """Best-effort: an orphan companion is harmless (the window skips companions without a canonical turn)."""
        try:
            await self._conv_table.delete_item(Key={"PK": pk, "SK": chrono_sk})
        except (ClientError, BotoCoreError) as exc:
            self.logger.warning("DynamoDB could not delete companion %s: %s", chrono_sk, exc)
```
**Why**: the existing `delete_turn` mock tests keep passing (the mocked `Attributes` carry no `chrono_sk`, so no second call happens). The cascade needs no change.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — `query_turn_window`
```python
# occurrences: 1 (verified: grep -c '    # Conversations table — Turns' ...)  :273 — insert the new operations as a block
#   ABOVE `async def delete_thread_cascade(` (:372), after `delete_turn`.
    async def query_turn_window(
        self, user_id: str, agent_id: str, session_id: str, limit: int
    ) -> List[dict]:
        """Newest ``limit`` turns by (timestamp, sequence, turn_id), limit applied descending, returned ascending."""
        self._require_connection()
        if await self.is_deleted(user_id, agent_id, session_id):
            raise ConversationDeletedError(f"session {session_id} is tombstoned")
        if await self.get_index_state(user_id, agent_id, session_id) != "ready":
            raise IndexNotReadyError(f"chronological index of session {session_id} is not ready")
        if limit <= 0:
            return []
        pk = self._build_pk(user_id, agent_id)
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": DKey("PK").eq(pk) & DKey("SK").begins_with(f"THREAD#{session_id}#CHRONO#"),
            "ScanIndexForward": False, "Limit": limit, "ConsistentRead": True,
        }
        newest_first: List[dict] = []
        try:
            while len(newest_first) < limit:
                page = await self._conv_table.query(**kwargs)
                newest_first.extend(await self._load_turns(pk, session_id, page.get("Items", []),
                                                           limit - len(newest_first)))
                if not page.get("LastEvaluatedKey"):
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB query_turn_window failed: {exc}") from exc
        newest_first.reverse()
        return newest_first

    async def _load_turns(self, pk: str, session_id: str, companions: List[dict], room: int) -> List[dict]:
        """Resolve companions to canonical turns (newest first), dropping orphans and tombstoned turns."""
        found: Dict[str, dict] = {}
        for start in range(0, len(companions), 50):                    # 2 keys per turn -> <= 100 per request
            chunk = companions[start:start + 50]
            keys = [{"PK": pk, "SK": self._sk_turn(session_id, c["turn_id"])} for c in chunk]
            keys += [{"PK": pk, "SK": self._sk_tomb(session_id, c["turn_id"])} for c in chunk]
            found.update(await self._batch_get(keys))
        turns: List[dict] = []
        for comp in companions:
            turn = found.get(self._sk_turn(session_id, comp["turn_id"]))
            if turn is None or self._sk_tomb(session_id, comp["turn_id"]) in found:
                continue                                              # orphan companion / tombstoned turn
            row = {k: _from_dynamo(v) for k, v in turn.items() if k not in _INTERNAL_KEYS}
            turns.append(row)
            if len(turns) == room:
                break
        return turns

    async def _batch_get(self, keys: List[dict]) -> Dict[str, dict]:
        """``BatchGetItem`` (consistent) with bounded retry of ``UnprocessedKeys``; maps SK -> item."""
        table, out, request = self._conversations_table, {}, {self._conversations_table: {
            "Keys": keys, "ConsistentRead": True}}
        for attempt in range(5):
            response = await self._resource.batch_get_item(RequestItems=request)
            out.update({i["SK"]: i for i in response.get("Responses", {}).get(table, [])})
            request = response.get("UnprocessedKeys") or {}
            if not request:
                return out
            await asyncio.sleep(0.05 * 2 ** attempt)
        raise StorageUnavailableError("DynamoDB batch_get_item left unprocessed keys")
```
**Why**: each companion `Query` page asks for `limit` items and `_load_turns` stops at the REMAINING room, so the common case is one companion query plus one `BatchGetItem`; only when orphans/tombstoned turns eat the page does it page again. The returned rows keep `session_id`/`turn_id` from the canonical item and drop PK/SK/type/ttl/chrono_sk.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — tombstones, index state, `max_sequence`
```python
    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence (companion items; session-bounded paginated Query), ``0`` when none."""
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": DKey("PK").eq(pk) & DKey("SK").begins_with(f"THREAD#{session_id}#CHRONO#"),
            "ProjectionExpression": "#q", "ExpressionAttributeNames": {"#q": "sequence"},   # SEQUENCE is reserved
            "ConsistentRead": True,
        }
        highest = 0
        try:
            while True:
                page = await self._conv_table.query(**kwargs)
                highest = max([highest] + [int(i.get("sequence", 0)) for i in page.get("Items", [])])
                if not page.get("LastEvaluatedKey"):
                    return highest
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailableError(f"DynamoDB max_sequence failed: {exc}") from exc

    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; NO ``ttl`` attribute."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        item = {"PK": self._build_pk(user_id, agent_id), "SK": self._sk_tomb(session_id, turn_id),
                "type": "tombstone", "session_id": session_id, "created_at": self._now().isoformat()}
        if turn_id is not None:
            item["turn_id"] = turn_id
        try:
            await self._conv_table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return                                                   # already tombstoned: first created_at wins
            raise StorageWriteError(f"DynamoDB put_tombstone failed: {exc}") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError(f"DynamoDB transport failure: {exc}") from exc

    async def is_deleted(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Whether the session (or session OR this turn) is tombstoned; raises when it cannot be determined."""
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        if await self._get_item(pk, self._sk_tomb(session_id)) is not None:
            return True
        return turn_id is not None and await self._get_item(pk, self._sk_tomb(session_id, turn_id)) is not None

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'`` (marker fast path, otherwise derived)."""
        self._require_connection()
        pk = self._build_pk(user_id, agent_id)
        marker = await self._get_item(pk, self._sk_state(session_id))
        state = marker.get("state") if marker else None
        if state == "ready" or not await self._has_unindexed(pk, session_id):
            return "ready"
        return "invalid" if state == "invalid" else "pending"
```
**Why**: the marker's `ready` is only trusted because every writer that could invalidate it (an unindexed `put_turn`) flips it to `pending` in the same transaction; any other state is re-derived, so a legacy session whose last legacy turn was deleted becomes `ready` without a backfill pass. Tombstones use the conditional `put_item` so the first `created_at` is kept.

### `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` (MODIFY) — `backfill_batch`
```python
    @staticmethod
    def _split_pk(pk: str) -> Tuple[str, str]:
        user_id, _, agent_id = pk[len("USER#"):].partition("#AGENT#")
        return user_id, agent_id

    async def _index_legacy_item(self, item: dict) -> str:
        """Index one legacy canonical turn: ``'indexed'`` | ``'invalid'`` | ``'skipped'`` (tombstoned / raced)."""
        micros, seq = _chrono_fields(item)
        if micros is None:
            return "invalid"
        pk, session_id, turn_id = item["PK"], item["session_id"], item["turn_id"]
        chrono_sk = _chrono_sk(session_id, micros, seq, turn_id)
        table, absent = self._conversations_table, "attribute_not_exists(PK)"
        companion = {"PK": pk, "SK": chrono_sk, "type": "chrono", "session_id": session_id, "turn_id": turn_id,
                     "timestamp": item.get("timestamp"), "sequence": seq, "ttl": item.get("ttl")}
        labelled = [
            ("tombstone-session", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                   "Key": {"PK": pk, "SK": self._sk_tomb(session_id)}}}),
            ("tombstone-turn", {"ConditionCheck": {"TableName": table, "ConditionExpression": absent,
                                "Key": {"PK": pk, "SK": self._sk_tomb(session_id, turn_id)}}}),
            ("canonical", {"Update": {"TableName": table, "Key": {"PK": pk, "SK": item["SK"]},
                           "UpdateExpression": "SET chrono_sk = :c",
                           "ConditionExpression": "attribute_not_exists(chrono_sk)",
                           "ExpressionAttributeValues": {":c": chrono_sk}}}),
            ("companion", {"Put": {"TableName": table, "Item": _to_dynamo(companion)}}),
        ]
        try:
            await self._transact(labelled)
        except (ConversationDeletedError, _OrderingRace):
            return "skipped"
        return "indexed"

    async def _finalize_session(self, pk: str, session_id: str, saw_invalid: bool) -> None:
        """Write the marker ``invalid`` / ``ready`` for a session touched by a batch (else leave it pending)."""
        if saw_invalid:
            state = "invalid"
        elif not await self._has_unindexed(pk, session_id):
            state = "ready"
        else:
            return
        await self._conv_table.put_item(Item={"PK": pk, "SK": self._sk_state(session_id), "type": "index_state",
                                              "state": state, "updated_at": self._now().isoformat()})

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` scanned items after ``cursor`` (resumable; offline, never a request path)."""
        self._require_connection()
        kwargs: Dict[str, Any] = {
            "FilterExpression": Attr("type").eq("turn") & Attr("chrono_sk").not_exists(),
            "Limit": batch_size, "ConsistentRead": True,
        }
        if cursor is not None:
            kwargs["ExclusiveStartKey"] = json.loads(cursor)
        touched: Dict[Tuple[str, str], bool] = {}
        indexed = 0
        try:
            page = await self._conv_table.scan(**kwargs)
            for item in page.get("Items", []):
                outcome = await self._index_legacy_item(item)
                key = (item["PK"], item["session_id"])
                indexed += outcome == "indexed"
                if outcome != "skipped":
                    touched[key] = touched.get(key, False) or outcome == "invalid"
            for (pk, session_id), saw_invalid in touched.items():
                await self._finalize_session(pk, session_id, saw_invalid)
        except (ClientError, BotoCoreError) as exc:
            raise StorageWriteError(f"DynamoDB backfill_batch failed: {exc}") from exc
        invalid = tuple("/".join((*self._split_pk(pk), session)) for (pk, session), bad in touched.items() if bad)
        last = page.get("LastEvaluatedKey")
        return BackfillBatch(processed=indexed, next_cursor=json.dumps(last) if last else None,
                             invalid_sessions=invalid)
```
**Why**: the legacy canonical item is updated and its companion created in one transaction that also re-checks both tombstones (backfill never resurrects a deleted identity); a concurrent `put_turn` that already indexed the item makes the `attribute_not_exists(chrono_sk)` condition fail → `'skipped'`. `Scan(Limit=batch_size)` counts EVALUATED items, so the cursor advances even when a page holds no legacy turn.

### `tests/storage/test_dynamodb_backend.py` (MODIFY, repo-root tree) — rewrite the old-behavior tests
```python
# occurrences: 1 each (verify with grep -c): `async def test_not_initialized_query_turns(self, dynamo_backend):` (:82),
#   `async def test_not_initialized_put_turn(self, dynamo_backend):` (:87), `class TestPutTurn:` (:120).
# REPLACE the two not-initialized tests (bodies at :82-85 and :87-89) with (add `from parrot.storage.errors import
# StorageUnavailableError, StorageWriteError, ConversationDeletedError` to the imports):
    @pytest.mark.asyncio
    async def test_not_initialized_query_turns(self, dynamo_backend):
        with pytest.raises(StorageUnavailableError):
            await dynamo_backend.query_turns("u1", "agent1", "sess1")

    @pytest.mark.asyncio
    async def test_not_initialized_put_turn(self, dynamo_backend):
        with pytest.raises(StorageUnavailableError):
            await dynamo_backend.put_turn("u1", "agent1", "sess1", "t001", {})
```
```python
# REPLACE `class TestPutTurn` (:120-170) with tests of the TRANSACTIONAL put_turn. The backend needs a connected
# fake: set dynamo_backend._conv_table / _art_table to _make_mock_table() (existing helper) AND
# dynamo_backend._resource = MagicMock(); dynamo_backend._resource.meta.client.transact_write_items = AsyncMock().
# get_item on the mock table must return {} (no existing turn / marker) — `_make_mock_table()` already does.
class TestPutTurn:
    """put_turn builds ONE TransactWriteItems: tombstone checks, canonical, companion, marker."""

    @pytest.mark.asyncio
    async def test_builds_transaction_with_canonical_and_companion(self, dynamo_backend):
        ...  # FILL IN: call put_turn("u1","agent1","sess1","t001",{"user_message":"hello","timestamp":"2026-11-01T10:00:00+00:00","sequence":3});
             # take TransactItems from transact_write_items.call_args.kwargs; assert 5 items in order
             # [ConditionCheck TOMB#sess1, ConditionCheck TOMB#sess1#TURN#t001, Put canonical, Put companion, Update INDEXSTATE#sess1];
             # canonical Item PK == "USER#u1#AGENT#agent1", SK == "THREAD#sess1#TURN#t001", type == "turn", "ttl" in Item,
             # user_message == "hello", chrono_sk == companion SK (f"THREAD#sess1#CHRONO#{micros:020d}#{3:012d}#t001").

    @pytest.mark.asyncio
    async def test_ttl_is_derived_from_timestamp(self, dynamo_backend):
        ...  # FILL IN: tz-aware timestamp datetime(2025,4,16,12,tzinfo=UTC); expected ttl ==
             # ConversationDynamoDB._ttl_epoch(that datetime, 180); assert on the canonical Put Item (old test used a NAIVE
             # datetime and local time — the new code reads naive as UTC, so use an aware value).

    @pytest.mark.asyncio
    async def test_client_error_is_raised_as_storage_write_error(self, dynamo_backend):
        ...  # FILL IN: transact_write_items.side_effect = ClientError({"Error": {"Code": "500", "Message": "Internal"}},
             # "TransactWriteItems"); with pytest.raises(StorageWriteError): await put_turn(...)

    @pytest.mark.asyncio
    async def test_tombstone_cancellation_raises_conversation_deleted(self, dynamo_backend):
        ...  # FILL IN: side_effect = ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "x"},
             # "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}, {"Code": "None"}, ...]},
             # "TransactWriteItems"); with pytest.raises(ConversationDeletedError): await put_turn(...)
```
**Why**: the module's fixtures mock the boto layer (a "network call" you do not own); the REAL-API behavior is covered by the new moto test file. Keep every other test in the file untouched. `test_ttl_is_set` / `test_constructs_correct_keys` are subsumed by the first two rewritten tests.

### FILL IN checklist
- [ ] `tests/storage/test_dynamodb_backend.py::TestPutTurn` — the four `...` test bodies above; bounded by the transaction layout in Implementation Notes and by "mock only the boto client call".
- [ ] `_transact` — if `test_transaction_accepts_native_types` fails with aioboto3, serialize every `TransactItems` entry with `boto3.dynamodb.types.TypeSerializer` (and deserialize `batch_get_item` output); bounded by "no behavior change for callers".
- [ ] `_chrono_fields` — import a shared helper if TASK-5570 provides one; bounded by "identical semantics across backends".
- [ ] `invalid_sessions` entry format — bounded by TASK-5570's `BackfillBatch` docstring.
- [ ] `put_turn` retry count / backoff between `_OrderingRace` retries (blueprint: 3 immediate retries) — bounded by "must terminate and never loop on a live conflict".
- [ ] Moto server fixture details (see Test Specification) — bounded by "real DynamoDB API, no `unittest.mock` of the boto client except the single fault-injection seam".

---

## Acceptance Criteria

- [ ] `put_turn` never returns silently: disconnected → `StorageUnavailableError`; failed transaction → `StorageWriteError`; tombstoned session/turn → `ConversationDeletedError` with NOTHING written (neither canonical nor companion) (spec §5 "No silent backend writes").
- [ ] Canonical item, companion and marker are written atomically: after a rejected or failed `put_turn` a raw table scan finds none of the three.
- [ ] Repeated `put_turn` with the same `turn_id` leaves one canonical item and one companion with unchanged ordering fields; a lost ordering race converges on the first writer's ordering (race-injection test).
- [ ] `query_turn_window` returns the same newest window, ascending, for random and reverse-lexical IDs, equal timestamps and more rows than `limit`; tombstoned turns and orphan companions are skipped and the window is still filled from older turns (spec §5 "Chronological hydration").
- [ ] Companion SK layout is exactly `THREAD#<s>#CHRONO#<20-digit µs>#<12-digit seq>#<turn_id>`; tombstone and marker items carry NO `ttl` attribute; the existing `query_threads` / `query_turns` results are unchanged by the new items.
- [ ] Tombstones survive `delete_thread_cascade`, deletion of the transcript items (TTL simulation) and a backend restart; `delete_thread_cascade` removes the companions.
- [ ] `get_index_state`: `pending` for legacy sessions, `invalid` for a bad timestamp after backfill, `ready` for new sessions and for a legacy session whose last legacy turn was deleted; `query_turn_window` on a non-ready session raises `IndexNotReadyError` (spec §5 "Backfill").
- [ ] `backfill_batch` is resumable by cursor, skips tombstoned sessions, ignores items that already have `chrono_sk`, never marks an unusable-timestamp session `ready`; `processed` counts indexed items only.
- [ ] Floats (`cost_usd`, usage) round-trip; `delete_turn` removes the companion; `query_turns` raises `StorageUnavailableError` when disconnected or failing.
- [ ] `tests/storage/test_dynamodb_backend.py` passes with the new assertions (no old-behavior test remains); `ruff check` clean on the three files.
- [ ] **Mutation checks** (record in the Completion Note): (1) remove the two `ConditionCheck` entries from `_plan_put` → tombstone-blocks-put check RED; (2) remove `ConditionExpression` from the canonical `Put` → the ordering-race test RED; (3) change `ScanIndexForward=False` to `True` in `query_turn_window` → window check RED; (4) widen/narrow `_TS_WIDTH` so the SK is not fixed-width consistently (e.g. drop the zero padding) → window check RED; (5) add a `ttl` to the tombstone item → `test_tombstone_and_marker_items_have_no_ttl` RED; (6) make `get_index_state` return `"ready"` when `_has_unindexed` is true → `IndexNotReady` check and legacy-backfill test RED.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/storage/backends/test_dynamodb_durable_contract.py -q`
- `pytest tests/storage/test_dynamodb_backend.py -q`
- `pytest packages/ai-parrot/tests/storage/backends/test_dynamodb_backend.py -q`
- `pytest packages/ai-parrot/tests/storage/test_backend_contract.py -q`

(`moto` is not installed in the shared `.venv`, so the first and third SKIP there: install it in a scratch environment — `uv pip install "moto[server]"` — run the first once for real, and record it.)

---

## Test Specification

> Real DynamoDB API served by moto in SERVER mode (aioboto3 talks aiohttp, which `mock_aws()`
> does not intercept). The only seam that is replaced is the network client call in the single
> fault-injection hook and the `_get_item` race hooks (our own method).

```python
# packages/ai-parrot/tests/storage/backends/test_dynamodb_durable_contract.py
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

moto_server = pytest.importorskip("moto.server", reason="moto[server] not installed — skipping DynamoDB durable contract")
boto3 = pytest.importorskip("boto3")
from botocore.exceptions import ClientError  # noqa: E402

from parrot.storage.backends.dynamodb import ConversationDynamoDB  # noqa: E402
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError,  # noqa: E402
                                   StorageUnavailableError, StorageWriteError)
from .. import durable_contract          # noqa: E402  TASK-5570: DurableHarness + ALL_CHECKS (NOT collected)

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
TABLES = ("parrot-conversations", "parrot-artifacts")
CREDS = {"aws_access_key_id": "test", "aws_secret_access_key": "test", "region_name": "us-east-1"}


@pytest.fixture(scope="module")
def endpoint():
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=0)   # FILL IN: if port=0 is not supported by the installed moto, pick a free port with `socket`
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def table_client(endpoint):
    """Sync boto3 handle on the SAME server: used to create tables, seed legacy items and inspect raw items."""
    client = boto3.client("dynamodb", endpoint_url=endpoint, **CREDS)
    for name in TABLES:
        client.create_table(
            TableName=name, BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}])
    yield boto3.resource("dynamodb", endpoint_url=endpoint, **CREDS).Table(TABLES[0])
    for name in TABLES:
        client.delete_table(TableName=name)


@pytest.fixture
async def backend(endpoint, table_client):
    b = ConversationDynamoDB(TABLES[0], TABLES[1], {**CREDS, "endpoint_url": endpoint})
    await b.initialize()
    assert b.is_connected, "moto server not reachable"
    yield b
    await b.close()


def _scan(table):                                  # raw view: every item of the partition(s)
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


@asynccontextmanager
async def _inject_write_failure(backend):
    """The one seam we replace: the network call. TransactWriteItems fails like a throttled service would."""
    client = backend._resource.meta.client
    real = client.transact_write_items

    async def boom(**_kw):
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "injected"}},
                          "TransactWriteItems")
    client.transact_write_items = boom
    try:
        yield
    finally:
        client.transact_write_items = real


def _seed_legacy(table, session_id: str, rows: list) -> None:
    pk = f"USER#{durable_contract.USER}#AGENT#{durable_contract.AGENT}"
    for row in rows:
        table.put_item(Item={"PK": pk, "SK": f"THREAD#{session_id}#TURN#{row['turn_id']}", "type": "turn",
                             "session_id": session_id, "ttl": 4102444800, **row})


def _expire_transcript(table, session_id: str) -> None:        # simulate the TTL reaper: tombstones are NOT under THREAD#
    for item in _scan(table):
        if item["SK"].startswith(f"THREAD#{session_id}"):
            table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})


@pytest.fixture
def harness(backend, table_client):
    # FILL IN: adapt the keyword names to the `DurableHarness` dataclass TASK-5570 actually wrote
    # (expected hooks: disconnect, inject_write_failure, seed_legacy, expire_transcript) — adapt THIS
    # call site, never the shared checks; record any mismatch in the Completion Note.
    async def seed(sid, rows):
        _seed_legacy(table_client, sid, rows)
    async def expire(sid):
        _expire_transcript(table_client, sid)
    return durable_contract.DurableHarness(
        backend=backend, disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(backend),
        seed_legacy=seed, expire_transcript=expire)


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_dynamodb_durable_contract(check, harness):
    await check(harness)


def _row(i: int, ts: datetime, seq: int = 0, **extra) -> dict:
    return {"timestamp": ts.isoformat(), "sequence": seq, "user_message": f"q{i}", "assistant_response": f"a{i}", **extra}


# --- DynamoDB-specific ---------------------------------------------------------------------
async def test_transaction_accepts_native_types(backend, table_client):          # settles the UNVERIFIED assumption
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0, seq=3, cost_usd=0.0021, usage={"in": 3}))
    [turn] = await backend.query_turn_window("u", "a", "s", 5)
    assert turn["cost_usd"] == 0.0021 and turn["usage"] == {"in": 3} and turn["sequence"] == 3


async def test_item_layout_and_no_ttl_on_tombstones(backend, table_client):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0, seq=7))
    await backend.put_tombstone("u", "a", "gone")
    await backend.put_tombstone("u", "a", "gone", turn_id="t9")
    by_sk = {i["SK"]: i for i in _scan(table_client)}
    micros = int((T0 - datetime(1970, 1, 1, tzinfo=UTC)) / timedelta(microseconds=1))
    chrono_sk = f"THREAD#s#CHRONO#{micros:020d}#{7:012d}#t1"
    assert by_sk["THREAD#s#TURN#t1"]["chrono_sk"] == chrono_sk and chrono_sk in by_sk
    assert by_sk["INDEXSTATE#s"]["state"] == "ready"
    for sk in ("TOMB#gone", "TOMB#gone#TURN#t9", "INDEXSTATE#s"):
        assert "ttl" not in by_sk[sk]                                     # DynamoDB TTL must never reap a guard
    assert "ttl" in by_sk["THREAD#s#TURN#t1"] and "ttl" in by_sk[chrono_sk]


async def test_rejected_put_writes_nothing(backend, table_client):
    await backend.put_tombstone("u", "a", "s")
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    assert not [i for i in _scan(table_client) if i["SK"].startswith("THREAD#s")]    # atomic: no canonical, no companion
    assert not [i for i in _scan(table_client) if i["SK"].startswith("INDEXSTATE#")]


async def test_tombstone_landing_between_read_and_write_is_fenced(backend, table_client):
    real = backend._get_item
    state = {"fired": False}

    async def get_then_tombstone(pk, sk):
        item = await real(pk, sk)
        if not state["fired"] and sk.startswith("THREAD#s#TURN#"):
            state["fired"] = True
            await backend.put_tombstone("u", "a", "s")                  # a real tombstone lands mid-flight
        return item
    backend._get_item = get_then_tombstone
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    assert not [i for i in _scan(table_client) if i["SK"].startswith("THREAD#s")]


async def test_lost_ordering_race_converges_on_the_first_writer(backend, table_client):
    real_get, real_put = backend._get_item, ConversationDynamoDB.put_turn
    state = {"fired": False}

    async def get_after_rival(pk, sk):
        if not state["fired"] and sk == "THREAD#s#TURN#t1":
            state["fired"] = True
            backend._get_item = real_get                                # let the rival write through cleanly
            await real_put(backend, "u", "a", "s", "t1", _row(1, T0, seq=1, assistant_response="rival"))
            backend._get_item = get_after_rival
            return None                                                 # ...but WE still believe the turn is new
        return await real_get(pk, sk)
    backend._get_item = get_after_rival
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0 + timedelta(hours=1), seq=9, assistant_response="late"))
    backend._get_item = real_get
    chrono = [i for i in _scan(table_client) if "#CHRONO#" in i["SK"]]
    assert len(chrono) == 1 and chrono[0]["SK"].endswith("#000000000001#t1")        # first writer's ordering kept
    [turn] = await backend.query_turn_window("u", "a", "s", 5)
    assert turn["assistant_response"] == "late" and turn["sequence"] == 1


async def test_window_skips_tombstoned_turns_and_still_fills(backend):
    for i in range(5):
        await backend.put_turn("u", "a", "s", f"t{i}", _row(i, T0 + timedelta(seconds=i)))
    await backend.put_tombstone("u", "a", "s", turn_id="t4")            # newest, tombstoned but not yet deleted
    window = await backend.query_turn_window("u", "a", "s", 3)
    assert [t["turn_id"] for t in window] == ["t1", "t2", "t3"]


async def test_cascade_removes_companions_but_not_tombstones(backend, table_client):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    await backend.put_tombstone("u", "a", "s")
    await backend.delete_thread_cascade("u", "a", "s")
    sks = {i["SK"] for i in _scan(table_client)}
    assert "TOMB#s" in sks and not any(sk.startswith("THREAD#s") for sk in sks)


async def test_delete_turn_removes_companion(backend, table_client):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    assert await backend.delete_turn("u", "a", "s", "t1") is True
    assert not [i for i in _scan(table_client) if "#CHRONO#" in i["SK"]]


async def test_legacy_items_backfill_then_ready(backend, table_client):
    ids = (durable_contract.USER, durable_contract.AGENT)
    legacy = [("zz-late", T0 + timedelta(minutes=2)), ("aa-early", T0), ("mm-same", T0 + timedelta(minutes=2))]
    _seed_legacy(table_client, "good", [{"turn_id": t, "timestamp": ts.isoformat()} for t, ts in legacy])
    _seed_legacy(table_client, "bad", [{"turn_id": "x", "timestamp": "garbage"}])
    assert await backend.get_index_state(*ids, "good") == "pending"
    with pytest.raises(IndexNotReadyError):
        await backend.query_turn_window(*ids, "good", 10)
    processed, cursor, invalid = 0, None, set()
    while True:                                                          # Scan pages: drive until the cursor is exhausted
        batch = await backend.backfill_batch(cursor, 2)
        processed, cursor = processed + batch.processed, batch.next_cursor
        invalid |= set(batch.invalid_sessions)
        if cursor is None:
            break
    assert processed == 3 and len(invalid) == 1
    assert await backend.get_index_state(*ids, "good") == "ready"
    assert await backend.get_index_state(*ids, "bad") == "invalid"
    assert [t["turn_id"] for t in await backend.query_turn_window(*ids, "good", 10)] == [
        "aa-early", "mm-same", "zz-late"]
    assert (await backend.backfill_batch(None, 100)).processed == 0      # idempotent


async def test_queries_raise_when_disconnected_or_failing(endpoint):
    b = ConversationDynamoDB(TABLES[0], TABLES[1], {**CREDS, "endpoint_url": endpoint})   # never initialized
    for call in (lambda: b.put_turn("u", "a", "s", "t", {}), lambda: b.query_turns("u", "a", "s"),
                 lambda: b.query_turn_window("u", "a", "s", 5), lambda: b.is_deleted("u", "a", "s"),
                 lambda: b.get_index_state("u", "a", "s"), lambda: b.put_tombstone("u", "a", "s")):
        with pytest.raises(StorageUnavailableError):
            await call()


async def test_failed_write_is_typed_and_leaves_nothing(backend, table_client):
    async with _inject_write_failure(backend):
        with pytest.raises(StorageWriteError):
            await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    assert not [i for i in _scan(table_client) if i["SK"].startswith("THREAD#s")]
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0))            # recovers
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at `sdd/specs/durable-conversation-memory.spec.md` (§2 Piece 1/2, §3 Modules 4 and 8, §4 backend contract suite, §5) and TASK-5574 (reference semantics)
3. **Check dependencies** — TASK-5570 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`
4. **Verify the Codebase Contract** — confirm every signature above and the abstract signatures TASK-5570 wrote; update the contract first if something changed
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Blueprint; complete every `# FILL IN:`; never change a fixed signature or path; do the native-types verification (Steps, item 2) BEFORE building on it
7. **Verify** all acceptance criteria and run the Validation Commands in an environment with `moto[server]`; record the mutation-check results 
8. **Commit the code** — stage only the three files this task lists
9. **Close the task** with `parrot sdd task close TASK-5577 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
