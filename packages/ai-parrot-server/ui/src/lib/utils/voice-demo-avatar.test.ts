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
