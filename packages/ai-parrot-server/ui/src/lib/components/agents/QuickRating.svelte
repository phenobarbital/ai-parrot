<script lang="ts">
    import {
        getOptionsForType,
        type QuickRatingType,
        type FeedbackPayload,
    } from './FeedbackTypes';
    import { sendAgentFeedback } from '$lib/api/agent';
    import { toastStore } from '$lib/stores/toast.svelte';
    import { slide } from 'svelte/transition';
    import Icon from '@iconify/svelte';

    let {
        type,
        messageId,
        sessionId,
        chatbotId,
        onSubmit,
        onClose,
    } = $props<{
        type: QuickRatingType;
        messageId: string;
        sessionId: string;
        chatbotId: string;
        onSubmit?: () => void;
        onClose?: () => void;
    }>();

    let options = $derived(getOptionsForType(type));
    let isSubmitting = $state(false);
    let dropdownRef = $state<HTMLElement | undefined>(undefined);

    const iconColor = $derived(type === 'positive' ? 'text-green-500' : 'text-red-500');
    const headerText = $derived(type === 'positive' ? 'What did you like?' : 'What went wrong?');

    async function handleSelect(value: string) {
        if (isSubmitting) return;
        isSubmitting = true;

        try {
            const payload: FeedbackPayload = {
                chatbot_id: chatbotId,
                session_id: sessionId,
                turn_id: messageId,
                like: type === 'positive',
                dislike: type === 'negative',
                feedback_type: value,
            };

            await sendAgentFeedback(payload);
            toastStore.success('Feedback submitted!');
            onSubmit?.();
            onClose?.();
        } catch (error: unknown) {
            const message = error instanceof Error ? error.message : 'Unknown error';
            console.error('Quick rating error:', error);
            toastStore.error(`Failed to submit: ${message}`);
        } finally {
            isSubmitting = false;
        }
    }

    function handleOutsideClick(event: MouseEvent) {
        if (dropdownRef && !dropdownRef.contains(event.target as Node)) {
            onClose?.();
        }
    }

    $effect(() => {
        // Delay adding listener to avoid immediate close from the triggering click
        const timeoutId = setTimeout(() => {
            document.addEventListener('click', handleOutsideClick);
        }, 10);

        return () => {
            clearTimeout(timeoutId);
            document.removeEventListener('click', handleOutsideClick);
        };
    });
</script>

<div
    bind:this={dropdownRef}
    class="absolute left-0 top-full mt-1 z-50 min-w-[180px] max-w-[220px] rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-xl p-1.5"
    transition:slide={{ duration: 150 }}
    role="menu"
>
    <!-- Header -->
    <div class="flex items-center gap-2 px-2.5 py-1.5 mb-1">
        <Icon
            icon={type === 'positive' ? 'mdi:thumb-up' : 'mdi:thumb-down'}
            class={`h-4 w-4 ${iconColor}`}
        />
        <span class="text-xs font-medium text-slate-500 dark:text-slate-400">
            {headerText}
        </span>
    </div>

    <!-- Options -->
    {#each options as option}
        <button
            class="w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 disabled:opacity-50 transition-colors"
            onclick={() => handleSelect(option.value)}
            disabled={isSubmitting}
            role="menuitem"
        >
            {option.label}
        </button>
    {/each}

    <!-- Loading indicator -->
    {#if isSubmitting}
        <div class="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-slate-800/80 rounded-xl">
            <Icon icon="mdi:loading" class="h-5 w-5 animate-spin text-slate-500" />
        </div>
    {/if}
</div>
