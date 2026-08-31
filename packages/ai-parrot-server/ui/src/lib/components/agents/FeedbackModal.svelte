<script lang="ts">
    import { AppDialog } from "$lib/ui/components";
    import Icon from "@iconify/svelte";
    import { toastStore } from "$lib/stores/toast.svelte";
    import { sendAgentFeedback } from "$lib/api/agent";
    import { FEEDBACK_CATEGORIES, type FeedbackPayload } from "./FeedbackTypes";

    let {
        open = $bindable(false),
        messageId, // turn_id
        sessionId,
        chatbotId,
        onSubmit,
    } = $props<{
        open: boolean;
        messageId: string;
        sessionId: string;
        chatbotId: string;
        onSubmit?: () => void;
    }>();

    let rating = $state(0);
    let feedbackType = $state("");
    let feedbackText = $state("");
    let isSubmitting = $state(false);
    let draftLoaded = $state(false);

    const DRAFT_KEY = "feedback-draft";

    // Load draft when modal opens
    $effect(() => {
        if (open && messageId && !draftLoaded) {
            try {
                const draft = localStorage.getItem(`${DRAFT_KEY}-${messageId}`);
                if (draft) {
                    const parsed = JSON.parse(draft);
                    feedbackType = parsed.feedbackType || "";
                    feedbackText = parsed.feedbackText || "";
                    rating = parsed.rating || 0;
                }
            } catch (e) {
                console.warn("Failed to load feedback draft:", e);
            }
            draftLoaded = true;
        }
        // Reset draftLoaded when modal closes
        if (!open) {
            draftLoaded = false;
        }
    });

    // Save draft when content changes
    $effect(() => {
        if (open && messageId && (feedbackText || feedbackType || rating > 0)) {
            try {
                localStorage.setItem(
                    `${DRAFT_KEY}-${messageId}`,
                    JSON.stringify({
                        feedbackType,
                        feedbackText,
                        rating,
                    })
                );
            } catch (e) {
                console.warn("Failed to save feedback draft:", e);
            }
        }
    });

    async function handleSubmit() {
        isSubmitting = true;
        try {
            const payload: FeedbackPayload = {
                chatbot_id: chatbotId,
                session_id: sessionId,
                turn_id: messageId,
                rating: rating > 0 ? rating : undefined,
                feedback_type: feedbackType || undefined,
                feedback: feedbackText || undefined,
            };

            await sendAgentFeedback(payload);
            toastStore.success("Feedback submitted successfully!");

            // Clear draft on successful submit
            try {
                localStorage.removeItem(`${DRAFT_KEY}-${messageId}`);
            } catch (e) {
                // Ignore localStorage errors
            }

            if (onSubmit) onSubmit();
            open = false;

            // Reset fields
            rating = 0;
            feedbackType = "";
            feedbackText = "";
        } catch (error: unknown) {
            const message = error instanceof Error ? error.message : "Unknown error";
            console.error("Feedback Error", error);
            toastStore.error(`Failed to submit feedback: ${message}`);
        } finally {
            isSubmitting = false;
        }
    }

    function setRating(r: number) {
        rating = r;
    }

    function handleCancel() {
        open = false;
    }
</script>

<AppDialog bind:open title="Provide Feedback" size="sm">
    <div class="flex flex-col gap-4">
        <!-- Feedback Text (Primary) -->
        <div>
            <label
                for="feedback-text"
                class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
            >
                Your Feedback
            </label>
            <textarea
                id="feedback-text"
                class="textarea w-full"
                bind:value={feedbackText}
                placeholder="Tell us what you think..."
                rows="4"
            ></textarea>
        </div>

        <!-- Feedback Category -->
        <div>
            <label
                for="feedback-type"
                class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
            >
                Category <span class="text-gray-400 font-normal">(optional)</span>
            </label>
            <select
                id="feedback-type"
                class="select w-full"
                bind:value={feedbackType}
            >
                <option value="">Select a category...</option>
                {#each FEEDBACK_CATEGORIES as opt}
                    <option value={opt.value}>{opt.label}</option>
                {/each}
            </select>
        </div>

        <!-- Rating Stars (Optional, de-emphasized) -->
        <div class="pt-2 border-t border-gray-200 dark:border-gray-700">
            <label
                class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
            >
                Rating <span class="text-gray-400 font-normal">(optional)</span>
            </label>
            <div class="flex items-center gap-1">
                {#each Array(5) as _, i}
                    {@const starRating = i + 1}
                    <button
                        type="button"
                        class="hover:scale-110 transition-transform focus:outline-none text-yellow-400 p-0.5"
                        onclick={() => setRating(starRating)}
                        title={`Rate ${starRating} stars`}
                    >
                        {#if rating >= starRating}
                            <Icon icon="mdi:star" class="w-6 h-6" />
                        {:else}
                            <Icon
                                icon="mdi:star-outline"
                                class="w-6 h-6 text-gray-300 dark:text-gray-600"
                            />
                        {/if}
                    </button>
                {/each}
                {#if rating > 0}
                    <button
                        type="button"
                        class="ml-2 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                        onclick={() => setRating(0)}
                    >
                        Clear
                    </button>
                {/if}
            </div>
        </div>

        <!-- Buttons -->
        <div class="flex justify-end gap-2 pt-2">
            <button type="button" class="btn btn-ghost" onclick={handleCancel}>
                Cancel
            </button>
            <button
                type="button"
                class="btn btn-primary"
                onclick={handleSubmit}
                disabled={isSubmitting}
            >
                {#if isSubmitting}
                    <Icon icon="mdi:loading" class="w-4 h-4 animate-spin mr-1" />
                    Submitting...
                {:else}
                    Submit Feedback
                {/if}
            </button>
        </div>
    </div>
</AppDialog>
