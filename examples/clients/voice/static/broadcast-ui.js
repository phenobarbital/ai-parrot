/**
 * Broadcast-mode client for the shared voice demo page (FEAT-537).
 *
 * Kept as a separate ES module — the option `dual_provider.html` already uses
 * for `avatar-viewer.js`, and the one this task's Implementation Notes
 * sanction ("or a new `static/broadcast-ui.js` ES module imported by the
 * page") — so the two pieces that most need testing, the resampler and the
 * floor state machine, are importable without a browser.
 *
 * Two rules drive everything here:
 *
 * 1. **The server owns roles and the floor.** Nothing in this file infers a
 *    role from a URL, a selector or a generic transport frame. `ready_to_speak`
 *    means "the provider finished a turn", not "you may talk" — conflating the
 *    two is exactly how an ungranted viewer's microphone gets enabled, which
 *    spec §2 calls out by name.
 * 2. **A microphone is opened only after a grant AND a user gesture.**
 *    `getUserMedia` is never called speculatively.
 *
 * @module broadcast-ui
 */

/** Floor state values mirrored from the server's `FloorState`. */
export const FloorState = Object.freeze({
  IDLE: "idle",
  SWITCHING: "switching",
  GRANTED: "granted",
});

/** How stale server state may be before Talk is disabled (spec §2: 3 s). */
export const STATE_FRESHNESS_MS = 3000;

/** Control-socket heartbeat period (spec §2: every 5 s, expiry 15 s). */
export const HEARTBEAT_MS = 5000;

/** Server-state polling fallback period. */
export const POLL_MS = 1000;

const TARGET_SAMPLE_RATE = 16000;

/**
 * Create a **stateful** linear resampler.
 *
 * The pre-FEAT-537 page resampled each `onaudioprocess` buffer independently,
 * restarting the read phase at 0 every time. At 48 kHz → 16 kHz that drops a
 * fraction of a sample per buffer and discards the boundary interpolation
 * entirely, producing a periodic click roughly every 85 ms and a slow drift
 * against real time. Carrying the fractional phase and the previous buffer's
 * last sample across calls fixes both.
 *
 * This is a bug fix for single-user mode too, not only for broadcast.
 *
 * @returns {{phase: number, last: number}} Opaque resampler state.
 */
export function createResamplerState() {
  return { phase: 0, last: 0 };
}

/**
 * Resample mono float audio to 16 kHz, continuing from previous calls.
 *
 * @param {{phase: number, last: number}} state Carried across calls; mutated.
 * @param {Float32Array} input Mono samples at `inRate`.
 * @param {number} inRate The AudioContext's **actual** sample rate. Never
 *   assume 16 kHz here: `getUserMedia`'s `sampleRate` is a hint browsers
 *   routinely ignore, and relabelling 48 kHz samples as 16 kHz makes the agent
 *   hear chipmunk speech (spec §2: "never merely relabel 48 kHz samples").
 * @returns {Float32Array} Samples at 16 kHz.
 */
export function resampleTo16k(state, input, inRate) {
  if (!input || input.length === 0) return new Float32Array(0);
  const ratio = inRate / TARGET_SAMPLE_RATE;
  if (Math.abs(ratio - 1) < 0.001) {
    state.last = input[input.length - 1];
    return input;
  }

  const out = [];
  // `phase` is the position of the next output sample within this buffer, in
  // input samples, carried over from the previous call — so a fractional
  // remainder is never rounded away at a buffer boundary.
  let phase = state.phase;
  while (phase < input.length) {
    const index = Math.floor(phase);
    const frac = phase - index;
    // index === -1 reads the previous buffer's final sample, which is what
    // makes the join between buffers continuous rather than a step.
    const a = index < 0 ? state.last : input[index];
    const b = index + 1 < input.length ? input[index + 1] : input[input.length - 1];
    out.push(a + (b - a) * frac);
    phase += ratio;
  }
  state.phase = phase - input.length;
  state.last = input[input.length - 1];
  return Float32Array.from(out);
}

/**
 * Convert float samples to little-endian PCM16.
 *
 * @param {Float32Array} samples
 * @returns {ArrayBuffer}
 */
export function floatToPcm16(samples) {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = Math.max(-32768, Math.min(32767, Math.round(clamped * 32768)));
  }
  return pcm.buffer;
}

/**
 * Derive what this browser may currently do, from server state alone.
 *
 * Deliberately a pure function of (state, lease, freshness): the UI asks it,
 * rather than each call site deciding for itself whether to enable Talk. That
 * is what makes "a generic `ready_to_speak` can never enable an ungranted
 * microphone" a property rather than a convention.
 *
 * @param {?object} state A `BroadcastPublicState`.
 * @param {?string} leaseId This browser's lease.
 * @param {boolean} fresh Whether the state is within the freshness budget.
 * @returns {{isModerator: boolean, isSpeaker: boolean, canTalk: boolean,
 *   floorEpoch: number, handRaised: boolean}}
 */
export function derivePermissions(state, leaseId, fresh) {
  if (!state || !leaseId) {
    return { isModerator: false, isSpeaker: false, canTalk: false, floorEpoch: 0, handRaised: false };
  }
  const isModerator = state.moderator_display_id === leaseId;
  const isSpeaker = state.speaker_display_id === leaseId;
  const granted = state.floor_state === FloorState.GRANTED;
  const live = state.state === "avatar" || state.state === "audio_only";
  return {
    isModerator,
    isSpeaker,
    // Every one of these is required: holding the floor is not enough if the
    // floor is mid-switch, the broadcast is not live, or our view of the
    // server is stale.
    canTalk: Boolean(isSpeaker && granted && live && fresh),
    floorEpoch: Number(state.floor_epoch ?? 0),
    handRaised: (state.hand_requests || []).some((hand) => hand.lease_id === leaseId),
  };
}

/** Thrown for a non-2xx broadcast API response, carrying the server's code. */
export class BroadcastApiError extends Error {
  /**
   * @param {number} status
   * @param {object} body Parsed JSON body, if any.
   */
  constructor(status, body) {
    const code = (body && body.error) || `http_${status}`;
    super(`${status} ${code}`);
    this.name = "BroadcastApiError";
    this.status = status;
    this.code = code;
    this.state = (body && body.state) || null;
    this.retryable = Boolean(body && body.retryable);
  }
}

/**
 * REST + control-socket client for one broadcast participation.
 *
 * Owns no DOM: the page supplies callbacks. That keeps this module testable
 * and keeps the "server decides" rule in one place instead of scattered
 * through render code.
 */
export class BroadcastClient {
  /**
   * @param {object} opts
   * @param {object} opts.config `window.__CONFIG__.broadcast`.
   * @param {() => ?string} opts.getToken Returns the demo bearer token, or
   *   `null`. Held in memory by the page and never persisted.
   * @param {(state: object) => void} [opts.onState] Server state applied.
   * @param {(perms: object) => void} [opts.onPermissions] Role/floor change.
   * @param {(frame: object) => void} [opts.onFrame] Any other control frame.
   * @param {(error: Error) => void} [opts.onError]
   * @param {(stale: boolean) => void} [opts.onStale]
   * @param {typeof fetch} [opts.fetchImpl]
   * @param {typeof WebSocket} [opts.socketImpl]
   * @param {() => number} [opts.now]
   */
  constructor({
    config,
    getToken,
    onState = () => {},
    onPermissions = () => {},
    onFrame = () => {},
    onError = () => {},
    onStale = () => {},
    fetchImpl = null,
    socketImpl = null,
    now = () => Date.now(),
  }) {
    this.config = config || {};
    this._getToken = getToken;
    this._onState = onState;
    this._onPermissions = onPermissions;
    this._onFrame = onFrame;
    this._onError = onError;
    this._onStale = onStale;
    this._fetch = fetchImpl || ((...args) => globalThis.fetch(...args));
    this._Socket = socketImpl || globalThis.WebSocket;
    this._now = now;

    this.broadcastId = null;
    this.leaseId = null;
    this.state = null;
    this.permissions = derivePermissions(null, null, false);
    this.lastStateAt = 0;
    this.stale = false;

    this._ws = null;
    this._heartbeat = null;
    this._poll = null;
  }

  /** @returns {string} The REST prefix for this agent's broadcasts. */
  get apiPrefix() {
    return this.config.apiPrefix;
  }

  /**
   * Share link for the current broadcast.
   *
   * Carries the broadcast id and **nothing else** — no role claim, no token.
   * Anyone following it still has to authenticate and be admitted (spec §2).
   *
   * @param {string} [origin]
   * @returns {?string}
   */
  shareLink(origin = globalThis.location ? globalThis.location.origin : "") {
    if (!this.broadcastId) return null;
    return `${origin}/?broadcast=${encodeURIComponent(this.broadcastId)}`;
  }

  /**
   * Issue one authenticated API call.
   *
   * @param {string} method
   * @param {string} path Appended to {@link apiPrefix}.
   * @param {object} [body]
   * @returns {Promise<object>} Parsed JSON, or `{}` for 204.
   * @throws {BroadcastApiError}
   */
  async request(method, path, body = undefined) {
    const token = this._getToken ? this._getToken() : null;
    const headers = { Accept: "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    const response = await this._fetch(`${this.apiPrefix}${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.status === 204) return {};
    let parsed = null;
    try {
      parsed = await response.json();
    } catch (err) {
      parsed = null;
    }
    if (!response.ok) throw new BroadcastApiError(response.status, parsed);
    return parsed || {};
  }

  /**
   * Create a pending broadcast.
   *
   * @returns {Promise<string>} The new broadcast id.
   */
  async create() {
    const body = await this.request("POST", "", {});
    this.broadcastId = body.broadcast_id;
    this._applyState(body.state);
    return this.broadcastId;
  }

  /**
   * Reserve a seat and obtain this browser's room credentials.
   *
   * The connection call is polled because media may still be initialising —
   * the server answers a retryable 409 rather than inventing credentials.
   *
   * @param {string} broadcastId
   * @param {{attempts?: number, delayMs?: number}} [opts]
   * @returns {Promise<{lease: object, connection: object}>}
   */
  async join(broadcastId, { attempts = 20, delayMs = 500 } = {}) {
    this.broadcastId = broadcastId;
    const admission = await this.request("POST", `/${broadcastId}/viewers`, {});
    this.leaseId = admission.lease_id;
    this._applyState(admission.state);

    let lastError = null;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const connection = await this.request(
          "GET",
          `/${broadcastId}/viewers/${this.leaseId}/connection`,
        );
        this._applyState(connection.public_state);
        return { lease: admission, connection };
      } catch (err) {
        if (!(err instanceof BroadcastApiError) || !err.retryable) throw err;
        lastError = err;
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
    throw lastError || new Error("timed out waiting for media");
  }

  /**
   * Open the participant control socket and attach it to this lease.
   *
   * @returns {Promise<void>}
   */
  async openControlSocket() {
    if (!this.broadcastId || !this.leaseId) throw new Error("join() first");
    const token = this._getToken ? this._getToken() : null;
    const path = this.config.wsPath.replace("{broadcast_id}", this.broadcastId);
    const origin = globalThis.location
      ? globalThis.location.origin.replace(/^http/, "ws")
      : "";
    // Token travels in the WebSocket subprotocol, never the query string, so
    // it stays out of URLs and access logs (spec §2).
    const socket = token
      ? new this._Socket(`${origin}${path}`, ["jwt", token])
      : new this._Socket(`${origin}${path}`);
    this._ws = socket;

    socket.onmessage = (event) => this._handleFrame(event);
    socket.onerror = () => this._onError(new Error("control socket error"));
    socket.onclose = () => this._stopTimers();

    await new Promise((resolve) => {
      if (socket.readyState === 1) return resolve();
      socket.onopen = () => resolve();
      return undefined;
    });

    this.send({ type: "attach", lease_id: this.leaseId });
    this.send({ type: "start_session" });
    this._startTimers();
  }

  /**
   * Send one control frame, if the socket is open.
   *
   * @param {object} frame
   * @returns {boolean} Whether it was sent.
   */
  send(frame) {
    if (!this._ws || this._ws.readyState !== 1) return false;
    this._ws.send(JSON.stringify(frame));
    return true;
  }

  /** Handle one inbound control frame. */
  _handleFrame(event) {
    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    switch (frame.type) {
      case "broadcast_state":
        this._applyState(frame.state);
        break;
      case "floor_state":
        // Authoritative per-socket permission. Note this is the ONLY frame that
        // may enable Talk — `ready_to_speak` never does.
        this._recompute();
        this._onFrame(frame);
        break;
      case "floor_revoked":
        this._onFrame(frame);
        break;
      default:
        this._onFrame(frame);
    }
  }

  /** Adopt a server state and recompute permissions. */
  _applyState(state) {
    if (!state) return;
    if (this.state && Number(state.version ?? 0) < Number(this.state.version ?? 0)) {
      // Out of order, but still proof the server is reachable.
      this.markFresh();
      return;
    }
    this.state = state;
    this.markFresh();
    this._onState(state);
    this._recompute();
  }

  /** Recompute and publish the derived permissions. */
  _recompute() {
    const perms = derivePermissions(this.state, this.leaseId, !this.stale);
    const changed =
      perms.canTalk !== this.permissions.canTalk ||
      perms.isModerator !== this.permissions.isModerator ||
      perms.isSpeaker !== this.permissions.isSpeaker ||
      perms.floorEpoch !== this.permissions.floorEpoch ||
      perms.handRaised !== this.permissions.handRaised;
    this.permissions = perms;
    if (changed) this._onPermissions(perms);
  }

  /** Record that the server was heard from just now. */
  markFresh() {
    this.lastStateAt = this._now();
    if (this.stale) {
      this.stale = false;
      this._onStale(false);
      this._recompute();
    }
  }

  /**
   * Disable Talk when our view of the server has gone stale.
   *
   * @returns {boolean} Whether the client is now stale.
   */
  checkFreshness() {
    if (!this.state) return false;
    const stale = this._now() - this.lastStateAt > STATE_FRESHNESS_MS;
    if (stale !== this.stale) {
      this.stale = stale;
      this._onStale(stale);
      this._recompute();
    }
    return this.stale;
  }

  _startTimers() {
    this._stopTimers();
    this._heartbeat = setInterval(() => this.send({ type: "ping" }), HEARTBEAT_MS);
    this._poll = setInterval(() => {
      this.checkFreshness();
      this.refresh().catch(() => {});
    }, POLL_MS);
  }

  _stopTimers() {
    if (this._heartbeat) clearInterval(this._heartbeat);
    if (this._poll) clearInterval(this._poll);
    this._heartbeat = null;
    this._poll = null;
  }

  /**
   * Poll the current state — the fallback when a notification is missed.
   *
   * Redis remains authoritative; a dropped push must not leave this browser
   * acting on a state the server has moved past (spec §2).
   *
   * @returns {Promise<?object>}
   */
  async refresh() {
    if (!this.broadcastId) return null;
    const body = await this.request("GET", `/${this.broadcastId}`);
    this._applyState(body.state);
    return body.state;
  }

  // ── Participant actions ────────────────────────────────────────────

  /** Raise this participant's hand. Grants no microphone permission. */
  async raiseHand() {
    const body = await this.request("POST", `/${this.broadcastId}/hands`, {
      lease_id: this.leaseId,
    });
    this._applyState(body.state);
  }

  /** Withdraw this participant's own hand request. */
  async cancelHand() {
    const body = await this.request(
      "DELETE",
      `/${this.broadcastId}/hands/me?lease_id=${encodeURIComponent(this.leaseId)}`,
    );
    this._applyState(body.state);
  }

  /** Moderator: dismiss someone else's request without changing permissions. */
  async dismissHand(targetLeaseId) {
    const body = await this.request(
      "DELETE",
      `/${this.broadcastId}/hands/${encodeURIComponent(targetLeaseId)}`,
    );
    this._applyState(body.state);
  }

  /**
   * Moderator: grant, revoke (`null`) or reclaim (own lease) the floor.
   *
   * @param {?string} targetLeaseId
   */
  async setFloor(targetLeaseId) {
    const body = await this.request("POST", `/${this.broadcastId}/floor`, {
      lease_id: targetLeaseId,
      expected_version: Number(this.state ? this.state.version : 0),
    });
    this._applyState(body.state);
  }

  /** Speaker: Finish Speaking — hand the floor back to the moderator. */
  async finishSpeaking() {
    const body = await this.request("POST", `/${this.broadcastId}/floor/release`, {
      lease_id: this.leaseId,
    });
    this._applyState(body.state);
  }

  /** Moderator: stop the broadcast for everyone. */
  async stop() {
    const body = await this.request("POST", `/${this.broadcastId}/stop`, {});
    this._applyState(body.state);
  }

  /** Leave: release this seat and close the control socket. */
  async leave() {
    this._stopTimers();
    try {
      if (this.broadcastId && this.leaseId) {
        await this.request(
          "DELETE",
          `/${this.broadcastId}/viewers/${encodeURIComponent(this.leaseId)}`,
        );
      }
    } finally {
      if (this._ws) {
        try {
          this._ws.close();
        } catch (err) {
          /* already closing */
        }
        this._ws = null;
      }
      this.leaseId = null;
      this.state = null;
      this.permissions = derivePermissions(null, null, false);
    }
  }
}
