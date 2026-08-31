<script lang="ts">
  /**
   * Compact player for an agent's spoken contestation (AgentTalk Voice).
   *
   * Receives the base64 audio + its REAL mime (`audio_format` from the
   * envelope) and renders a play/pause control with a scrub bar beneath the
   * assistant's text. Audio is treated as an *enhancement*: this component is
   * only mounted when `audioBase64` is present.
   */
  import Icon from "@iconify/svelte";
  import { browser } from "$app/environment";

  let {
    audioBase64,
    audioFormat = "audio/wav",
    autoplay = false,
  } = $props<{
    audioBase64: string;
    audioFormat?: string;
    /** Play once automatically as soon as the audio is ready (lazy fetch). */
    autoplay?: boolean;
  }>();

  let audioEl = $state<HTMLAudioElement>();
  let isPlaying = $state(false);
  let currentTime = $state(0);
  let duration = $state(0);

  // Decode base64 → Blob → object URL once per payload. Use the REAL mime the
  // server reported (do not assume WAV). Revoke the URL when it changes/unmounts.
  let objectUrl = $derived.by(() => {
    if (!browser || !audioBase64) return "";
    try {
      const bytes = Uint8Array.from(atob(audioBase64), (c) => c.charCodeAt(0));
      return URL.createObjectURL(new Blob([bytes], { type: audioFormat }));
    } catch (e) {
      console.error("Failed to decode voice answer audio", e);
      return "";
    }
  });

  $effect(() => {
    const url = objectUrl;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  });

  // Lazy-fetch replay (FEAT-257): when the audio is fetched on click, play it
  // once automatically so a single click both loads and plays. History-loaded
  // audio (autoplay=false) stays paused until the user hits play.
  let _autoplayed = false;
  $effect(() => {
    if (autoplay && !_autoplayed && audioEl && objectUrl) {
      _autoplayed = true;
      audioEl.play().catch(() => {});
    }
  });

  function togglePlay() {
    if (!audioEl) return;
    if (isPlaying) {
      audioEl.pause();
    } else {
      audioEl
        .play()
        .catch((e) => console.error("Voice answer playback failed", e));
    }
  }

  function onSeek(e: Event) {
    if (!audioEl) return;
    const value = Number((e.target as HTMLInputElement).value);
    audioEl.currentTime = value;
    currentTime = value;
  }

  function fmt(s: number): string {
    if (!Number.isFinite(s) || s < 0) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  let progress = $derived(duration > 0 ? (currentTime / duration) * 100 : 0);
</script>

{#if objectUrl}
  <div
    class="mt-2 flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 px-2.5 py-1.5 max-w-[320px]"
  >
    <audio
      bind:this={audioEl}
      src={objectUrl}
      preload="metadata"
      onplay={() => (isPlaying = true)}
      onpause={() => (isPlaying = false)}
      onended={() => (isPlaying = false)}
      ontimeupdate={() => audioEl && (currentTime = audioEl.currentTime)}
      onloadedmetadata={() =>
        audioEl &&
        Number.isFinite(audioEl.duration) &&
        (duration = audioEl.duration)}
    ></audio>

    <button
      type="button"
      class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-500 text-white hover:bg-blue-600 transition-colors"
      onclick={togglePlay}
      title={isPlaying ? "Pause" : "Play answer"}
      aria-label={isPlaying ? "Pause" : "Play answer"}
    >
      <Icon icon={isPlaying ? "mdi:pause" : "mdi:play"} class="size-4" />
    </button>

    <input
      type="range"
      min="0"
      max={duration || 0}
      step="0.1"
      value={currentTime}
      oninput={onSeek}
      class="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-slate-200 dark:bg-slate-600 accent-blue-500"
      style={`background: linear-gradient(to right, rgb(59 130 246) ${progress}%, transparent ${progress}%)`}
      aria-label="Seek audio"
    />

    <span
      class="shrink-0 text-[10px] tabular-nums text-slate-500 dark:text-slate-400"
    >
      {fmt(currentTime)} / {fmt(duration)}
    </span>
  </div>
{/if}
