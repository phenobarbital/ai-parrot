/**
 * AgentWidget wrapper - bridges old import paths to new dashboard library.
 * AgentWidget is a specialized Widget for displaying agent responses.
 */
import { Widget, type WidgetConfig } from '$lib/dashboard/domain/widget.svelte.js';

export interface AgentMessage {
    content: string;
    output_mode: 'html' | 'markdown' | 'text';
    data?: unknown;
    code?: string;
    tool_calls?: unknown[];
}

export interface AgentWidgetConfig {
    id?: string;
    title: string;
    type: string;
    message?: AgentMessage;
    position?: { x: number; y: number; w: number; h: number };
}

export class AgentWidget extends Widget {
    message = $state<AgentMessage | null>(null);
    widgetType: string;

    constructor(config: AgentWidgetConfig) {
        const widgetConfig: WidgetConfig = {
            id: config.id,
            title: config.title,
            icon: '🤖',
        };
        super(widgetConfig);

        this.widgetType = config.type;

        if (config.message) {
            this.message = config.message;
        }
    }

    updateMessage(message: Partial<AgentMessage>): void {
        this.message = {
            content: message.content ?? this.message?.content ?? '',
            output_mode: message.output_mode ?? this.message?.output_mode ?? 'markdown',
            data: message.data ?? this.message?.data,
            code: message.code ?? this.message?.code,
            tool_calls: message.tool_calls ?? this.message?.tool_calls,
        };
    }
}
