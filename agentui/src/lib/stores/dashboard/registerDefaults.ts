import { registry } from '$lib/stores/dashboard/registry.svelte';

export function registerDefaultWidgets() {
    registry.register({
        type: 'agent-chat',
        name: 'Agent Chat',
        icon: '💬',
        description: 'Interactive chat with AI agents',
        defaultConfig: { title: 'Agent Chat' }
    });

    registry.register({
        type: 'iframe',
        name: 'IFrame Widget',
        icon: '🌐',
        description: 'Embed external websites',
        defaultConfig: { title: 'Website', url: 'https://example.com' }
    });

    registry.register({
        type: 'markdown',
        name: 'Markdown Note',
        icon: '📝',
        description: 'Rich text notes',
        defaultConfig: { title: 'Notes', content: '# Hello World' }
    });

    registry.register({
        type: 'metrics',
        name: 'Metrics Card',
        icon: '📈',
        description: 'Display single metric',
        defaultConfig: { title: 'Metric', value: 123, label: 'Visitors' }
    });
}
