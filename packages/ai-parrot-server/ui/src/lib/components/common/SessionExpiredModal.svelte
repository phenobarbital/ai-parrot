<!-- src/lib/components/common/SessionExpiredModal.svelte -->
<script lang="ts">
    import { onMount, onDestroy } from "svelte";

    interface Props {
        onLogout: () => void;
    }

    let { onLogout }: Props = $props();

    let countdown = $state(5);
    let interval: ReturnType<typeof setInterval> | null = null;

    onMount(() => {
        interval = setInterval(() => {
            countdown -= 1;
            if (countdown <= 0) {
                if (interval) clearInterval(interval);
                onLogout();
            }
        }, 1000);
    });

    onDestroy(() => {
        if (interval) clearInterval(interval);
    });
</script>

<!-- Backdrop -->
<div
    class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
>
    <!-- Modal Card -->
    <div
        class="bg-base-100 border-base-content/10 w-full max-w-md rounded-2xl border p-8 shadow-2xl"
    >
        <!-- Icon -->
        <div
            class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-error/10"
        >
            <svg
                class="h-8 w-8 text-error"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
            >
                <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z"
                ></path>
            </svg>
        </div>

        <!-- Title -->
        <h2 class="mb-2 text-center text-xl font-bold text-base-content">
            Session Expired
        </h2>

        <!-- Message -->
        <p class="text-base-content/70 mb-6 text-center text-sm">
            Your session has expired or is no longer valid. Please log in again
            to continue.
        </p>

        <!-- Countdown -->
        <div class="mb-4 text-center">
            <span class="text-base-content/50 text-xs">
                Redirecting in <span class="font-mono font-bold text-error"
                    >{countdown}</span
                > seconds…
            </span>
        </div>

        <!-- Button -->
        <button onclick={onLogout} class="btn btn-error btn-block">
            Go to login now ({countdown})
        </button>
    </div>
</div>
