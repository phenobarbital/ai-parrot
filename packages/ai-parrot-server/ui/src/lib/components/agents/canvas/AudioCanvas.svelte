<script lang="ts">
	import Icon from '@iconify/svelte';

	let { data }: { data: unknown } = $props();

	// data shape: { podcastPath: string; scriptPath?: string; script?: string } | '__loading__'
	let isLoading = $derived(data === '__loading__');

	let payload = $derived(
		typeof data === 'object' && data !== null ? (data as Record<string, string>) : null
	);
	let podcastUrl = $derived(payload?.podcastPath ?? '');
	let scriptContent = $derived(payload?.script ?? '');

	// Audio element and state
	let audioEl = $state<HTMLAudioElement | null>(null);
	let playing = $state(false);
	let currentTime = $state(0);
	let duration = $state(0);
	let volume = $state(0.8);
	let seeking = $state(false);

	function togglePlay() {
		if (!audioEl) return;
		if (playing) {
			audioEl.pause();
		} else {
			audioEl.play();
		}
	}

	function stop() {
		if (!audioEl) return;
		audioEl.pause();
		audioEl.currentTime = 0;
	}

	function handleTimeUpdate() {
		if (!audioEl || seeking) return;
		currentTime = audioEl.currentTime;
	}

	function handleLoadedMetadata() {
		if (!audioEl) return;
		duration = audioEl.duration;
	}

	function handleSeek(e: Event) {
		const target = e.target as HTMLInputElement;
		const val = parseFloat(target.value);
		currentTime = val;
		if (audioEl) {
			audioEl.currentTime = val;
		}
	}

	function handleVolumeChange(e: Event) {
		const target = e.target as HTMLInputElement;
		volume = parseFloat(target.value);
		if (audioEl) {
			audioEl.volume = volume;
		}
	}

	function formatTime(seconds: number): string {
		if (!isFinite(seconds) || seconds < 0) return '0:00';
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	let progress = $derived(duration > 0 ? (currentTime / duration) * 100 : 0);

	async function downloadAudio() {
		if (!podcastUrl) return;
		try {
			const response = await fetch(podcastUrl);
			const blob = await response.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			// Extract filename from the URL path
			const filename = podcastUrl.split('/').pop() || 'audio.wav';
			a.download = filename;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			URL.revokeObjectURL(url);
		} catch (err) {
			console.error('Failed to download audio:', err);
		}
	}
</script>

<div class="flex flex-col h-full">
	{#if isLoading}
		<!-- Loading state -->
		<div
			class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6 gap-3"
		>
			<div class="animate-spin">
				<Icon icon="mdi:loading" class="size-8 opacity-60" />
			</div>
			<p class="text-sm font-medium">Generating audio report...</p>
			<p class="text-xs">The agent is creating a podcast-style summary of your data.</p>
		</div>
	{:else if podcastUrl}
		<!-- Script display (if available) -->
		{#if scriptContent}
			<div class="flex-1 overflow-y-auto p-4">
				<h4 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
					Script
				</h4>
				<div class="prose prose-sm dark:prose-invert max-w-none text-sm whitespace-pre-wrap">
					{scriptContent}
				</div>
			</div>
		{:else}
			<div class="flex-1 flex flex-col items-center justify-center text-muted-foreground/40 p-6">
				<Icon icon="mdi:headphones" class="size-16 mb-3 opacity-30" />
				<p class="text-sm font-medium">Audio Report Ready</p>
				<p class="text-xs mt-1">Use the player below to listen.</p>
			</div>
		{/if}

		<!-- Audio player — bottom-left -->
		<div class="shrink-0 border-t border-border bg-muted/30 p-3">
			<!-- Hidden audio element -->
			<audio
				bind:this={audioEl}
				src={podcastUrl}
				onplay={() => (playing = true)}
				onpause={() => (playing = false)}
				onended={() => {
					playing = false;
					currentTime = 0;
				}}
				ontimeupdate={handleTimeUpdate}
				onloadedmetadata={handleLoadedMetadata}
			></audio>

			<!-- Progress bar -->
			<div class="mb-2">
				<div class="h-1 w-full rounded-full bg-muted overflow-hidden">
					<div
						class="h-full bg-primary rounded-full transition-[width] duration-100"
						style="width: {progress}%"
					></div>
				</div>
			</div>

			<!-- Seek bar -->
			<input
				type="range"
				min="0"
				max={duration || 0}
				step="0.1"
				value={currentTime}
				oninput={handleSeek}
				onfocus={() => (seeking = true)}
				onblur={() => (seeking = false)}
				class="w-full h-1 mb-2 accent-primary cursor-pointer"
				aria-label="Seek"
			/>

			<div class="flex items-center gap-2">
				<!-- Play/Pause -->
				<button
					class="btn btn-ghost btn-xs btn-square"
					onclick={togglePlay}
					title={playing ? 'Pause' : 'Play'}
				>
					<Icon icon={playing ? 'mdi:pause' : 'mdi:play'} class="size-5" />
				</button>

				<!-- Stop -->
				<button class="btn btn-ghost btn-xs btn-square" onclick={stop} title="Stop">
					<Icon icon="mdi:stop" class="size-4" />
				</button>

				<!-- Time display -->
				<span class="text-xs text-muted-foreground tabular-nums min-w-[70px]">
					{formatTime(currentTime)} / {formatTime(duration)}
				</span>

				<div class="flex-1"></div>

				<!-- Volume control -->
				<div class="flex items-center gap-1.5">
					<Icon
						icon={volume === 0 ? 'mdi:volume-off' : volume < 0.5 ? 'mdi:volume-low' : 'mdi:volume-high'}
						class="size-3.5 text-muted-foreground"
					/>
					<input
						type="range"
						min="0"
						max="1"
						step="0.05"
						value={volume}
						oninput={handleVolumeChange}
						class="w-16 h-1 accent-primary cursor-pointer"
						aria-label="Volume"
					/>
				</div>

				<!-- Download -->
				<button
					onclick={downloadAudio}
					class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
					title="Download audio"
				>
					<Icon icon="mdi:download" class="size-4" />
				</button>
			</div>
		</div>
	{:else}
		<!-- Empty state -->
		<div
			class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6"
		>
			<Icon icon="mdi:headphones" class="size-12 mb-3 opacity-40" />
			<p class="text-sm font-medium">No Audio Report</p>
			<p class="text-xs mt-1">Use "Listen This" to generate an audio report from your canvas data.</p>
		</div>
	{/if}
</div>
