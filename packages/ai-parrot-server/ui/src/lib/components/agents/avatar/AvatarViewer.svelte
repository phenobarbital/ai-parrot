<script lang="ts">
  /**
   * AvatarViewer — FEAT-169 LiveAvatar Integration
   *
   * Owns the LiveKit Room lifecycle and renders a floating, collapsible,
   * scroll-independent video card. This component is a subscribe-only viewer —
   * it NEVER publishes video or audio from the browser.
   *
   * Positioning: position: fixed, pinned to the bottom-right corner of the
   * viewport at a high z-index, so thread scroll never moves it.
   *
   * Usage:
   *   <AvatarViewer
   *     agentId="my-agent"
   *     sessionId={currentSessionId}
   *     tenantId={clientStore.getClient()?.slug}
   *     enabled={avatarEnabled}
   *     client={scopedClient}
   *     bind:collapsed={avatarCollapsed}
   *     onstatuschange={(s) => avatarLive = s === 'live'}
   *   />
   */
  import { onDestroy } from "svelte";
  import { browser } from "$app/environment";
  import {
    startAvatarSession,
    stopAvatarSession,
    AvatarDisabledError,
    AvatarUnavailableError,
    type AvatarStatus,
  } from "$lib/api/avatar";
  import type { AxiosInstance } from "axios";

  // ── Props ─────────────────────────────────────────────────────────────────────

  interface AvatarViewerProps {
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
  }: AvatarViewerProps = $props();

  // ── State ─────────────────────────────────────────────────────────────────────

  let status = $state<AvatarStatus>("idle");
  let videoEl = $state<HTMLVideoElement | null>(null);
  let audioEl = $state<HTMLAudioElement | null>(null);
  let isMuted = $state(true); // start muted for autoplay policy; user unmutes

  // LiveKit Room instance — lives only in browser, created dynamically
  // to avoid SSR-breaking static imports of livekit-client (which accesses window)
  let room: any = null;

  // ── Helpers ───────────────────────────────────────────────────────────────────

  function setStatus(s: AvatarStatus) {
    status = s;
    onstatuschange?.(s);
  }

  async function startSession() {
    if (!browser || !enabled || status !== "idle") return;

    setStatus("connecting");
    try {
      // Dynamic import so livekit-client (which touches window) never runs on the server
      const { Room, RoomEvent, Track } = await import("livekit-client");

      const creds = await startAvatarSession(
        agentId,
        sessionId,
        tenantId,
        client,
      );

      // Create and wire the LiveKit room
      room = new Room({ adaptiveStream: true, dynacast: true });

      room.on(RoomEvent.TrackSubscribed, (track: any) => {
        if (track.kind === Track.Kind.Video && videoEl) {
          track.attach(videoEl);
        } else if (track.kind === Track.Kind.Audio && audioEl) {
          track.attach(audioEl);
        }
      });

      room.on(RoomEvent.TrackUnsubscribed, (track: any) => {
        track.detach();
      });

      room.on(RoomEvent.Disconnected, () => {
        if (status === "live") setStatus("idle");
      });

      await room.connect(creds.livekit_url, creds.client_token);
      setStatus("live");
    } catch (err) {
      if (err instanceof AvatarDisabledError) {
        setStatus("disabled");
      } else if (err instanceof AvatarUnavailableError) {
        setStatus("error");
      } else {
        console.error("[AvatarViewer] Error starting session:", err);
        setStatus("error");
      }
    }
  }

  async function stopSession() {
    if (!browser) return;
    try {
      if (room) {
        await room.disconnect();
        room = null;
      }
    } catch {
      // swallow — teardown must not throw
    }
    try {
      await stopAvatarSession(agentId, sessionId, client);
    } catch {
      // swallow
    }
    if (status === "live" || status === "connecting") {
      setStatus("idle");
    }
  }

  function handleEnableSound() {
    isMuted = false;
    if (audioEl) {
      audioEl.muted = false;
      audioEl.play().catch(() => {
        // Autoplay blocked even after click — ignore; user can try again
      });
    }
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────────

  // Start session when enabled and idle in the browser
  $effect(() => {
    if (browser && enabled && status === "idle" && sessionId) {
      startSession();
    }
  });

  // Stop session when disabled
  $effect(() => {
    if (!enabled && (status === "live" || status === "connecting")) {
      stopSession();
    }
  });

  // Cleanup on component destroy
  onDestroy(() => {
    stopSession();
  });

  // Cleanup on page unload (tab close / navigation)
  $effect(() => {
    if (!browser) return;
    const handler = () => stopSession();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  });
</script>

<!--
  Render nothing when:
  - not in browser (SSR)
  - disabled (tenant has no opt-in → status === 'disabled')
  - not enabled
-->
{#if browser && enabled && status !== "disabled"}
  <!--
    Fixed card — pinned to bottom-right corner of the viewport.
    z-[50] places it above the chat thread (no high z-index) but
    below the floating chat FAB (z-[60]) and panel (z-[55]) when
    used inside the floating chat context.
  -->
  <div
    class={docked
      ? "relative w-full flex-1 min-h-0 flex flex-col gap-0 rounded-2xl border border-base-300 bg-base-100 shadow-sm overflow-hidden"
      : "fixed bottom-4 right-4 z-[50] flex flex-col gap-0 rounded-2xl shadow-2xl border border-base-300 bg-base-100 overflow-hidden transition-all duration-300"}
    class:w-64={!docked && !collapsed}
    class:w-14={!docked && collapsed}
    class:h-auto={!docked && !collapsed}
    style={!docked && collapsed ? "height: 3.5rem;" : ""}
    role="complementary"
    aria-label="Avatar video"
  >
    <!-- Header / pill -->
    <div
      class="flex items-center justify-between px-2 py-1.5 bg-primary text-primary-foreground shrink-0"
    >
      <div class="flex items-center gap-1.5 min-w-0">
        <!-- Status dot -->
        <span
          class="inline-block w-2 h-2 rounded-full shrink-0"
          class:bg-green-400={status === "live"}
          class:animate-pulse={status === "connecting"}
          class:bg-yellow-400={status === "connecting"}
          class:bg-red-400={status === "error"}
          class:bg-base-300={status === "idle"}
        ></span>
        {#if !collapsed}
          <span class="text-xs font-semibold truncate">
            {#if status === "connecting"}Connecting avatar…{:else if status === "live"}Avatar{:else if status === "error"}Avatar
              unavailable{:else}Avatar{/if}
          </span>
        {/if}
      </div>
      <!-- Collapse / expand button — hidden while docked (the panel owns size) -->
      {#if !docked}
        <button
          type="button"
          class="flex items-center justify-center w-6 h-6 rounded hover:bg-primary-foreground/10 shrink-0 transition-colors"
          aria-label={collapsed ? "Expand avatar" : "Collapse avatar"}
          onclick={() => {
            collapsed = !collapsed;
          }}
        >
          <svg class="w-3 h-3" viewBox="0 0 12 12" fill="currentColor">
            {#if collapsed}
              <!-- Expand icon: chevron up-left -->
              <path
                d="M2 8L6 4L10 8"
                stroke="currentColor"
                stroke-width="1.5"
                fill="none"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            {:else}
              <!-- Collapse icon: chevron down-right -->
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
      <!-- Video area — fills the panel while docked, fixed 9/16 card otherwise -->
      <div
        class={docked
          ? "relative w-full flex-1 min-h-0 bg-black"
          : "relative w-full bg-black"}
        style={docked ? "" : "aspect-ratio: 9/16; max-height: 360px;"}
      >
        {#if status === "connecting"}
          <!-- Connecting overlay -->
          <div
            class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white"
          >
            <div
              class="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin"
            ></div>
            <span class="text-xs">Connecting avatar…</span>
          </div>
        {:else if status === "error"}
          <!-- Error overlay -->
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
              >Avatar unavailable</span
            >
            <span class="text-[10px] text-white/60"
              >Chat continues normally</span
            >
          </div>
        {/if}

        <!-- Video element — always rendered so track.attach has a target.
             Docked: object-contain shows the whole avatar frame (no side
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
          aria-label="Avatar video stream"
        ></video>
      </div>

      <!-- Controls footer -->
      {#if status === "live"}
        <div
          class="flex items-center justify-center px-2 py-1.5 border-t border-base-200"
        >
          {#if isMuted}
            <button
              type="button"
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-base-200"
              onclick={handleEnableSound}
            >
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
                  d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.506-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z"
                />
              </svg>
              Enable sound
            </button>
          {:else}
            <span class="text-xs text-muted-foreground flex items-center gap-1">
              <svg
                class="w-3 h-3 text-green-500"
                viewBox="0 0 24 24"
                fill="currentColor"
              >
                <path
                  d="M13.5 4.06c0-1.336-1.616-2.005-2.56-1.06l-4.5 4.5H4.508c-1.141 0-2.318.664-2.66 1.905A9.76 9.76 0 001.5 12c0 .898.121 1.768.35 2.595.341 1.24 1.518 1.905 2.659 1.905h1.93l4.5 4.5c.945.945 2.561.276 2.561-1.06V4.06zM18.584 5.106a.75.75 0 011.06 0c3.808 3.807 3.808 9.98 0 13.788a.75.75 0 01-1.06-1.06 8.25 8.25 0 000-11.668.75.75 0 010-1.06z"
                />
              </svg>
              Sound on
            </span>
          {/if}
        </div>
      {/if}
    {/if}
  </div>
{/if}

<!-- Hidden audio element — always rendered (outside the collapsed check) for track attachment -->
{#if browser && enabled && status !== "disabled"}
  <audio
    bind:this={audioEl}
    autoplay
    muted={isMuted}
    style="display:none;"
    aria-hidden="true"
  ></audio>
{/if}
