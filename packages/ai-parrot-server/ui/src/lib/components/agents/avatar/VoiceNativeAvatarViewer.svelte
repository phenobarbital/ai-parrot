<script lang="ts">
  /**
   * VoiceNativeAvatarViewer — FEAT-243 LiveAvatar Phase C (voice-native hybrid).
   *
   * Unlike the Phase A {@link AvatarViewer} (subscribe-only), this component:
   *   - publishes the browser microphone into the LiveKit room so the server-side
   *     LiveKit Agents worker can run STT / VAD / turn-detection / barge-in;
   *   - subscribes to the avatar's video + TTS audio tracks;
   *   - listens on the shared AgentChat WS (`/ws/userinfo`) channel == session_id
   *     for structured outputs (charts/data/canvas/tool_calls) and forwards them
   *     to the host via `onStructured` so they render in the chat thread.
   *
   * No per-turn POST: the user just speaks; the worker drives the turn. Voice-only
   * turns produce NO structured message — the user simply hears the avatar.
   *
   * Start is gated behind a user gesture (the "Start talking" button) to satisfy
   * the browser microphone-permission + autoplay policies.
   *
   * Usage:
   *   <VoiceNativeAvatarViewer
   *     agentId="my-agent"
   *     sessionId={currentSessionId}
   *     tenantId={clientStore.getClient()?.slug}
   *     enabled={voiceNativeEnabled}
   *     bind:collapsed={avatarCollapsed}
   *     onstatuschange={(s) => avatarLive = s === 'live'}
   *     onStructured={(m) => appendAssistantMessage(m)}
   *   />
   */
  import { onDestroy } from "svelte";
  import { browser } from "$app/environment";
  import {
    startVoiceNativeSession,
    stopAvatarSession,
    isStructuredOutputMessage,
    structuredOutputToAgentMessage,
    AvatarDisabledError,
    AvatarUnavailableError,
    type AvatarStatus,
  } from "$lib/api/avatar";
  import type { AgentMessage } from "$lib/types/agent";
  import { wsService } from "$lib/services/websocket-service";
  import type { AxiosInstance } from "axios";

  // ── Props ─────────────────────────────────────────────────────────────────────

  /** Real-time turn state for a live-feeling UI. */
  type TurnState = "listening" | "speaking" | "thinking" | "idle";

  interface VoiceNativeAvatarViewerProps {
    agentId: string;
    sessionId: string;
    tenantId?: string;
    enabled?: boolean;
    client?: AxiosInstance;
    collapsed?: boolean;
    /**
     * Docked mode: render inline filling a parent panel (relative, full
     * width/height, no shadow/rounding) instead of the default floating
     * card pinned to the bottom-right corner. The parent owns positioning,
     * width and borders. Collapse is disabled while docked.
     */
    docked?: boolean;
    onstatuschange?: (status: AvatarStatus) => void;
    onStructured?: (message: AgentMessage) => void;
  }

  let {
    agentId,
    sessionId,
    tenantId = undefined,
    enabled = true,
    client = undefined,
    collapsed = $bindable(false),
    docked = false,
    onstatuschange = undefined,
    onStructured = undefined,
  }: VoiceNativeAvatarViewerProps = $props();

  // ── State ─────────────────────────────────────────────────────────────────────

  let status = $state<AvatarStatus>("idle");
  let turn = $state<TurnState>("idle");
  let videoEl = $state<HTMLVideoElement | null>(null);
  let audioEl = $state<HTMLAudioElement | null>(null);
  let micMuted = $state(false);

  // LiveKit Room + livekit-client enums (created dynamically; livekit-client
  // touches window so it must never be statically imported during SSR).
  let room: any = null;
  let RoomEventRef: any = null;
  let TrackRef: any = null;

  // WS structured-output handler disposer (wildcard listener on the shared WS).
  let wsDispose: (() => void) | null = null;

  const AVATAR_IDENTITY = "avatar-agent";

  // ── Helpers ───────────────────────────────────────────────────────────────────

  function setStatus(s: AvatarStatus) {
    status = s;
    onstatuschange?.(s);
  }

  /** Subscribe to the structured-output channel on the shared AgentChat WS. */
  async function openStructuredChannel() {
    // Reuse the app's single WS connection (idempotent if already connected/auth'd).
    await wsService.connect(client?.defaults?.baseURL as string | undefined);
    wsService.subscribe(sessionId);

    wsDispose?.();
    wsDispose = wsService.onMessage("*", (msg) => {
      if (!isStructuredOutputMessage(msg, sessionId)) return;
      // A tool_call turn means the agent is working — reflect "thinking".
      if (msg.type === "tool_call") turn = "thinking";
      onStructured?.(structuredOutputToAgentMessage(msg));
    });
  }

  /** Derive listening/speaking/idle from who is actively speaking in the room. */
  function wireTurnDetection() {
    if (!room || !RoomEventRef) return;
    room.on(RoomEventRef.ActiveSpeakersChanged, (speakers: any[]) => {
      const avatarSpeaking = speakers.some(
        (p) => p?.identity === AVATAR_IDENTITY || !p?.isLocal,
      );
      const userSpeaking = speakers.some((p) => p?.isLocal);
      if (avatarSpeaking) turn = "speaking";
      else if (userSpeaking) turn = "listening";
      else if (turn !== "thinking") turn = "idle";
    });
  }

  async function startSession() {
    if (!browser || !enabled || status !== "idle" || !sessionId) return;

    setStatus("connecting");
    try {
      const { Room, RoomEvent, Track } = await import("livekit-client");
      RoomEventRef = RoomEvent;
      TrackRef = Track;

      // 1) Mint publish(audio)+subscribe token + dispatch the worker.
      const creds = await startVoiceNativeSession(
        agentId,
        sessionId,
        tenantId,
        client,
      );

      // 2) Subscribe to the structured-output channel BEFORE speaking
      //    (UserSocketManager has no buffer — late subscribers miss messages).
      await openStructuredChannel();

      // 3) Join the room, subscribe avatar tracks, publish the mic.
      room = new Room({ adaptiveStream: true, dynacast: true });
      room.on(RoomEvent.TrackSubscribed, (track: any) => {
        if (track.kind === Track.Kind.Video && videoEl) track.attach(videoEl);
        else if (track.kind === Track.Kind.Audio && audioEl)
          track.attach(audioEl);
      });
      room.on(RoomEvent.TrackUnsubscribed, (track: any) => track.detach());
      room.on(RoomEvent.Disconnected, () => {
        if (status === "live") setStatus("idle");
      });
      wireTurnDetection();

      await room.connect(creds.livekit_url, creds.token);
      // ▶ Publish the microphone — this is what makes Phase C voice-native.
      await room.localParticipant.setMicrophoneEnabled(true);
      micMuted = false;
      turn = "listening";
      setStatus("live");
    } catch (err) {
      if (err instanceof AvatarDisabledError) {
        setStatus("disabled");
      } else if (err instanceof AvatarUnavailableError) {
        setStatus("error");
      } else if (
        err instanceof DOMException &&
        err.name === "NotAllowedError"
      ) {
        // Microphone permission denied — no turn-taking possible.
        console.warn("[VoiceNativeAvatarViewer] microphone permission denied");
        setStatus("error");
      } else {
        console.error("[VoiceNativeAvatarViewer] Error starting session:", err);
        setStatus("error");
      }
      await teardown();
    }
  }

  async function teardown() {
    try {
      wsDispose?.();
      wsDispose = null;
      if (sessionId) wsService.unsubscribe(sessionId);
    } catch {
      // ignore
    }
    try {
      if (room) {
        await room.localParticipant?.setMicrophoneEnabled(false);
        await room.disconnect();
        room = null;
      }
    } catch {
      // swallow — teardown must not throw
    }
  }

  async function stopSession() {
    if (!browser) return;
    await teardown();
    try {
      await stopAvatarSession(agentId, sessionId, client);
    } catch {
      // swallow
    }
    turn = "idle";
    if (status === "live" || status === "connecting") setStatus("idle");
  }

  async function toggleMute() {
    if (!room) return;
    micMuted = !micMuted;
    try {
      await room.localParticipant.setMicrophoneEnabled(!micMuted);
    } catch {
      micMuted = !micMuted; // revert on failure
    }
  }

  function handleEnableSound() {
    if (audioEl) {
      audioEl.muted = false;
      audioEl.play().catch(() => {});
    }
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────────

  // Stop when disabled mid-session (opt-out / toggle off).
  $effect(() => {
    if (!enabled && (status === "live" || status === "connecting")) {
      stopSession();
    }
  });

  onDestroy(() => {
    stopSession();
  });

  $effect(() => {
    if (!browser) return;
    const handler = () => stopSession();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  });

  const turnLabel = $derived(
    turn === "speaking"
      ? "Hablando…"
      : turn === "listening"
        ? "Escuchando…"
        : turn === "thinking"
          ? "Pensando…"
          : "",
  );
</script>

<!-- Render nothing on SSR, when disabled, or when the tenant has no opt-in. -->
{#if browser && enabled && status !== "disabled"}
  <div
    class={docked
      ? "relative w-full flex-1 min-h-0 flex flex-col gap-0 rounded-2xl border border-base-300 bg-base-100 shadow-sm overflow-hidden"
      : "fixed bottom-4 right-4 z-[50] flex flex-col gap-0 rounded-2xl shadow-2xl border border-base-300 bg-base-100 overflow-hidden transition-all duration-300"}
    class:w-64={!docked && !collapsed}
    class:w-14={!docked && collapsed}
    style={!docked && collapsed ? "height: 3.5rem;" : ""}
    role="complementary"
    aria-label="Avatar de voz"
  >
    <!-- Header / pill -->
    <div
      class="flex items-center justify-between px-2 py-1.5 bg-primary text-primary-foreground shrink-0"
    >
      <div class="flex items-center gap-1.5 min-w-0">
        <span
          class="inline-block w-2 h-2 rounded-full shrink-0"
          class:bg-green-400={status === "live"}
          class:animate-pulse={status === "connecting" ||
            turn === "speaking" ||
            turn === "listening"}
          class:bg-yellow-400={status === "connecting"}
          class:bg-red-400={status === "error"}
          class:bg-base-300={status === "idle"}
        ></span>
        {#if !collapsed}
          <span class="text-xs font-semibold truncate">
            {#if status === "connecting"}Conectando…{:else if status === "live"}{turnLabel ||
                "Avatar"}{:else if status === "error"}Avatar no disponible{:else}Avatar
              de voz{/if}
          </span>
        {/if}
      </div>
      {#if !docked}
        <button
          type="button"
          class="flex items-center justify-center w-6 h-6 rounded hover:bg-primary-foreground/10 shrink-0 transition-colors"
          aria-label={collapsed ? "Expandir avatar" : "Contraer avatar"}
          onclick={() => {
            collapsed = !collapsed;
          }}
        >
          <svg class="w-3 h-3" viewBox="0 0 12 12" fill="currentColor">
            {#if collapsed}
              <path
                d="M2 8L6 4L10 8"
                stroke="currentColor"
                stroke-width="1.5"
                fill="none"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            {:else}
              <path
                d="M2 4L6 8L10 4"
                stroke="currentColor"
                stroke-width="1.5"
                fill="none"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            {/if}
          </svg>
        </button>
      {/if}
    </div>

    {#if docked || !collapsed}
      <div
        class={docked
          ? "relative w-full flex-1 min-h-0 bg-black"
          : "relative w-full bg-black"}
        style={docked ? "" : "aspect-ratio: 9/16; max-height: 360px;"}
      >
        {#if status === "idle"}
          <!-- Gesture-gated start (mic permission + autoplay) -->
          <div
            class="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white px-4 text-center"
          >
            <span class="text-xs text-white/70"
              >Conversa por voz con el avatar.</span
            >
            <button type="button" class="btn btn-sm" onclick={startSession}>
              Empezar a hablar
            </button>
          </div>
        {:else if status === "connecting"}
          <div
            class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white"
          >
            <div
              class="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin"
            ></div>
            <span class="text-xs">Conectando…</span>
          </div>
        {:else if status === "error"}
          <div
            class="absolute inset-0 flex flex-col items-center justify-center gap-1 text-white px-3 text-center"
          >
            <svg
              class="w-6 h-6 text-yellow-400 mb-1"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
              />
            </svg>
            <span class="text-xs text-yellow-300 font-medium"
              >Avatar no disponible</span
            >
            <span class="text-[10px] text-white/60"
              >El chat continúa normalmente</span
            >
            <button
              type="button"
              class="btn btn-xs mt-1"
              onclick={() => {
                setStatus("idle");
              }}
            >
              Reintentar
            </button>
          </div>
        {/if}

        <!-- Docked: object-contain shows the whole avatar frame (no side
             truncation); the black card bg hides any letterbox bars. -->
        <video
          bind:this={videoEl}
          class={docked
            ? "w-full h-full object-contain"
            : "w-full h-full object-cover"}
          class:opacity-0={status !== "live"}
          autoplay
          playsinline
          muted
          aria-label="Vídeo del avatar"
        ></video>
      </div>

      {#if status === "live"}
        <div
          class="flex items-center justify-between gap-2 px-2 py-1.5 border-t border-base-200"
        >
          <button
            type="button"
            class="flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-base-200 transition-colors"
            class:text-red-500={micMuted}
            class:text-muted-foreground={!micMuted}
            onclick={toggleMute}
            aria-label={micMuted ? "Activar micrófono" : "Silenciar micrófono"}
          >
            {#if micMuted}
              <svg
                class="w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M3 3l18 18M9 9v3a3 3 0 005.12 2.12M15 9.34V5a3 3 0 00-5.94-.6M17 16.95A7 7 0 015 12v-1m14 0v1a6.97 6.97 0 01-.34 2.15"
                />
              </svg>
              Micro off
            {:else}
              <svg
                class="w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M12 1.5a3 3 0 00-3 3v7a3 3 0 006 0v-7a3 3 0 00-3-3zM5 11a7 7 0 0014 0M12 18.5V22"
                />
              </svg>
              Micro on
            {/if}
          </button>

          <button
            type="button"
            class="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded hover:bg-base-200 transition-colors"
            onclick={handleEnableSound}
          >
            Activar sonido
          </button>
        </div>
      {/if}
    {/if}
  </div>
{/if}

<!-- Hidden audio sink — always rendered (outside collapsed) for track attachment. -->
{#if browser && enabled && status !== "disabled"}
  <audio bind:this={audioEl} autoplay style="display:none;" aria-hidden="true"
  ></audio>
{/if}
