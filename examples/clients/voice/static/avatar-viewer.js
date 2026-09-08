// Avatar viewer controller — FEAT-536 TASK-2944 (subscriber lifecycle and
// single-source audio controller for the LiveAvatar viewer added to the
// Voice demo page, examples/clients/voice/static/dual_provider.html).
//
// This module owns ONE subscribe-only LiveKit Room built from the viewer
// credentials the server already returns on `session_started.avatar`
// (`livekit_url`, `client_token`, optionally `room`) — see
// packages/ai-parrot-integrations/src/parrot/voice/handler.py's
// `_handle_start_session` avatar block. It never publishes a microphone or
// camera track: the existing WebSocket PCM16/16k path remains the only
// input. It is deliberately independent of any framework (Svelte, etc.) so
// it can run unmodified inside a plain HTML page loaded as an ES module,
// and is SDK-injectable so tests can supply a fake `{Room, RoomEvent,
// Track}` surface instead of the real `livekit-client` UMD/ESM build.
//
// Reference (lifecycle pattern only — not reused/imported): the admin
// Svelte viewer at packages/ai-parrot-server/ui/src/lib/components/agents/
// avatar/AvatarViewer.svelte registers Room listeners before connecting and
// tears down idempotently; this controller follows the same pattern plus
// the additional single-audible-source policy and generation-token guard
// this feature's spec requires (sdd/specs/voicebot-liveavatar-implementation
// .spec.md, "Avatar viewer in the existing Voice UI").

/** @typedef {"idle"|"connecting"|"live"|"error"} AvatarViewerStatus */
/** @typedef {"browser"|"avatar"} AudioSourceKind */

export const AvatarStatus = Object.freeze({
  IDLE: "idle",
  CONNECTING: "connecting",
  LIVE: "live",
  ERROR: "error",
});

/**
 * Viewer operating mode (FEAT-537).
 *
 * - `"single"` — the pre-FEAT-537 behaviour, unchanged: one user, one avatar
 *   session, a WebSocket PCM fallback when avatar audio is unavailable.
 * - `"broadcast"` — a moderated multi-browser broadcast. Room credentials come
 *   from the scoped admission API, the audible source is chosen by the server's
 *   descriptor (never inferred locally), and the WebSocket PCM fallback is
 *   **disabled**: after a cutover the fallback audio arrives from the shared
 *   room's direct publisher, so playing local PCM as well would give this
 *   browser two audible sources.
 *
 * @typedef {"single"|"broadcast"} ViewerModeKind
 */
export const ViewerMode = Object.freeze({
  SINGLE: "single",
  BROADCAST: "broadcast",
});

/**
 * How stale a broadcast descriptor may be before output is muted.
 *
 * Spec §2: "Polling fallback must disable capture if state freshness exceeds
 * 3 seconds" and "Status older than 3 seconds mutes output until refreshed."
 * A browser that has lost contact with the server must not keep playing audio
 * whose authorisation it can no longer confirm.
 */
export const STATE_FRESHNESS_MS = 3000;

export const AudioSource = Object.freeze({
  BROWSER: "browser",
  AVATAR: "avatar",
});

const noop = () => {};

/**
 * Subscribe-only LiveKit Room lifecycle plus the "at most one audible
 * output source at any instant" policy described by the spec.
 *
 * Usage (from the page, once `session_started.avatar.active` is true):
 *
 *   const controller = new AvatarViewerController({
 *     sdk: window.LivekitClient,            // {Room, RoomEvent, Track}
 *     videoEl: document.getElementById("avatarVideo"),
 *     audioEl: document.getElementById("avatarAudio"),
 *     onStatusChange: (status) => { ... },
 *     onAudioSourceChange: (source) => { ... },
 *     onStopLocalPlayback: () => stopAndClearLocalPcmQueue(),
 *     onAudioPlaybackBlocked: () => showEnableAudioButton(),
 *   });
 *   await controller.join(sessionStartedMsg.avatar);
 *   // ... before playing each locally-queued WebSocket PCM chunk:
 *   if (controller.shouldPlayLocalAudio()) playChunk(chunk);
 *   // ... on provider switch / session end / avatar off / page teardown:
 *   await controller.teardown();
 */
export class AvatarViewerController {
  /**
   * @param {object} opts
   * @param {{Room: Function, RoomEvent: Record<string, string>, Track: {Kind: {Video: string, Audio: string}}}} opts.sdk
   *   Injected LiveKit SDK surface. In the browser this is the
   *   `LivekitClient` UMD global (or an ES-module import of the same
   *   package); tests inject a fake with the same shape — no real Room or
   *   network connection is required.
   * @param {HTMLVideoElement|null} [opts.videoEl] Subscribe-only video
   *   element. The controller always forces `muted = true` on it — actual
   *   audio, if any, only ever plays through `audioEl`.
   * @param {HTMLAudioElement|null} [opts.audioEl] Dedicated remote-audio
   *   element carrying avatar speech, gated by the one-source policy.
   * @param {(status: AvatarViewerStatus) => void} [opts.onStatusChange]
   * @param {(source: AudioSourceKind) => void} [opts.onAudioSourceChange]
   *   Fired whenever the single-audible-source decision changes.
   * @param {() => void} [opts.onStopLocalPlayback] Called exactly once, at
   *   the start of a switch to avatar audio; the caller (the page) must
   *   stop and clear any currently playing/queued local PCM chunks. The
   *   controller does not own that queue.
   * @param {() => void} [opts.onAudioPlaybackBlocked] Fired when the
   *   avatar's audio track exists but the browser's autoplay policy is
   *   blocking playback; the caller should surface an explicit
   *   "Enable avatar audio" affordance that calls {@link enableAudio}.
   * @param {(error: Error) => void} [opts.onError]
   * @param {Console} [opts.logger]
   */
  constructor({
    sdk,
    videoEl = null,
    audioEl = null,
    onStatusChange = noop,
    onAudioSourceChange = noop,
    onStopLocalPlayback = noop,
    onAudioPlaybackBlocked = noop,
    onError = noop,
    logger = console,
    // ── FEAT-537 broadcast mode ──────────────────────────────────────
    mode = ViewerMode.SINGLE,
    onStale = noop,
    onDisconnected = noop,
    stateFreshnessMs = STATE_FRESHNESS_MS,
    now = () => Date.now(),
  } = {}) {
    if (!sdk || !sdk.Room || !sdk.RoomEvent || !sdk.Track) {
      throw new Error(
        "AvatarViewerController requires an injected sdk with {Room, RoomEvent, Track}",
      );
    }
    this._sdk = sdk;
    this._videoEl = videoEl;
    this._audioEl = audioEl;
    this._onStatusChange = onStatusChange;
    this._onAudioSourceChange = onAudioSourceChange;
    this._onStopLocalPlayback = onStopLocalPlayback;
    this._onAudioPlaybackBlocked = onAudioPlaybackBlocked;
    this._onError = onError;
    this._logger = logger;

    // Connection-generation token (spec "Lifecycle/races"): every join()
    // bumps this; any async continuation (connect() resolution, track
    // events) captured against an older generation becomes a no-op instead
    // of attaching media, changing status or unmuting audio.
    this._generation = 0;

    this._room = null;
    this._audioTrack = null;
    this._videoTrack = null;

    this._status = AvatarStatus.IDLE;
    this._audioSource = AudioSource.BROWSER;
    // Default preference: once avatar audio is actually playable, prefer
    // it over the WebSocket fallback (spec: "the user chooses/defaults to
    // avatar audio"). An explicit setPreferredAudioSource("browser") call
    // overrides this.
    this._preferredSource = AudioSource.AVATAR;
    this._userMuted = false;
    this._canPlayAvatarAudio = false;

    // ── FEAT-537 broadcast state ─────────────────────────────────────
    this._mode = mode === ViewerMode.BROADCAST ? ViewerMode.BROADCAST : ViewerMode.SINGLE;
    this._onStale = onStale;
    this._onDisconnected = onDisconnected;
    this._stateFreshnessMs = stateFreshnessMs;
    this._now = now;
    this._broadcast = null;
    this._stale = false;

    if (this._audioEl) this._audioEl.muted = true;
    if (this._videoEl) this._videoEl.muted = true;
  }

  /** @returns {ViewerModeKind} `"single"` or `"broadcast"`. */
  get mode() {
    return this._mode;
  }

  /**
   * @returns {?{state: string, version: number, outputEpoch: number,
   *   avatarIdentity: ?string, directIdentity: ?string, lastStateAt: number}}
   *   The last applied broadcast descriptor, or `null` outside broadcast mode.
   */
  get broadcastState() {
    return this._broadcast;
  }

  /** @returns {boolean} Whether the descriptor is older than the freshness budget. */
  get stale() {
    return this._stale;
  }

  /** @returns {AvatarViewerStatus} */
  get status() {
    return this._status;
  }

  /** @returns {AudioSourceKind} Currently active audible source. */
  get audioSource() {
    return this._audioSource;
  }

  /** @returns {boolean} Whether the avatar's audio track can currently play. */
  get canPlayAvatarAudio() {
    return this._canPlayAvatarAudio;
  }

  /** @returns {boolean} The sticky, explicit user mute choice. */
  get muted() {
    return this._userMuted;
  }

  /**
   * Whether the page's own WebSocket/local PCM fallback should play right
   * now. The page must call this before playing each queued chunk instead
   * of assuming local audio is always active — this is the "at most one
   * audible output source at any instant" gate.
   *
   * @returns {boolean}
   */
  shouldPlayLocalAudio() {
    // Broadcast mode has no WebSocket PCM fallback: the audience's fallback is
    // the shared room's direct publisher, so playing local PCM here would be a
    // second audible source for this browser alone (spec §2).
    if (this._mode === ViewerMode.BROADCAST) return false;
    return !this._userMuted && this._audioSource === AudioSource.BROWSER;
  }

  /**
   * Join one subscribe-only Room from `session_started.avatar` viewer
   * credentials. Registers listeners BEFORE connecting so tracks already
   * present on join are not missed, and never calls any local-publish
   * method (video/camera capture is never requested).
   *
   * Implicitly tears down any previous room first, so callers can call
   * `join()` again directly on a provider/session change without a
   * separate `teardown()` call (teardown remains idempotent and safe to
   * call anyway, e.g. on avatar-off or page unload).
   *
   * @param {{livekit_url: string, client_token: string, room?: string}} credentials
   *   Exactly the wire shape of `session_started.avatar` (server field
   *   names, not a translated/camelCased copy) — see handler.py's avatar
   *   block: `{active, livekit_url, client_token, room, audio}`.
   * @returns {Promise<void>}
   */
  async join(credentials) {
    await this.teardown();

    const generation = ++this._generation;
    const { Room, RoomEvent, Track } = this._sdk;

    this._roomName = credentials && credentials.room ? credentials.room : null;
    this._setStatus(AvatarStatus.CONNECTING, generation);

    const room = new Room();
    this._room = room;

    room.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
      if (generation !== this._generation) return; // stale generation guard
      this._handleTrackSubscribed(track, Track, generation, participant);
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      if (generation !== this._generation) return;
      this._handleTrackUnsubscribed(track, generation);
    });
    room.on(RoomEvent.Disconnected, () => {
      if (generation !== this._generation) return;
      this._handleDisconnected(generation);
    });
    room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
      if (generation !== this._generation) return;
      this._handleAudioPlaybackStatusChanged(generation);
    });

    try {
      await room.connect(
        credentials && credentials.livekit_url,
        credentials && credentials.client_token,
      );
    } catch (err) {
      if (generation !== this._generation) return; // superseded meanwhile
      this._setStatus(AvatarStatus.ERROR, generation);
      this._onError(err);
      return;
    }

    if (generation !== this._generation) {
      // A newer join()/teardown() raced us while connect() was pending —
      // this room is now stale and must not be left alive as a second
      // live room.
      await this._safeDisconnect(room);
      return;
    }

    this._canPlayAvatarAudio = !!room.canPlaybackAudio;
    this._setStatus(AvatarStatus.LIVE, generation);
    if (this._canPlayAvatarAudio) this._maybeSwitchToAvatarAudio(generation);
  }

  /**
   * Call from a user-gesture handler (an "Enable avatar audio" button) to
   * satisfy the browser's autoplay policy via `Room.startAudio()`. A
   * failure here only affects the avatar path — the WebSocket fallback
   * keeps working and no local chunk is skipped because of it.
   *
   * @returns {Promise<void>}
   */
  async enableAudio() {
    const room = this._room;
    if (!room || typeof room.startAudio !== "function") return;
    const generation = this._generation;
    try {
      await room.startAudio();
    } catch (err) {
      if (generation !== this._generation) return;
      this._onError(err);
      return;
    }
    if (generation !== this._generation) return;
    this._canPlayAvatarAudio = !!room.canPlaybackAudio;
    if (this._canPlayAvatarAudio) this._maybeSwitchToAvatarAudio(generation);
  }

  /**
   * Explicit user selection between `"avatar"` and `"browser"` output. If
   * `"avatar"` is requested but its track cannot play yet, the fallback
   * simply continues until a later `AudioPlaybackStatusChanged`/track
   * event makes the switch possible — this never forces an attempt against
   * a blocked or absent track.
   *
   * @param {AudioSourceKind} source
   */
  setPreferredAudioSource(source) {
    if (source !== AudioSource.AVATAR && source !== AudioSource.BROWSER) {
      throw new Error(`Unknown audio source: ${source}`);
    }
    this._preferredSource = source;
    const generation = this._generation;
    if (source === AudioSource.AVATAR) {
      this._maybeSwitchToAvatarAudio(generation);
      return;
    }
    if (this._audioSource === AudioSource.AVATAR) {
      if (this._audioEl) this._audioEl.muted = true;
      this._setAudioSource(AudioSource.BROWSER, generation);
    }
  }

  /**
   * Sticky, explicit global mute. Applies regardless of the active source
   * and — per spec — is never silently undone by an automatic fallback
   * transition; only another explicit `setMuted(false)` call clears it.
   *
   * @param {boolean} muted
   */
  setMuted(muted) {
    this._userMuted = !!muted;
    if (this._audioEl) {
      this._audioEl.muted = this._userMuted || this._audioSource !== AudioSource.AVATAR;
    }
    if (!this._userMuted) {
      this._maybeSwitchToAvatarAudio(this._generation);
    }
  }

  /**
   * Disconnect the room (if any), remove its listeners, detach media and
   * invalidate the current generation so any in-flight promise or track
   * event from before this call becomes a safe no-op. Idempotent and safe
   * to call with no active room.
   *
   * @returns {Promise<void>}
   */
  async teardown() {
    this._generation += 1; // invalidate anything already in-flight

    const room = this._room;
    this._room = null;

    if (this._audioTrack) {
      try {
        this._audioTrack.detach();
      } catch (err) {
        this._logger.warn?.("AvatarViewerController: audio track detach failed", err);
      }
      this._audioTrack = null;
    }
    if (this._videoTrack) {
      try {
        this._videoTrack.detach();
      } catch (err) {
        this._logger.warn?.("AvatarViewerController: video track detach failed", err);
      }
      this._videoTrack = null;
    }

    if (this._videoEl) {
      try {
        this._videoEl.srcObject = null;
      } catch {
        // Some test doubles/older browsers may not support srcObject.
      }
      this._videoEl.muted = true;
    }
    if (this._audioEl) {
      try {
        this._audioEl.srcObject = null;
      } catch {
        // noop
      }
      this._audioEl.muted = true;
    }

    const wasAvatar = this._audioSource === AudioSource.AVATAR;
    this._audioSource = AudioSource.BROWSER;
    this._canPlayAvatarAudio = false;
    this._roomName = null;
    if (wasAvatar) this._onAudioSourceChange(AudioSource.BROWSER);

    if (this._status !== AvatarStatus.IDLE) {
      this._status = AvatarStatus.IDLE;
      this._onStatusChange(AvatarStatus.IDLE);
    }

    await this._safeDisconnect(room);
  }

  // ── FEAT-537: broadcast mode ───────────────────────────────────────

  /**
   * Join a broadcast's LiveKit room with per-lease admission credentials.
   *
   * Same connect path as {@link join}; the difference is what happens next —
   * source selection is driven by the server's descriptor rather than by
   * whichever track happens to arrive.
   *
   * @param {{livekit_url: string, client_token: string, room?: string}} credentials
   *   Exactly the `ViewerJoinResponse` wire shape from
   *   `GET .../viewers/{lease}/connection`.
   * @param {object} [publicState] The `BroadcastPublicState` to apply on join.
   * @returns {Promise<void>}
   */
  async joinBroadcast(credentials, publicState = null) {
    this._mode = ViewerMode.BROADCAST;
    this._broadcast = null;
    this._stale = false;
    if (publicState) this._adoptState(publicState);
    await this.join(credentials);
    if (publicState) this.applyBroadcastState(publicState);
    this._attachExistingTracks();
  }

  /**
   * Apply a server descriptor: select the audible source, or ignore it.
   *
   * Rejects any state that is not monotonically newer (`version` and
   * `output_epoch`), so a late or reordered poll cannot resurrect the avatar
   * after a cutover. `audio_only` is sticky by construction: the server never
   * emits a *newer* `avatar` state after it, and an older one is rejected here.
   *
   * @param {object} publicState A `BroadcastPublicState`.
   * @returns {boolean} Whether the state was applied.
   */
  applyBroadcastState(publicState) {
    if (this._mode !== ViewerMode.BROADCAST || !publicState) return false;

    const version = Number(publicState.version ?? 0);
    const outputEpoch = Number(publicState.output_epoch ?? 0);
    const current = this._broadcast;
    if (current && (version < current.version || outputEpoch < current.outputEpoch)) {
      this._logger.debug?.(
        "AvatarViewerController: ignoring stale broadcast state",
        { version, outputEpoch },
      );
      return false;
    }

    this._adoptState(publicState);
    this.markStateFresh();

    const selected = this._selectedIdentity();
    if (publicState.state === "audio_only") {
      // Detach avatar media BEFORE selecting direct audio, so the two are
      // never audible together during the transition (spec §2).
      this._detachAvatarMedia();
    }
    this._retainOnlySelected(selected);
    this._attachExistingTracks();
    return true;
  }

  /**
   * Record that a fresh descriptor arrived (poll or push).
   *
   * Call on **every** state observation, including ones
   * {@link applyBroadcastState} rejects as stale — an out-of-order poll still
   * proves the server is reachable.
   */
  markStateFresh() {
    if (this._broadcast) this._broadcast.lastStateAt = this._now();
    if (this._stale) {
      this._stale = false;
      if (this._audioEl && !this._userMuted) this._audioEl.muted = false;
      this._onStale(false);
    }
  }

  /**
   * Mute output when the descriptor has gone stale.
   *
   * The page drives this from its poll timer. A browser that cannot confirm
   * the current state must not keep playing audio it can no longer show is
   * authorised (spec §2: "Status older than 3 seconds mutes output").
   *
   * @returns {boolean} Whether the viewer is now stale.
   */
  checkStateFreshness() {
    if (this._mode !== ViewerMode.BROADCAST || !this._broadcast) return false;
    const age = this._now() - this._broadcast.lastStateAt;
    const stale = age > this._stateFreshnessMs;
    if (stale && !this._stale) {
      this._stale = true;
      if (this._audioEl) this._audioEl.muted = true;
      if (this._videoEl) this._videoEl.muted = true;
      this._onStale(true);
    }
    return this._stale;
  }

  /** Store the descriptor fields this controller acts on. */
  _adoptState(publicState) {
    this._broadcast = {
      state: publicState.state,
      version: Number(publicState.version ?? 0),
      outputEpoch: Number(publicState.output_epoch ?? 0),
      avatarIdentity: publicState.avatar_identity ?? null,
      directIdentity: publicState.direct_identity ?? null,
      selectedIdentity: publicState.selected_identity ?? null,
      lastStateAt: this._now(),
    };
  }

  /**
   * The publisher identity the server says is authoritative right now.
   *
   * Prefers the server's own `selected_identity`; falls back to deriving it
   * from the state so an older server that omits the field still works.
   *
   * @returns {?string}
   */
  _selectedIdentity() {
    const state = this._broadcast;
    if (!state) return null;
    if (state.selectedIdentity) return state.selectedIdentity;
    if (state.state === "audio_only") return state.directIdentity;
    if (state.state === "avatar") return state.avatarIdentity;
    return null;
  }

  /** Whether a participant is the currently selected publisher. */
  _identityIsSelected(participant) {
    const selected = this._selectedIdentity();
    // Before any descriptor arrives, accept nothing: a broadcast viewer must
    // not attach media it has not been told to play.
    if (!selected) return false;
    return !!participant && participant.identity === selected;
  }

  /** Mute and detach avatar video and audio ahead of a cutover. */
  _detachAvatarMedia() {
    if (this._videoEl) this._videoEl.muted = true;
    if (this._audioEl) this._audioEl.muted = true;
    for (const track of [this._videoTrack, this._audioTrack]) {
      if (!track) continue;
      try {
        track.detach();
      } catch (err) {
        this._logger.warn?.("AvatarViewerController: detach failed", err);
      }
    }
    this._videoTrack = null;
    this._audioTrack = null;
    this._canPlayAvatarAudio = false;
    this._setAudioSource(AudioSource.BROWSER, this._generation);
  }

  /** Drop any attached track that no longer belongs to the selected publisher. */
  _retainOnlySelected(selected) {
    if (!selected) return;
    for (const key of ["_videoTrack", "_audioTrack"]) {
      const track = this[key];
      if (!track) continue;
      const identity = track.__parrotIdentity;
      if (identity && identity !== selected) {
        try {
          track.detach();
        } catch (err) {
          this._logger.warn?.("AvatarViewerController: detach failed", err);
        }
        this[key] = null;
      }
    }
  }

  /**
   * Attach tracks that were already published when we joined.
   *
   * A late joiner receives no `TrackSubscribed` event for media that was
   * already flowing, so without this the tenth viewer would see a black frame
   * (spec §2: "Late joins use current state and handle already published
   * tracks").
   */
  _attachExistingTracks() {
    const room = this._room;
    if (!room || !room.remoteParticipants) return;
    const { Track } = this._sdk;
    const generation = this._generation;
    const participants =
      typeof room.remoteParticipants.values === "function"
        ? Array.from(room.remoteParticipants.values())
        : Object.values(room.remoteParticipants);

    for (const participant of participants) {
      if (!this._identityIsSelected(participant)) continue;
      const publications =
        participant.trackPublications &&
        typeof participant.trackPublications.values === "function"
          ? Array.from(participant.trackPublications.values())
          : Object.values(participant.trackPublications || {});
      for (const publication of publications) {
        const track = publication && publication.track;
        if (!track) continue;
        if (track === this._audioTrack || track === this._videoTrack) continue;
        this._handleTrackSubscribed(track, Track, generation, participant);
      }
    }
  }

  // ── Internal event handlers ────────────────────────────────────────

  _handleTrackSubscribed(track, Track, generation, participant = null) {
    // In broadcast mode the server's descriptor — not arrival order — decides
    // which publisher is audible. A late avatar track after a cutover, or any
    // track from an unexpected identity, is ignored rather than attached.
    if (this._mode === ViewerMode.BROADCAST && !this._identityIsSelected(participant)) {
      this._logger.debug?.(
        "AvatarViewerController: ignoring track from unselected identity",
        participant && participant.identity,
      );
      return;
    }
    if (participant && participant.identity) {
      // Remember which publisher a track came from: after a cutover we must be
      // able to tell an avatar track from the direct publisher's.
      track.__parrotIdentity = participant.identity;
    }
    if (track.kind === Track.Kind.Video) {
      this._videoTrack = track;
      if (this._videoEl) {
        track.attach(this._videoEl);
        this._videoEl.muted = true;
      }
      return;
    }
    if (track.kind === Track.Kind.Audio) {
      this._audioTrack = track;
      if (this._audioEl) {
        track.attach(this._audioEl);
        // Starts muted regardless of transport state — only the one-source
        // switch below (or a later explicit selection) ever unmutes it.
        this._audioEl.muted = true;
      }
      this._maybeSwitchToAvatarAudio(generation);
    }
  }

  _handleTrackUnsubscribed(track, generation) {
    try {
      track.detach();
    } catch (err) {
      this._logger.warn?.("AvatarViewerController: track detach failed", err);
    }
    if (track === this._videoTrack) {
      this._videoTrack = null;
      return;
    }
    if (track === this._audioTrack) {
      this._audioTrack = null;
      if (this._audioSource === AudioSource.AVATAR) {
        // Avatar audio is gone — resume FUTURE local chunks only; the page
        // owns not replaying any backlog that would duplicate speech.
        if (this._audioEl) this._audioEl.muted = true;
        this._setAudioSource(AudioSource.BROWSER, generation);
      }
    }
  }

  _handleDisconnected(generation) {
    this._canPlayAvatarAudio = false;
    if (this._audioSource === AudioSource.AVATAR) {
      if (this._audioEl) this._audioEl.muted = true;
      this._setAudioSource(AudioSource.BROWSER, generation);
    }
    this._setStatus(AvatarStatus.IDLE, generation);
    // Broadcast mode does NOT restart a session here. Re-entry means asking
    // the admission API for a fresh lease; reconnecting on our own would try
    // to start a producer and could over-admit the room (spec §2).
    if (this._mode === ViewerMode.BROADCAST) this._onDisconnected();
  }

  _handleAudioPlaybackStatusChanged(generation) {
    const room = this._room;
    if (!room) return;
    this._canPlayAvatarAudio = !!room.canPlaybackAudio;
    if (this._canPlayAvatarAudio) {
      this._maybeSwitchToAvatarAudio(generation);
    } else {
      this._onAudioPlaybackBlocked();
    }
  }

  _maybeSwitchToAvatarAudio(generation) {
    if (this._userMuted) return;
    if (this._preferredSource !== AudioSource.AVATAR) return;
    if (this._audioSource === AudioSource.AVATAR) return;
    if (!this._audioTrack || !this._canPlayAvatarAudio) return;
    this._switchToAvatarAudio(generation);
  }

  _switchToAvatarAudio(generation) {
    // 1. Mute the remote element for the duration of the transition.
    if (this._audioEl) this._audioEl.muted = true;
    // 2. The caller must clear/stop any currently playing or queued local
    //    PCM chunk — the controller does not own that queue.
    this._onStopLocalPlayback();
    // 3. Flip the source flag; shouldPlayLocalAudio() now suppresses any
    //    new local playback from this point on, even before unmuting.
    this._setAudioSource(AudioSource.AVATAR, generation);
    if (generation !== this._generation) return; // superseded mid-callback
    // 4. Unmute the avatar element, unless an explicit mute landed meanwhile.
    if (this._audioEl && !this._userMuted) this._audioEl.muted = false;
  }

  _setStatus(status, generation) {
    if (generation !== this._generation) return;
    if (this._status === status) return;
    this._status = status;
    this._onStatusChange(status);
  }

  _setAudioSource(source, generation) {
    if (generation !== this._generation) return;
    if (this._audioSource === source) return;
    this._audioSource = source;
    this._onAudioSourceChange(source);
  }

  async _safeDisconnect(room) {
    if (!room) return;
    try {
      if (typeof room.removeAllListeners === "function") {
        room.removeAllListeners();
      }
    } catch (err) {
      this._logger.warn?.("AvatarViewerController: removeAllListeners failed", err);
    }
    try {
      await room.disconnect();
    } catch (err) {
      this._logger.warn?.("AvatarViewerController: room.disconnect() failed", err);
    }
  }
}
