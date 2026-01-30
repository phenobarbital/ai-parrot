
export interface AgentChatRequest {
    query: string;
    session_id?: string;
    [key: string]: any; // Allow for extra properties if needed
}

export interface AgentMetadata {
    model: string;
    provider: string;
    session_id: string;
    turn_id: string;
    response_time?: number | null;
    is_error?: boolean;
}

export interface AgentToolCall {
    name: string;
    status: string;
    output: any;
    arguments: any;
}

export interface AgentChatResponse {
    input: string;
    output: string;
    data: any | null;
    response: string; // Markdown
    output_mode: 'default' | 'json' | string;
    code: string | null;
    metadata: AgentMetadata;
    sources: any[];
    tool_calls: AgentToolCall[];
}

export interface AgentMessage {
    id: string; // generated UUID or turn_id
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
    metadata?: AgentMetadata;
    data?: any;
    code?: string | null;
    output?: any; // For structured output (like ECharts JSON)
    tool_calls?: AgentToolCall[];
    output_mode?: string;
    htmlResponse?: string | null; // Full HTML response for iframe rendering
}

export interface AgentConversation {
    id: string; // session_id
    title: string;
    created_at: Date;
    updated_at: Date;
    agent_name: string;
    last_message?: string;
}
