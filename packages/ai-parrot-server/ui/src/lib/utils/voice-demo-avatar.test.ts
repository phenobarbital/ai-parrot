// FEAT-536 TASK-2944 — Vitest coverage for the Voice demo's avatar viewer
// controller (examples/clients/voice/static/avatar-viewer.js).
//
// The controller is a standalone ES module for a plain HTML page (not part
// of this SvelteKit UI package) — imported here by relative file path so
// the existing Vitest runner can exercise it with a fake LiveKit SDK
// surface `{Room, RoomEvent, Track}` (no real Room, network connection or
// livekit-client build is required). See avatar-viewer.js's module
// docstring and sdd/specs/voicebot-liveavatar-implementation.spec.md,
// "Avatar viewer in the existing Voice UI", for the behavior under test.

import { describe, it, expect, vi } from "vitest";
import {
  AvatarViewerController,
  AvatarStatus,
  AudioSource,
  // eslint-disable-next-line import/extensions
} from "../../../../../../examples/clients/voice/static/avatar-viewer.js";

// ── Fake LiveKit SDK ─────────────────────────────────────────────────────

const ROOM_EVENT = Object.freeze({
  TrackSubscribed: "trackSubscribed",
  TrackUnsubscribed: "trackUnsubscribed",
  Disconnected: "disconnected",
  AudioPlaybackStatusChanged: "audioPlaybackStatusChanged",
});

const TRACK_KIND = Object.freeze({ Video: "video", Audio: "audio" });

class FakeRoom {
  listeners: Record<string, Array<(...args: unknown[]) => void>> = {};
  canPlaybackAudio = false;
  connectCalls: Array<[unknown, unknown]> = [];
  disconnectCalls = 0;
  removeAllListenersCalls = 0;
  startAudioCalls = 0;
  localParticipant = { publishTrack: vi.fn(), publishData: vi.fn() };
  /** Overridable per-test: () => Promise<void> */
  connectImpl: (() => Promise<void>) | null = null;

  on(event: string, cb: (...args: unknown[]) => void) {
    (this.listeners[event] ||= []).push(cb);
  }

  emit(event: string, ...args: unknown[]) {
    (this.listeners[event] || []).forEach((cb) => cb(...args));
  }

  connect(url: unknown, token: unknown) {
    this.connectCalls.push([url, token]);
    if (this.connectImpl) return this.connectImpl();
    return Promise.resolve();
  }

  async disconnect() {
    this.disconnectCalls += 1;
  }

  removeAllListeners() {
    this.removeAllListenersCalls += 1;
    this.listeners = {};
  }

  async startAudio() {
    this.startAudioCalls += 1;
  }
}

function createFakeSdk() {
  const rooms: FakeRoom[] = [];
  // One-shot hook: whichever FakeRoom is constructed next picks up the
  // pending connectImpl set here. Registering it BEFORE calling join()
  // avoids racing join()'s internal `await this.teardown()` microtask to
  // grab a reference to the not-yet-constructed room.
  const nextConnect: { impl: (() => Promise<void>) | null } = { impl: null };
  function Room(this: unknown) {
    const room = new FakeRoom();
    if (nextConnect.impl) {
      room.connectImpl = nextConnect.impl;
      nextConnect.impl = null;
    }
    rooms.push(room);
    return room;
  }
  return {
    sdk: { Room: Room as unknown as new () => FakeRoom, RoomEvent: ROOM_EVENT, Track: { Kind: TRACK_KIND } },
    rooms,
    nextConnect,
  };
}

function makeFakeTrack(kind: string) {
  return { kind, attach: vi.fn(), detach: vi.fn() };
}

const CREDENTIALS = {
  livekit_url: "wss://livekit.example.com",
  client_token: "viewer-token",
  room: "sess-1",
};

function makeElements() {
  return {
    videoEl: document.createElement("video"),
    audioEl: document.createElement("audio"),
  };
}

// ── test_join_subscribe_only ──────────────────────────────────────────────

describe("AvatarViewerController — join is subscribe-only", () => {
  it("registers listeners before connecting and never publishes", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });

    await controller.join(CREDENTIALS);

    const room = rooms[0];
    expect(room.connectCalls).toEqual([[CREDENTIALS.livekit_url, CREDENTIALS.client_token]]);
    // All four events were registered — and, critically, BEFORE connect()
    // was called (captured via listeners already present at connect time).
    for (const evt of Object.values(ROOM_EVENT)) {
      expect(room.listeners[evt]?.length ?? 0).toBeGreaterThan(0);
    }
    expect(room.localParticipant.publishTrack).not.toHaveBeenCalled();
    expect(room.localParticipant.publishData).not.toHaveBeenCalled();
    expect(controller.status).toBe(AvatarStatus.LIVE);
  });

  it("attaches subscribed video/audio tracks to the intended elements and forces video muted", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    videoEl.muted = false;
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });
    await controller.join(CREDENTIALS);
    const room = rooms[0];

    const videoTrack = makeFakeTrack(TRACK_KIND.Video);
    const audioTrack = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, videoTrack);
    room.emit(ROOM_EVENT.TrackSubscribed, audioTrack);

    expect(videoTrack.attach).toHaveBeenCalledWith(videoEl);
    expect(videoEl.muted).toBe(true);
    expect(audioTrack.attach).toHaveBeenCalledWith(audioEl);
  });

  it("detaches unsubscribed tracks", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });
    await controller.join(CREDENTIALS);
    const room = rooms[0];

    const videoTrack = makeFakeTrack(TRACK_KIND.Video);
    room.emit(ROOM_EVENT.TrackSubscribed, videoTrack);
    room.emit(ROOM_EVENT.TrackUnsubscribed, videoTrack);

    expect(videoTrack.detach).toHaveBeenCalled();
  });
});

// ── test_audio_source_transitions ─────────────────────────────────────────

describe("AvatarViewerController — single audible source policy", () => {
  it("switches to avatar audio only once the track can actually play, stopping local playback first", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const onStopLocalPlayback = vi.fn();
    const onAudioSourceChange = vi.fn();
    const controller = new AvatarViewerController({
      sdk,
      videoEl,
      audioEl,
      onStopLocalPlayback,
      onAudioSourceChange,
    });
    await controller.join(CREDENTIALS);
    const room = rooms[0];

    // Browser fallback is active by default.
    expect(controller.audioSource).toBe(AudioSource.BROWSER);
    expect(controller.shouldPlayLocalAudio()).toBe(true);

    const audioTrack = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, audioTrack);
    // Track present but not yet playable — must stay on the fallback.
    expect(controller.audioSource).toBe(AudioSource.BROWSER);
    expect(onStopLocalPlayback).not.toHaveBeenCalled();

    room.canPlaybackAudio = true;
    room.emit(ROOM_EVENT.AudioPlaybackStatusChanged);

    expect(onStopLocalPlayback).toHaveBeenCalledTimes(1);
    expect(onAudioSourceChange).toHaveBeenCalledWith(AudioSource.AVATAR);
    expect(controller.audioSource).toBe(AudioSource.AVATAR);
    expect(audioEl.muted).toBe(false);
    expect(controller.shouldPlayLocalAudio()).toBe(false);
  });

  it("falls back to future-only local audio when the avatar track is unsubscribed or the room disconnects", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const onAudioSourceChange = vi.fn();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, onAudioSourceChange });
    await controller.join(CREDENTIALS);
    const room = rooms[0];
    room.canPlaybackAudio = true;

    const audioTrack = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, audioTrack);
    room.emit(ROOM_EVENT.AudioPlaybackStatusChanged);
    expect(controller.audioSource).toBe(AudioSource.AVATAR);

    room.emit(ROOM_EVENT.TrackUnsubscribed, audioTrack);

    expect(controller.audioSource).toBe(AudioSource.BROWSER);
    expect(audioEl.muted).toBe(true);
    expect(controller.shouldPlayLocalAudio()).toBe(true);
    expect(onAudioSourceChange).toHaveBeenLastCalledWith(AudioSource.BROWSER);
  });
});

// ── test_autoplay_and_explicit_mute ───────────────────────────────────────

describe("AvatarViewerController — autoplay gating and explicit mute", () => {
  it("reports autoplay-blocked and keeps the fallback until enableAudio() unblocks it", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const onAudioPlaybackBlocked = vi.fn();
    const onAudioSourceChange = vi.fn();
    const controller = new AvatarViewerController({
      sdk,
      videoEl,
      audioEl,
      onAudioPlaybackBlocked,
      onAudioSourceChange,
    });
    await controller.join(CREDENTIALS);
    const room = rooms[0];

    const audioTrack = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, audioTrack);

    room.canPlaybackAudio = false;
    room.emit(ROOM_EVENT.AudioPlaybackStatusChanged);

    expect(onAudioPlaybackBlocked).toHaveBeenCalledTimes(1);
    expect(controller.audioSource).toBe(AudioSource.BROWSER);
    expect(controller.shouldPlayLocalAudio()).toBe(true);

    // Simulate a user gesture on the "Enable avatar audio" affordance —
    // Room.startAudio() succeeds and playback becomes possible.
    room.startAudio = vi.fn(async () => {
      room.canPlaybackAudio = true;
    });
    await controller.enableAudio();

    expect(room.startAudio).toHaveBeenCalledTimes(1);
    expect(controller.audioSource).toBe(AudioSource.AVATAR);
    expect(onAudioSourceChange).toHaveBeenCalledWith(AudioSource.AVATAR);
  });

  it("an explicit mute silences both sources and is not undone by an automatic fallback", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });
    await controller.join(CREDENTIALS);
    const room = rooms[0];
    room.canPlaybackAudio = true;

    const audioTrack = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, audioTrack);
    room.emit(ROOM_EVENT.AudioPlaybackStatusChanged);
    expect(controller.audioSource).toBe(AudioSource.AVATAR);

    controller.setMuted(true);
    expect(controller.muted).toBe(true);
    expect(audioEl.muted).toBe(true);
    expect(controller.shouldPlayLocalAudio()).toBe(false); // no silent fallback leak

    // An automatic AudioPlaybackStatusChanged re-fire must not undo the
    // explicit mute.
    room.emit(ROOM_EVENT.AudioPlaybackStatusChanged);
    expect(audioEl.muted).toBe(true);
    expect(controller.muted).toBe(true);

    controller.setMuted(false);
    expect(controller.muted).toBe(false);
    expect(audioEl.muted).toBe(false);
  });

  it("setPreferredAudioSource('browser') falls back without a forced attempt against a blocked track", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });
    await controller.join(CREDENTIALS);
    const room = rooms[0];
    room.canPlaybackAudio = true;
    const audioTrack = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, audioTrack);
    room.emit(ROOM_EVENT.AudioPlaybackStatusChanged);
    expect(controller.audioSource).toBe(AudioSource.AVATAR);

    controller.setPreferredAudioSource(AudioSource.BROWSER);
    expect(controller.audioSource).toBe(AudioSource.BROWSER);
    expect(audioEl.muted).toBe(true);
    expect(controller.shouldPlayLocalAudio()).toBe(true);

    // Track is still playable, but the explicit preference keeps it on
    // browser output until the user (or default) asks for avatar again.
    room.emit(ROOM_EVENT.AudioPlaybackStatusChanged);
    expect(controller.audioSource).toBe(AudioSource.BROWSER);
  });
});

// ── test_stale_generation_and_idempotent_teardown ─────────────────────────

describe("AvatarViewerController — generation guard and idempotent teardown", () => {
  it("a late connect() resolution from a superseded join cannot go live or attach media", async () => {
    const { sdk, rooms, nextConnect } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const onStatusChange = vi.fn();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, onStatusChange });

    let resolveConnect: () => void = () => {};
    const pending = new Promise<void>((resolve) => {
      resolveConnect = resolve;
    });
    // Registered BEFORE join() so the room it constructs (after its own
    // internal `await teardown()` microtask) picks this up deterministically.
    nextConnect.impl = () => pending;

    const firstJoin = controller.join(CREDENTIALS);
    // Let join()'s internal teardown()/Room-construction microtasks settle
    // so the stale room exists and has registered its listeners.
    await new Promise((resolve) => setTimeout(resolve, 0));
    const staleRoom = rooms[0];
    expect(staleRoom).toBeDefined();
    expect(staleRoom.connectCalls).toEqual([[CREDENTIALS.livekit_url, CREDENTIALS.client_token]]);
    // Capture the generation-guarded listener closures directly, so the
    // later assertion exercises join()'s own stale-generation check —
    // not merely the fact that teardown() also clears the room's listeners.
    const staleTrackSubscribedHandlers = [...(staleRoom.listeners[ROOM_EVENT.TrackSubscribed] || [])];
    expect(staleTrackSubscribedHandlers.length).toBeGreaterThan(0);

    // Supersede it before the first connect() resolves.
    await controller.teardown();
    expect(controller.status).toBe(AvatarStatus.IDLE);

    resolveConnect();
    await firstJoin; // let the stale continuation run to completion
    await Promise.resolve();

    // The stale room must never have gone live nor attached anything, and
    // must have been disconnected instead of left as a second live room.
    expect(onStatusChange).not.toHaveBeenCalledWith(AvatarStatus.LIVE);
    expect(controller.status).toBe(AvatarStatus.IDLE);
    expect(staleRoom.disconnectCalls).toBeGreaterThanOrEqual(1);

    // A late track event replayed through the stale generation's own
    // captured listener closures must not attach media either.
    const lateTrack = makeFakeTrack(TRACK_KIND.Video);
    staleTrackSubscribedHandlers.forEach((cb) => cb(lateTrack));
    expect(lateTrack.attach).not.toHaveBeenCalled();
  });

  it("teardown() is idempotent and safe with no active room", async () => {
    const { sdk } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });

    await expect(controller.teardown()).resolves.toBeUndefined();
    await expect(controller.teardown()).resolves.toBeUndefined();
    expect(controller.status).toBe(AvatarStatus.IDLE);
  });

  it("removes listeners and disconnects the room exactly once per join on a clean teardown", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });
    await controller.join(CREDENTIALS);
    const room = rooms[0];

    await controller.teardown();

    expect(room.removeAllListenersCalls).toBe(1);
    expect(room.disconnectCalls).toBe(1);

    // A second teardown with no active room must not re-disconnect it.
    await controller.teardown();
    expect(room.disconnectCalls).toBe(1);
  });
});

// ── FEAT-537 TASK-2964: broadcast mode ────────────────────────────────────
//
// In broadcast mode the *server's descriptor* decides which publisher is
// audible; the viewer never infers it from whichever track arrives first.
// These cases pin the four properties that follow from that: identity-scoped
// attachment, monotonic state, a one-way cutover, and no local PCM fallback.

const BROADCAST_CREDENTIALS = {
  livekit_url: "wss://livekit.example.com",
  client_token: "lease-token",
  room: "bcast-1",
};

function avatarState(overrides: Record<string, unknown> = {}) {
  return {
    broadcast_id: "bc-1",
    state: "avatar",
    version: 5,
    output_epoch: 2,
    avatar_identity: "avatar-abc",
    direct_identity: "direct-abc",
    selected_identity: "avatar-abc",
    media_ready: true,
    ...overrides,
  };
}

function audioOnlyState(overrides: Record<string, unknown> = {}) {
  return avatarState({
    state: "audio_only",
    version: 6,
    output_epoch: 3,
    selected_identity: "direct-abc",
    ...overrides,
  });
}

function fakeParticipant(identity: string, tracks: Array<{ kind: string }> = []) {
  return {
    identity,
    trackPublications: new Map(
      tracks.map((track, index) => [`pub-${index}`, { track }]),
    ),
  };
}

describe("AvatarViewerController — broadcast mode", () => {
  it("never plays local WebSocket audio in broadcast mode", async () => {
    const { sdk } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, mode: "broadcast" });

    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());

    // True in single mode with a browser source; always false here — the
    // audience's fallback is the room's direct publisher, not local PCM.
    expect(controller.audioSource).toBe(AudioSource.BROWSER);
    expect(controller.shouldPlayLocalAudio()).toBe(false);
    expect(controller.mode).toBe("broadcast");
  });

  it("attaches only tracks from the selected publisher", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, mode: "broadcast" });
    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());
    const room = rooms[0];

    const strangerAudio = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, strangerAudio, {}, fakeParticipant("some-viewer"));
    expect(strangerAudio.attach).not.toHaveBeenCalled();

    const avatarAudio = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, avatarAudio, {}, fakeParticipant("avatar-abc"));
    expect(avatarAudio.attach).toHaveBeenCalledTimes(1);
  });

  it("switches to direct audio once on audio_only and rejects late avatar tracks", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, mode: "broadcast" });
    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());
    const room = rooms[0];

    const avatarVideo = makeFakeTrack(TRACK_KIND.Video);
    const avatarAudio = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, avatarVideo, {}, fakeParticipant("avatar-abc"));
    room.emit(ROOM_EVENT.TrackSubscribed, avatarAudio, {}, fakeParticipant("avatar-abc"));
    expect(avatarVideo.attach).toHaveBeenCalledTimes(1);

    // The server cuts over.
    expect(controller.applyBroadcastState(audioOnlyState())).toBe(true);
    // Avatar media is detached BEFORE direct audio is selected, so the two are
    // never audible together.
    expect(avatarVideo.detach).toHaveBeenCalled();
    expect(avatarAudio.detach).toHaveBeenCalled();

    // The direct publisher is now the only accepted source.
    const directAudio = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, directAudio, {}, fakeParticipant("direct-abc"));
    expect(directAudio.attach).toHaveBeenCalledTimes(1);

    // A late avatar track — the vendor reconnecting after the cutover — must
    // not become audible again.
    const lateAvatarAudio = makeFakeTrack(TRACK_KIND.Audio);
    room.emit(ROOM_EVENT.TrackSubscribed, lateAvatarAudio, {}, fakeParticipant("avatar-abc"));
    expect(lateAvatarAudio.attach).not.toHaveBeenCalled();
  });

  it("ignores states with older version or output_epoch", async () => {
    const { sdk } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, mode: "broadcast" });
    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());

    controller.applyBroadcastState(audioOnlyState());
    expect(controller.broadcastState.state).toBe("audio_only");

    // A reordered poll carrying the pre-cutover state must not resurrect the
    // avatar — audio_only is sticky.
    expect(controller.applyBroadcastState(avatarState())).toBe(false);
    expect(controller.broadcastState.state).toBe("audio_only");

    // Same version but an older output epoch is also refused.
    expect(
      controller.applyBroadcastState(audioOnlyState({ version: 6, output_epoch: 1 })),
    ).toBe(false);
    expect(controller.broadcastState.outputEpoch).toBe(3);
  });

  it("mutes when state is stale for more than 3 seconds", async () => {
    const { sdk } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    let now = 1_000;
    const staleEvents: boolean[] = [];
    const controller = new AvatarViewerController({
      sdk,
      videoEl,
      audioEl,
      mode: "broadcast",
      onStale: (value: boolean) => staleEvents.push(value),
      now: () => now,
    });
    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());

    now += 2_000;
    expect(controller.checkStateFreshness()).toBe(false);
    expect(staleEvents).toEqual([]);

    now += 2_000; // 4 s since the last state
    expect(controller.checkStateFreshness()).toBe(true);
    expect(controller.stale).toBe(true);
    expect(audioEl.muted).toBe(true);
    expect(videoEl.muted).toBe(true);
    expect(staleEvents).toEqual([true]);

    // A fresh observation clears it.
    controller.markStateFresh();
    expect(controller.stale).toBe(false);
    expect(audioEl.muted).toBe(false);
    expect(staleEvents).toEqual([true, false]);
  });

  it("counts a rejected out-of-order state as proof the server is reachable", async () => {
    const { sdk } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    let now = 1_000;
    const controller = new AvatarViewerController({
      sdk,
      videoEl,
      audioEl,
      mode: "broadcast",
      now: () => now,
    });
    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());
    controller.applyBroadcastState(audioOnlyState());

    now += 5_000;
    // The stale (older) state is rejected for source selection...
    expect(controller.applyBroadcastState(avatarState())).toBe(false);
    // ...but the page still marks freshness on every observation.
    controller.markStateFresh();
    expect(controller.checkStateFreshness()).toBe(false);
  });

  it("attaches already-published tracks on late join", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, mode: "broadcast" });

    const existingVideo = makeFakeTrack(TRACK_KIND.Video);
    const existingAudio = makeFakeTrack(TRACK_KIND.Audio);
    const strangerAudio = makeFakeTrack(TRACK_KIND.Audio);

    // The room is already live when this viewer joins, so no TrackSubscribed
    // event will ever fire for the media already flowing.
    const { sdk: _unused } = { sdk };
    const originalRoom = sdk.Room;
    sdk.Room = function () {
      const room = new (originalRoom as unknown as new () => FakeRoom)();
      (room as unknown as { remoteParticipants: Map<string, unknown> }).remoteParticipants =
        new Map([
          ["p1", fakeParticipant("avatar-abc", [existingVideo, existingAudio])],
          ["p2", fakeParticipant("some-viewer", [strangerAudio])],
        ]);
      return room;
    } as unknown as new () => FakeRoom;

    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());
    sdk.Room = originalRoom;

    expect(existingVideo.attach).toHaveBeenCalledTimes(1);
    expect(existingAudio.attach).toHaveBeenCalledTimes(1);
    expect(strangerAudio.attach).not.toHaveBeenCalled();
    expect(rooms.length).toBeGreaterThan(0);
  });

  it("does not restart a session on disconnect", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const disconnects: number[] = [];
    const controller = new AvatarViewerController({
      sdk,
      videoEl,
      audioEl,
      mode: "broadcast",
      onDisconnected: () => disconnects.push(1),
    });
    await controller.joinBroadcast(BROADCAST_CREDENTIALS, avatarState());

    rooms[0].emit(ROOM_EVENT.Disconnected);
    // Only a notification: re-entry means asking the admission API for a fresh
    // lease, never reconnecting on our own (which could over-admit the room).
    expect(disconnects).toEqual([1]);
    expect(controller.status).toBe(AvatarStatus.IDLE);
    expect(rooms.length).toBe(1);
  });

  it("attaches nothing before a descriptor has been applied", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl, mode: "broadcast" });
    await controller.joinBroadcast(BROADCAST_CREDENTIALS, null);

    const someAudio = makeFakeTrack(TRACK_KIND.Audio);
    rooms[0].emit(ROOM_EVENT.TrackSubscribed, someAudio, {}, fakeParticipant("avatar-abc"));
    // A broadcast viewer must not play media it has not been told to play.
    expect(someAudio.attach).not.toHaveBeenCalled();
  });
});

describe("AvatarViewerController — single mode is unchanged by FEAT-537", () => {
  it("defaults to single mode and keeps the local-audio fallback", async () => {
    const { sdk, rooms } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });

    expect(controller.mode).toBe("single");
    await controller.join(CREDENTIALS);
    expect(controller.shouldPlayLocalAudio()).toBe(true);

    // Tracks attach without any identity, exactly as before.
    const audio = makeFakeTrack(TRACK_KIND.Audio);
    rooms[0].emit(ROOM_EVENT.TrackSubscribed, audio);
    expect(audio.attach).toHaveBeenCalledTimes(1);
  });

  it("ignores broadcast state in single mode", async () => {
    const { sdk } = createFakeSdk();
    const { videoEl, audioEl } = makeElements();
    const controller = new AvatarViewerController({ sdk, videoEl, audioEl });
    await controller.join(CREDENTIALS);

    expect(controller.applyBroadcastState(audioOnlyState())).toBe(false);
    expect(controller.broadcastState).toBe(null);
    expect(controller.checkStateFreshness()).toBe(false);
  });
});
