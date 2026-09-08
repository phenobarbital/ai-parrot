"""Cross-worker broadcast registry backed by Redis (FEAT-537 — Module 2).

Production implementation of :class:`~.registry.BroadcastRegistry`.  Spec §2:
"persist scoped metadata, moderation and admission state in Redis so another
worker can serve participants or request shutdown … Admission is atomic across
workers: pending plus active reservations must never exceed ten."

**Every compound operation is one Lua script.**  Admission, ownership claim,
the floor barrier, departure-with-succession, election, transition and socket
binding all read *and* write inside a single atomic server-side call, so two
workers racing on the same broadcast cannot interleave a read with the other's
write.  Nothing here does read-modify-write from Python.

Key layout, namespaced by tenant and broadcast id::

    {prefix}:{tenant}:{bid}:descriptor      JSON BroadcastDescriptor
    {prefix}:{tenant}:{bid}:leases          hash lease_id -> JSON lease envelope
    {prefix}:{tenant}:{bid}:tombstones      zset livekit_identity -> expiry
    {prefix}:{tenant}:{bid}:hands           zset lease_id -> sequence
    {prefix}:{tenant}:{bid}:owner           string "<worker_id>:<epoch>"
    {prefix}:{tenant}:{bid}:stop            string, moderator lease that stopped it
    {prefix}:{tenant}:{bid}:meta            hash of registry-internal scalars
    {prefix}:{tenant}:index                 set of live broadcast ids

Nothing secret is ever written: the descriptor carries no token by
construction, ``owner_worker_id`` is an opaque worker id (never a network
address — address resolution belongs to the service layer), and no PCM, AWS
credential or LiveAvatar access token touches these keys.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from parrot.integrations.liveavatar.broadcast.errors import (
    BroadcastError,
    BroadcastTerminal,
    FloorNotGranted,
    IdentityTombstoned,
    NotModerator,
    NotOwner,
    NotSpeaker,
    SpeakerConnectionExists,
    StaleFloorEpoch,
    StaleVersion,
    ViewerLimitReached,
)
from parrot.integrations.liveavatar.broadcast.models import (
    CONTROL_EXPIRY_S,
    OWNER_LEASE_TTL_S,
    PENDING_TTL_S,
    TERMINAL_RETENTION_S,
    VIEWER_CREDENTIAL_TTL_S,
    BroadcastDescriptor,
    BroadcastReason,
    BroadcastState,
    ParticipantPrincipal,
    ViewerLease,
)
from parrot.integrations.liveavatar.broadcast.registry import (
    _ALLOWED_TRANSITIONS,
    Admission,
    BroadcastRegistry,
    ExpiryEvent,
    ExpiryKind,
    ReleaseOutcome,
)

DEFAULT_KEY_PREFIX: str = "parrot:voice-broadcast"

#: Reverse of the shared state graph: target state -> CSV of states it may be
#: entered from.  Derived from the single definition in ``registry.py`` so the
#: Lua guard and the in-memory reference can never disagree about a legal edge.
_LEGAL_SOURCES: Dict[BroadcastState, str] = {
    target: ",".join(source.value for source, targets in _ALLOWED_TRANSITIONS.items() if target in targets)
    for target in BroadcastState
}

#: Lua error code → typed exception.  The Lua side speaks only these codes so a
#: server-side rejection surfaces as the same exception the in-memory reference
#: raises for the same situation.
_ERROR_MAP: Dict[str, type[BroadcastError]] = {
    "terminal": BroadcastTerminal,
    "viewer_limit_reached": ViewerLimitReached,
    "identity_tombstoned": IdentityTombstoned,
    "stale_version": StaleVersion,
    "stale_floor_epoch": StaleFloorEpoch,
    "floor_not_granted": FloorNotGranted,
    "unknown_lease": FloorNotGranted,
    "speaker_connection_exists": SpeakerConnectionExists,
    "not_moderator": NotModerator,
    "not_speaker": NotSpeaker,
    "not_owner": NotOwner,
}


def _utc(now: float) -> datetime:
    """Convert epoch seconds to an aware UTC datetime."""
    return datetime.fromtimestamp(now, tz=timezone.utc)


def _iso(now: float) -> str:
    """Format epoch seconds as the ISO-8601 string Pydantic round-trips."""
    return _utc(now).isoformat()


# ── Lua ────────────────────────────────────────────────────────────────────
#
# KEYS are always, in order:
#   1 descriptor  2 leases  3 tombstones  4 hands  5 owner  6 stop  7 meta
#   8 tenant index
# ARGV[1] is always ``now`` (epoch seconds) and ARGV[2] its ISO form, so every
# script stamps time from one source.

_PRELUDE = """
local K_DESC, K_LEASES, K_TOMB, K_HANDS, K_OWNER, K_STOP, K_META, K_INDEX =
  KEYS[1], KEYS[2], KEYS[3], KEYS[4], KEYS[5], KEYS[6], KEYS[7], KEYS[8]
local NOW = tonumber(ARGV[1])
local NOW_ISO = ARGV[2]

-- cjson decodes JSON null to cjson.null, which is TRUTHY in Lua.  Every read
-- of an optional field must go through nz() or the null will be mistaken for
-- a real value (e.g. a null moderator_lease_id would "match" a caller).
local function nz(v)
  if v == nil or v == cjson.null then return nil end
  return v
end

local function fail(code) return redis.error_reply(code) end

local function load_desc()
  local raw = redis.call('GET', K_DESC)
  if not raw then return nil end
  return cjson.decode(raw)
end

local function save_desc(d) redis.call('SET', K_DESC, cjson.encode(d)) end

local function touch(d, bump)
  d.updated_at = NOW_ISO
  if bump then d.version = d.version + 1 end
end

local function is_terminal(d)
  return d.state == 'ended' or d.state == 'failed'
end

local function meta_num(field, default)
  local v = redis.call('HGET', K_META, field)
  if not v then return default end
  return tonumber(v)
end

local function load_lease(lease_id)
  local raw = redis.call('HGET', K_LEASES, lease_id)
  if not raw then return nil end
  return cjson.decode(raw)
end

local function save_lease(env) redis.call('HSET', K_LEASES, env.lease.lease_id, cjson.encode(env)) end

local function all_leases()
  local flat = redis.call('HGETALL', K_LEASES)
  local out = {}
  for i = 1, #flat, 2 do out[#out + 1] = cjson.decode(flat[i + 1]) end
  table.sort(out, function(a, b)
    return a.lease.admission_sequence < b.lease.admission_sequence
  end)
  return out
end

local function prune_tombstones()
  redis.call('ZREMRANGEBYSCORE', K_TOMB, '-inf', '(' .. NOW)
end

local function occupied()
  prune_tombstones()
  return redis.call('HLEN', K_LEASES) + redis.call('ZCARD', K_TOMB)
end

-- Descriptor hand_requests and the hands zset are written together, always in
-- the same script, so the ordering index cannot drift from the projection the
-- browser reads.
local function drop_hand(d, lease_id)
  redis.call('ZREM', K_HANDS, lease_id)
  local kept, changed = {}, false
  for _, hand in ipairs(d.hand_requests) do
    if hand.lease_id == lease_id then changed = true else kept[#kept + 1] = hand end
  end
  d.hand_requests = kept
  return changed
end

local function require_moderator(d, lease_id)
  local mod = nz(d.moderator_lease_id)
  if mod == nil or mod ~= lease_id then return fail('not_moderator') end
  return nil
end

-- The single place the floor barrier opens.  Grant, revoke, Finish Speaking,
-- speaker departure and election all fence identically through here.
local function open_barrier(d, target)
  local speaker = nz(d.speaker_lease_id)
  if speaker then
    local env = load_lease(speaker)
    if env then env.lease.speaker_socket_id = cjson.null; save_lease(env) end
  end
  d.speaker_lease_id = cjson.null
  d.floor_epoch = d.floor_epoch + 1
  d.floor_state = 'switching'
  if target then
    redis.call('HSET', K_META, 'pending_floor_target', target)
    drop_hand(d, target)
  else
    redis.call('HDEL', K_META, 'pending_floor_target')
  end
  touch(d, true)
end

local function eligible_moderators()
  local out = {}
  for _, env in ipairs(all_leases()) do
    if env.lease.state == 'active' and env.lease.confirmed
       and env.t.hb ~= nil and (NOW - env.t.hb) <= tonumber(ARGV[3] or '15') then
      out[#out + 1] = env
    end
  end
  return out
end

local function elect(d)
  local candidates = eligible_moderators()
  if #candidates == 0 then
    d.moderator_lease_id = cjson.null
    return nil
  end
  local elected = candidates[1].lease.lease_id
  d.moderator_lease_id = elected
  drop_hand(d, elected)
  open_barrier(d, elected)
  return elected
end

local function end_bcast(d, reason)
  if is_terminal(d) then return end
  d.state = 'ended'
  d.failure_reason = reason
  d.ended_at = NOW_ISO
  d.floor_state = 'idle'
  d.speaker_lease_id = cjson.null
  d.moderator_lease_id = cjson.null
  redis.call('HDEL', K_META, 'pending_floor_target')
  redis.call('HSET', K_META, 'terminal_at', NOW)
  touch(d, true)
end
"""

_SCRIPTS: Dict[str, str] = {}

# create(descriptor_json) -> descriptor_json
_SCRIPTS["create"] = """
if redis.call('EXISTS', K_DESC) == 1 then return fail('already_exists') end
local d = cjson.decode(ARGV[4])
d.created_at = NOW_ISO
d.updated_at = NOW_ISO
save_desc(d)
redis.call('HSET', K_META, 'created_at', NOW, 'hand_sequence', 0)
redis.call('SADD', K_INDEX, ARGV[5])
return cjson.encode(d)
"""

# get() -> descriptor_json | nil
_SCRIPTS["get"] = """
local raw = redis.call('GET', K_DESC)
if not raw then return nil end
return raw
"""

# reserve_viewer(principal_json, livekit_identity, credential_ttl) -> {lease_json, is_first}
_SCRIPTS["reserve_viewer"] = """
local d = load_desc()
if not d then return fail('terminal') end
if is_terminal(d) then return fail('terminal') end

local identity = ARGV[5]
local tomb = redis.call('ZSCORE', K_TOMB, identity)
if tomb and tonumber(tomb) > NOW then return fail('identity_tombstoned') end

if occupied() >= d.max_viewers then return fail('viewer_limit_reached') end

d.admission_sequence = d.admission_sequence + 1
local ttl = tonumber(ARGV[6])
local expires_iso = ARGV[7]
local lease = {
  lease_id = ARGV[8],
  principal = cjson.decode(ARGV[4]),
  livekit_identity = identity,
  state = 'pending',
  credential_expires_at = expires_iso,
  admission_deadline = expires_iso,
  confirmed = false,
  admission_sequence = d.admission_sequence,
  last_control_heartbeat = cjson.null,
  speaker_socket_id = cjson.null,
}
local env = { lease = lease, t = { hb = cjson.null, cred = NOW + ttl, deadline = NOW + ttl } }
save_lease(env)

local is_first = 0
if nz(d.moderator_lease_id) == nil and redis.call('HLEN', K_LEASES) == 1 then
  -- Moderator is decided here and nowhere else.
  d.moderator_lease_id = lease.lease_id
  d.speaker_lease_id = lease.lease_id
  d.floor_epoch = 1
  d.floor_state = 'granted'
  redis.call('HDEL', K_META, 'pending_floor_target')
  is_first = 1
end
touch(d, true)
save_desc(d)
return { cjson.encode(lease), is_first }
"""

# confirm_viewer(lease_id) -> lease_json
_SCRIPTS["confirm_viewer"] = """
local d = load_desc()
if not d then return fail('terminal') end
local env = load_lease(ARGV[4])
if not env then return fail('unknown_lease') end
env.lease.state = 'active'
env.lease.confirmed = true
if env.t.hb == nil or env.t.hb == cjson.null then
  env.t.hb = NOW
  env.lease.last_control_heartbeat = NOW_ISO
end
save_lease(env)
touch(d, true)
save_desc(d)
return cjson.encode(env.lease)
"""

# heartbeat_control(lease_id) -> 1
_SCRIPTS["heartbeat_control"] = """
local d = load_desc()
if not d then return fail('terminal') end
local env = load_lease(ARGV[4])
if not env then return fail('unknown_lease') end
env.t.hb = NOW
env.lease.last_control_heartbeat = NOW_ISO
save_lease(env)
-- Heartbeats never bump the public version (spec §2).
touch(d, false)
save_desc(d)
return 1
"""

# release_viewer(lease_id) -> {audience_empty, floor_returned_to, new_moderator}
_SCRIPTS["release_viewer"] = """
local d = load_desc()
if not d then return fail('terminal') end
local lease_id = ARGV[4]
local env = load_lease(lease_id)
if not env then
  local empty = 0
  if redis.call('HLEN', K_LEASES) == 0 then empty = 1 end
  return { empty, '', '' }
end
redis.call('HDEL', K_LEASES, lease_id)

local cred = env.t.cred
if cred == nil or cred == cjson.null or cred < NOW then cred = NOW + tonumber(ARGV[5]) end
redis.call('ZADD', K_TOMB, cred, env.lease.livekit_identity)

drop_hand(d, lease_id)
local was_speaker = (nz(d.speaker_lease_id) == lease_id)
local was_moderator = (nz(d.moderator_lease_id) == lease_id)
local floor_returned_to, new_moderator = '', ''

if redis.call('HLEN', K_LEASES) == 0 then
  end_bcast(d, 'audience_empty')
  save_desc(d)
  return { 1, '', '' }
end

if was_moderator then
  d.moderator_lease_id = cjson.null
  local elected = elect(d)
  if elected == nil then
    end_bcast(d, 'audience_empty')
    save_desc(d)
    return { 1, '', '' }
  end
  new_moderator = elected
  floor_returned_to = elected
elseif was_speaker then
  local mod = nz(d.moderator_lease_id)
  open_barrier(d, mod)
  floor_returned_to = mod or ''
else
  touch(d, true)
end
save_desc(d)
return { 0, floor_returned_to, new_moderator }
"""

# list_leases() -> array of lease JSON
_SCRIPTS["list_leases"] = """
local out = {}
for _, env in ipairs(all_leases()) do out[#out + 1] = cjson.encode(env.lease) end
return out
"""

# claim_owner(worker_id, ttl) -> {claimed, owner_epoch}
_SCRIPTS["claim_owner"] = """
local d = load_desc()
if not d then return fail('terminal') end
if is_terminal(d) then return fail('terminal') end
local worker = ARGV[4]
local ttl = tonumber(ARGV[5])
local expires = meta_num('owner_expires_at', 0)
local current = nz(d.owner_worker_id)
local live = (current ~= nil and expires > NOW)

if live and current ~= worker then return { 0, d.owner_epoch } end
if live and current == worker then
  redis.call('HSET', K_META, 'owner_expires_at', NOW + ttl)
  redis.call('SET', K_OWNER, worker .. ':' .. d.owner_epoch, 'PX', math.floor(ttl * 4000))
  return { 1, d.owner_epoch }
end
d.owner_worker_id = worker
d.owner_epoch = d.owner_epoch + 1
redis.call('HSET', K_META, 'owner_expires_at', NOW + ttl)
redis.call('SET', K_OWNER, worker .. ':' .. d.owner_epoch, 'PX', math.floor(ttl * 4000))
touch(d, true)
save_desc(d)
return { 1, d.owner_epoch }
"""

# renew_owner(worker_id, owner_epoch, ttl) -> 0|1
_SCRIPTS["renew_owner"] = """
local d = load_desc()
if not d then return 0 end
if nz(d.owner_worker_id) ~= ARGV[4] then return 0 end
if d.owner_epoch ~= tonumber(ARGV[5]) then return 0 end
local expires = meta_num('owner_expires_at', 0)
if expires <= NOW then return 0 end
local ttl = tonumber(ARGV[6])
redis.call('HSET', K_META, 'owner_expires_at', NOW + ttl)
redis.call('SET', K_OWNER, ARGV[4] .. ':' .. d.owner_epoch, 'PX', math.floor(ttl * 4000))
return 1
"""

# transition(new_state, expected_owner_epoch, output_epoch|'', reason|'',
#            allowed_csv, terminal_ttl) -> descriptor_json
_SCRIPTS["transition"] = """
local d = load_desc()
if not d then return fail('terminal') end
if d.owner_epoch ~= tonumber(ARGV[5]) then return fail('not_owner') end
if is_terminal(d) then return fail('terminal') end
local new_state = ARGV[4]
if new_state ~= d.state then
  -- ARGV[8] is the CSV of states from which new_state is reachable, so the
  -- graph stays defined once in Python (_ALLOWED_TRANSITIONS) instead of
  -- being re-encoded in Lua where it could drift.
  local ok = false
  for source in string.gmatch(ARGV[8], '[^,]+') do
    if source == d.state then ok = true end
  end
  if not ok then return fail('illegal_transition') end
end
if ARGV[6] ~= '' then
  local oe = tonumber(ARGV[6])
  if oe < d.output_epoch then return fail('non_monotonic_output_epoch') end
  d.output_epoch = oe
end
if ARGV[7] ~= '' then d.failure_reason = ARGV[7] end
if new_state == 'starting' and nz(d.started_at) == nil then d.started_at = NOW_ISO end
d.state = new_state
if is_terminal(d) then
  d.ended_at = NOW_ISO
  d.floor_state = 'idle'
  d.speaker_lease_id = cjson.null
  redis.call('HDEL', K_META, 'pending_floor_target')
  redis.call('HSET', K_META, 'terminal_at', NOW)
end
touch(d, true)
save_desc(d)
return cjson.encode(d)
"""

# raise_hand(lease_id) -> descriptor_json
_SCRIPTS["raise_hand"] = """
local d = load_desc()
if not d then return fail('terminal') end
if is_terminal(d) then return fail('terminal') end
local lease_id = ARGV[4]
local env = load_lease(lease_id)
if not env then return fail('unknown_lease') end
if redis.call('ZSCORE', K_HANDS, lease_id) == false then
  local seq = meta_num('hand_sequence', 0) + 1
  redis.call('HSET', K_META, 'hand_sequence', seq)
  redis.call('ZADD', K_HANDS, seq, lease_id)
  d.hand_requests[#d.hand_requests + 1] = {
    lease_id = lease_id,
    display_name = env.lease.principal.display_name,
    sequence = seq,
    requested_at = NOW_ISO,
  }
  touch(d, true)
  save_desc(d)
end
return cjson.encode(d)
"""

# cancel_hand(lease_id) -> descriptor_json
_SCRIPTS["cancel_hand"] = """
local d = load_desc()
if not d then return fail('terminal') end
if drop_hand(d, ARGV[4]) then touch(d, true); save_desc(d) end
return cjson.encode(d)
"""

# dismiss_hand(moderator_lease_id, target_lease_id) -> descriptor_json
_SCRIPTS["dismiss_hand"] = """
local d = load_desc()
if not d then return fail('terminal') end
local denied = require_moderator(d, ARGV[4])
if denied then return denied end
if drop_hand(d, ARGV[5]) then touch(d, true); save_desc(d) end
return cjson.encode(d)
"""

# grant_floor(moderator_lease_id, target_lease_id|'', expected_version) -> descriptor_json
_SCRIPTS["grant_floor"] = """
local d = load_desc()
if not d then return fail('terminal') end
if is_terminal(d) then return fail('terminal') end
local denied = require_moderator(d, ARGV[4])
if denied then return denied end
if d.version ~= tonumber(ARGV[6]) then return fail('stale_version') end
if d.floor_state == 'switching' then return fail('stale_version') end
local target = ARGV[5]
if target == '' then target = ARGV[4] end
local env = load_lease(target)
if not env or env.lease.state ~= 'active' then return fail('floor_not_granted') end
open_barrier(d, target)
save_desc(d)
return cjson.encode(d)
"""

# commit_floor(target_lease_id, floor_epoch) -> descriptor_json
_SCRIPTS["commit_floor"] = """
local d = load_desc()
if not d then return fail('terminal') end
if d.floor_state ~= 'switching' or d.floor_epoch ~= tonumber(ARGV[5]) then
  return fail('stale_floor_epoch')
end
local target = ARGV[4]
local pending = redis.call('HGET', K_META, 'pending_floor_target')
if pending ~= target then return fail('floor_not_granted') end
if not load_lease(target) then
  d.floor_state = 'idle'
  redis.call('HDEL', K_META, 'pending_floor_target')
  touch(d, true)
  save_desc(d)
  return fail('floor_not_granted')
end
d.speaker_lease_id = target
d.floor_state = 'granted'
redis.call('HDEL', K_META, 'pending_floor_target')
touch(d, true)
save_desc(d)
return cjson.encode(d)
"""

# abort_floor(floor_epoch) -> descriptor_json
_SCRIPTS["abort_floor"] = """
local d = load_desc()
if not d then return fail('terminal') end
if d.floor_state ~= 'switching' or d.floor_epoch ~= tonumber(ARGV[4]) then
  return fail('stale_floor_epoch')
end
d.floor_state = 'idle'
d.speaker_lease_id = cjson.null
redis.call('HDEL', K_META, 'pending_floor_target')
touch(d, true)
save_desc(d)
return cjson.encode(d)
"""

# release_floor(speaker_lease_id) -> descriptor_json
_SCRIPTS["release_floor"] = """
local d = load_desc()
if not d then return fail('terminal') end
if is_terminal(d) then return fail('terminal') end
if nz(d.speaker_lease_id) ~= ARGV[4] then return fail('not_speaker') end
open_barrier(d, nz(d.moderator_lease_id))
save_desc(d)
return cjson.encode(d)
"""

# elect_moderator() -> lease_id | ''
_SCRIPTS["elect_moderator"] = """
local d = load_desc()
if not d then return fail('terminal') end
if is_terminal(d) then return fail('terminal') end
local elected = elect(d)
save_desc(d)
return elected or ''
"""

# bind_speaker_socket(lease_id, socket_id, floor_epoch) -> 1
_SCRIPTS["bind_speaker_socket"] = """
local d = load_desc()
if not d then return fail('terminal') end
if d.floor_state ~= 'granted' then return fail('floor_not_granted') end
if nz(d.speaker_lease_id) ~= ARGV[4] then return fail('floor_not_granted') end
if d.floor_epoch ~= tonumber(ARGV[6]) then return fail('stale_floor_epoch') end
local env = load_lease(ARGV[4])
if not env then return fail('unknown_lease') end
local bound = nz(env.lease.speaker_socket_id)
if bound ~= nil and bound ~= ARGV[5] then return fail('speaker_connection_exists') end
env.lease.speaker_socket_id = ARGV[5]
save_lease(env)
return 1
"""

# unbind_speaker_socket(lease_id, socket_id) -> 0|1
_SCRIPTS["unbind_speaker_socket"] = """
local env = load_lease(ARGV[4])
if not env then return 0 end
if nz(env.lease.speaker_socket_id) ~= ARGV[5] then return 0 end
env.lease.speaker_socket_id = cjson.null
save_lease(env)
return 1
"""

# request_stop(by_lease_id) -> descriptor_json
_SCRIPTS["request_stop"] = """
local d = load_desc()
if not d then return fail('terminal') end
local denied = require_moderator(d, ARGV[4])
if denied then return denied end
if redis.call('EXISTS', K_STOP) == 0 then
  redis.call('SET', K_STOP, ARGV[4])
  d.failure_reason = 'stopped_by_moderator'
  touch(d, true)
  save_desc(d)
end
return cjson.encode(d)
"""

# stop_requested() -> 0|1  (1 also when the record is gone: fail closed)
_SCRIPTS["stop_requested"] = """
if redis.call('EXISTS', K_DESC) == 0 then return 1 end
return redis.call('EXISTS', K_STOP)
"""

# expire(pending_ttl, terminal_ttl, control_expiry, index_member)
#   -> array of "kind|lease_id|detail"
_SCRIPTS["expire"] = """
local d = load_desc()
if not d then return {} end
local events = {}
local function emit(kind, lease_id, detail)
  events[#events + 1] = kind .. '|' .. (lease_id or '') .. '|' .. detail
end

local stale_tombs = redis.call('ZRANGEBYSCORE', K_TOMB, '-inf', '(' .. NOW)
for _ = 1, #stale_tombs do emit('tombstone', '', 'identity reusable again') end
prune_tombstones()

if is_terminal(d) then
  local terminal_at = meta_num('terminal_at', NOW)
  if (NOW - terminal_at) >= tonumber(ARGV[5]) then
    redis.call('DEL', K_DESC, K_LEASES, K_TOMB, K_HANDS, K_OWNER, K_STOP, K_META)
    redis.call('SREM', K_INDEX, ARGV[7])
    emit('terminal_retention', '', 'sanitized terminal state expired')
  end
  return events
end

if d.state == 'pending' and redis.call('HLEN', K_LEASES) == 0
   and (NOW - meta_num('created_at', NOW)) >= tonumber(ARGV[4]) then
  end_bcast(d, 'pending_expired')
  save_desc(d)
  emit('pending_broadcast', '', 'no admission within the pending TTL')
  return events
end

local dirty = false
local owner = nz(d.owner_worker_id)
if owner ~= nil and meta_num('owner_expires_at', 0) <= NOW then
  d.owner_worker_id = cjson.null
  redis.call('HDEL', K_META, 'owner_expires_at')
  redis.call('DEL', K_OWNER)
  d.failure_reason = 'owner_lost'
  dirty = true
  emit('owner_lease', '', 'fenced expired owner ' .. owner)
end

for _, env in ipairs(all_leases()) do
  local lease = env.lease
  if lease.state ~= 'leaving' then
    local deadline = env.t.deadline
    if (not lease.confirmed) and deadline ~= nil and deadline ~= cjson.null
       and deadline <= NOW then
      lease.state = 'leaving'
      save_lease(env)
      dirty = true
      emit('admission_deadline', lease.lease_id, 'pending seat never confirmed')
    elseif lease.confirmed and env.t.hb ~= nil and env.t.hb ~= cjson.null
           and (NOW - env.t.hb) > tonumber(ARGV[6]) then
      lease.state = 'leaving'
      save_lease(env)
      dirty = true
      emit('control_heartbeat', lease.lease_id,
           'control heartbeat expired; remove from room first')
    end
  end
end

if dirty or #events > 0 then touch(d, true); save_desc(d) end
return events
"""


class RedisBroadcastRegistry(BroadcastRegistry):
    """Redis-backed, cross-worker :class:`BroadcastRegistry`.

    Args:
        redis_client: An ``redis.asyncio.Redis`` with ``decode_responses=True``.
        key_prefix: Namespace for every key this registry owns.
        clock: Optional client-side clock.  Production leaves this ``None`` so
            every script stamps time from **Redis** ``TIME`` — the single clock
            all workers share.  Tests inject a fake clock so TTL behaviour is
            deterministic without sleeping.
        owns_client: Whether :meth:`aclose` should close ``redis_client``.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        clock: Optional[Callable[[], float]] = None,
        owns_client: bool = False,
    ) -> None:
        self._redis = redis_client
        self._prefix = key_prefix
        self._clock = clock
        self._owns_client = owns_client
        self._scripts = {name: redis_client.register_script(_PRELUDE + body) for name, body in _SCRIPTS.items()}
        self.logger = logging.getLogger(__name__)

    # ── Construction / teardown ────────────────────────────────────────

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        clock: Optional[Callable[[], float]] = None,
    ) -> "RedisBroadcastRegistry":
        """Build a registry from a Redis URL (lazy ``redis.asyncio`` import).

        Args:
            redis_url: Standard ``redis://`` URL.
            key_prefix: Namespace for every key this registry owns.
            clock: Optional client-side clock override (tests only).

        Returns:
            A ready registry owning its own connection pool.
        """
        import redis.asyncio as aioredis

        return cls(
            aioredis.from_url(redis_url, decode_responses=True),
            key_prefix=key_prefix,
            clock=clock,
            owns_client=True,
        )

    async def ping(self) -> bool:
        """Verify the Redis connection.  Raises the driver's error when down."""
        return bool(await self._redis.ping())

    async def aclose(self) -> None:
        """Close the underlying client when this registry owns it."""
        if not self._owns_client:
            return
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def purge_all_for_tests(self) -> int:
        """Delete every key under this registry's prefix.  Test helper only.

        Returns:
            Number of keys removed.
        """
        removed = 0
        pattern = f"{self._prefix}:*"
        async for key in self._redis.scan_iter(match=pattern, count=500):
            await self._redis.delete(key)
            removed += 1
        return removed

    # ── Plumbing ───────────────────────────────────────────────────────

    def _keys(self, tenant_id: str, broadcast_id: str) -> List[str]:
        """Return the eight keys every script takes, in the fixed order."""
        base = f"{self._prefix}:{tenant_id}:{broadcast_id}"
        return [
            f"{base}:descriptor",
            f"{base}:leases",
            f"{base}:tombstones",
            f"{base}:hands",
            f"{base}:owner",
            f"{base}:stop",
            f"{base}:meta",
            f"{self._prefix}:{tenant_id}:index",
        ]

    async def _now(self, now: Optional[float]) -> float:
        """Resolve the authoritative timestamp for an operation.

        Precedence: explicit ``now`` → injected clock → Redis ``TIME``.  In
        production the last branch wins, so all workers share one clock.
        """
        if now is not None:
            return now
        if self._clock is not None:
            return self._clock()
        seconds, microseconds = await self._redis.time()
        return float(seconds) + float(microseconds) / 1_000_000

    async def _run(
        self,
        name: str,
        tenant_id: str,
        broadcast_id: str,
        now: float,
        *extra: Any,
    ) -> Any:
        """Execute one Lua script and translate its error reply.

        Args:
            name: Script key in :data:`_SCRIPTS`.
            tenant_id: Tenant scope.
            broadcast_id: Broadcast scope.
            now: Authoritative epoch seconds.
            *extra: Script-specific ARGV from index 4 onwards.

        Returns:
            Whatever the script returned.

        Raises:
            BroadcastError: Mapped from the script's ``redis.error_reply``.
        """
        from redis.exceptions import ResponseError

        argv: List[Any] = [f"{now:.6f}", _iso(now), str(CONTROL_EXPIRY_S), *extra]
        try:
            return await self._scripts[name](keys=self._keys(tenant_id, broadcast_id), args=argv)
        except ResponseError as exc:
            code = str(exc).strip()
            mapped = _ERROR_MAP.get(code)
            if mapped is not None:
                raise mapped(message=f"{name}: {code}") from exc
            if code == "already_exists":
                raise BroadcastError(message="broadcast already exists") from exc
            if code in ("illegal_transition", "non_monotonic_output_epoch"):
                raise ValueError(f"{name}: {code}") from exc
            raise

    @staticmethod
    def _normalise(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Repair the one cjson asymmetry that bites round-tripping.

        Redis's cjson encodes an **empty Lua table as ``{}``**, so a list field
        that Lua emptied comes back as an object.  Pydantic would reject it.
        """
        if isinstance(payload.get("hand_requests"), dict):
            payload["hand_requests"] = []
        principal = payload.get("principal")
        if isinstance(principal, dict) and isinstance(principal.get("roles"), dict):
            principal["roles"] = []
        return payload

    @classmethod
    def _descriptor(cls, raw: str) -> BroadcastDescriptor:
        """Deserialise a descriptor emitted by Lua."""
        return BroadcastDescriptor.model_validate(cls._normalise(json.loads(raw)))

    @classmethod
    def _lease(cls, raw: str) -> ViewerLease:
        """Deserialise a lease emitted by Lua."""
        return ViewerLease.model_validate(cls._normalise(json.loads(raw)))

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def create(self, descriptor: BroadcastDescriptor) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run(
            "create",
            descriptor.tenant_id,
            descriptor.broadcast_id,
            now,
            descriptor.model_dump_json(),
            descriptor.broadcast_id,
        )
        self.logger.info(
            "broadcast %s created for agent %s",
            descriptor.broadcast_id,
            descriptor.agent_id,
        )
        return self._descriptor(raw)

    async def get(self, tenant_id: str, broadcast_id: str) -> Optional[BroadcastDescriptor]:
        now = await self._now(None)
        raw = await self._run("get", tenant_id, broadcast_id, now)
        return None if raw is None else self._descriptor(raw)

    async def transition(
        self,
        tenant_id: str,
        broadcast_id: str,
        new_state: BroadcastState,
        *,
        output_epoch: Optional[int] = None,
        reason: Optional[BroadcastReason] = None,
        expected_owner_epoch: int,
    ) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run(
            "transition",
            tenant_id,
            broadcast_id,
            now,
            new_state.value,
            str(expected_owner_epoch),
            "" if output_epoch is None else str(output_epoch),
            "" if reason is None else reason.value,
            _LEGAL_SOURCES[new_state],
        )
        return self._descriptor(raw)

    # ── Ownership ──────────────────────────────────────────────────────

    async def claim_owner(
        self,
        tenant_id: str,
        broadcast_id: str,
        worker_id: str,
        *,
        now: Optional[float] = None,
    ) -> Tuple[bool, int]:
        stamp = await self._now(now)
        claimed, epoch = await self._run(
            "claim_owner",
            tenant_id,
            broadcast_id,
            stamp,
            worker_id,
            str(OWNER_LEASE_TTL_S),
        )
        return bool(claimed), int(epoch)

    async def renew_owner(
        self,
        tenant_id: str,
        broadcast_id: str,
        worker_id: str,
        owner_epoch: int,
        *,
        now: Optional[float] = None,
    ) -> bool:
        stamp = await self._now(now)
        result = await self._run(
            "renew_owner",
            tenant_id,
            broadcast_id,
            stamp,
            worker_id,
            str(owner_epoch),
            str(OWNER_LEASE_TTL_S),
        )
        return bool(result)

    # ── Admission ──────────────────────────────────────────────────────

    async def reserve_viewer(
        self,
        tenant_id: str,
        broadcast_id: str,
        principal: ParticipantPrincipal,
        livekit_identity: str,
        *,
        now: Optional[float] = None,
    ) -> Admission:
        stamp = await self._now(now)
        lease_raw, is_first = await self._run(
            "reserve_viewer",
            tenant_id,
            broadcast_id,
            stamp,
            principal.model_dump_json(),
            livekit_identity,
            str(VIEWER_CREDENTIAL_TTL_S),
            _iso(stamp + VIEWER_CREDENTIAL_TTL_S),
            f"lease-{uuid.uuid4().hex[:16]}",
        )
        return Admission(lease=self._lease(lease_raw), is_first=bool(is_first))

    async def confirm_viewer(self, tenant_id: str, broadcast_id: str, lease_id: str) -> ViewerLease:
        now = await self._now(None)
        raw = await self._run("confirm_viewer", tenant_id, broadcast_id, now, lease_id)
        return self._lease(raw)

    async def heartbeat_control(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> None:
        stamp = await self._now(now)
        await self._run("heartbeat_control", tenant_id, broadcast_id, stamp, lease_id)

    async def release_viewer(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> ReleaseOutcome:
        stamp = await self._now(now)
        empty, floor_to, new_moderator = await self._run(
            "release_viewer",
            tenant_id,
            broadcast_id,
            stamp,
            lease_id,
            str(VIEWER_CREDENTIAL_TTL_S),
        )
        return ReleaseOutcome(
            audience_empty=bool(empty),
            floor_returned_to=floor_to or None,
            new_moderator=new_moderator or None,
        )

    async def list_leases(self, tenant_id: str, broadcast_id: str) -> List[ViewerLease]:
        now = await self._now(None)
        rows = await self._run("list_leases", tenant_id, broadcast_id, now)
        return [self._lease(row) for row in rows]

    # ── Hands ──────────────────────────────────────────────────────────

    async def raise_hand(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> BroadcastDescriptor:
        stamp = await self._now(now)
        raw = await self._run("raise_hand", tenant_id, broadcast_id, stamp, lease_id)
        return self._descriptor(raw)

    async def cancel_hand(self, tenant_id: str, broadcast_id: str, lease_id: str) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run("cancel_hand", tenant_id, broadcast_id, now, lease_id)
        return self._descriptor(raw)

    async def dismiss_hand(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        target_lease_id: str,
    ) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run(
            "dismiss_hand",
            tenant_id,
            broadcast_id,
            now,
            moderator_lease_id,
            target_lease_id,
        )
        return self._descriptor(raw)

    # ── Floor ──────────────────────────────────────────────────────────

    async def grant_floor(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        target_lease_id: Optional[str],
        expected_version: int,
    ) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run(
            "grant_floor",
            tenant_id,
            broadcast_id,
            now,
            moderator_lease_id,
            target_lease_id or "",
            str(expected_version),
        )
        return self._descriptor(raw)

    async def commit_floor(
        self, tenant_id: str, broadcast_id: str, target_lease_id: str, floor_epoch: int
    ) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run(
            "commit_floor",
            tenant_id,
            broadcast_id,
            now,
            target_lease_id,
            str(floor_epoch),
        )
        return self._descriptor(raw)

    async def abort_floor(self, tenant_id: str, broadcast_id: str, floor_epoch: int) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run("abort_floor", tenant_id, broadcast_id, now, str(floor_epoch))
        return self._descriptor(raw)

    async def release_floor(self, tenant_id: str, broadcast_id: str, speaker_lease_id: str) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run("release_floor", tenant_id, broadcast_id, now, speaker_lease_id)
        return self._descriptor(raw)

    async def revoke_floor(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        expected_version: int,
    ) -> BroadcastDescriptor:
        return await self.grant_floor(tenant_id, broadcast_id, moderator_lease_id, None, expected_version)

    async def elect_moderator(self, tenant_id: str, broadcast_id: str, *, now: Optional[float] = None) -> Optional[str]:
        stamp = await self._now(now)
        elected = await self._run("elect_moderator", tenant_id, broadcast_id, stamp)
        return elected or None

    # ── Speaker socket binding ─────────────────────────────────────────

    async def bind_speaker_socket(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        socket_id: str,
        floor_epoch: int,
    ) -> bool:
        now = await self._now(None)
        result = await self._run(
            "bind_speaker_socket",
            tenant_id,
            broadcast_id,
            now,
            lease_id,
            socket_id,
            str(floor_epoch),
        )
        return bool(result)

    async def unbind_speaker_socket(self, tenant_id: str, broadcast_id: str, lease_id: str, socket_id: str) -> bool:
        now = await self._now(None)
        result = await self._run("unbind_speaker_socket", tenant_id, broadcast_id, now, lease_id, socket_id)
        return bool(result)

    # ── Stop and reconciliation ────────────────────────────────────────

    async def request_stop(self, tenant_id: str, broadcast_id: str, by_lease_id: str) -> BroadcastDescriptor:
        now = await self._now(None)
        raw = await self._run("request_stop", tenant_id, broadcast_id, now, by_lease_id)
        return self._descriptor(raw)

    async def stop_requested(self, tenant_id: str, broadcast_id: str) -> bool:
        now = await self._now(None)
        return bool(await self._run("stop_requested", tenant_id, broadcast_id, now))

    async def expire(self, tenant_id: str, broadcast_id: str, *, now: Optional[float] = None) -> List[ExpiryEvent]:
        stamp = await self._now(now)
        rows = await self._run(
            "expire",
            tenant_id,
            broadcast_id,
            stamp,
            str(PENDING_TTL_S),
            str(TERMINAL_RETENTION_S),
            str(CONTROL_EXPIRY_S),
            broadcast_id,
        )
        events: List[ExpiryEvent] = []
        for row in rows:
            kind, lease_id, detail = row.split("|", 2)
            events.append(ExpiryEvent(kind=ExpiryKind(kind), lease_id=lease_id or None, detail=detail))
        return events


__all__ = ["DEFAULT_KEY_PREFIX", "RedisBroadcastRegistry"]
