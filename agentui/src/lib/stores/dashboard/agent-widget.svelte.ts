import { Widget, type WidgetConfig } from './widget.svelte';

export interface AgentMessageData {
    content: string;
    output_mode?: string;
    data?: any;
    code?: string;
    tool_calls?: any[];
}

export interface AgentWidgetConfig extends WidgetConfig {
    message: AgentMessageData;
}

export class AgentWidget extends Widget {
    message: AgentMessageData = $state({ content: '' });

    constructor(config: AgentWidgetConfig) {
        super({ ...config, type: 'agent-response' });
        this.message = config.message;
    }

    // Agent specific actions
    updateMessage(newMessage: AgentMessageData) {
        this.message = newMessage;
    }
}
