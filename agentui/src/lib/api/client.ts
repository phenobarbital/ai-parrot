
import { PUBLIC_API_ENDPOINT } from '$env/static/public';

export interface ChatRequest {
    query: string;
    session_id?: string;
    // support extra arbitrary data
    [key: string]: any;
}

export interface ChatResponse {
    input: string;
    output: string;
    data: any | null;
    response: string;
    output_mode: 'default' | 'json' | 'html' | 'image' | 'echarts' | 'vega';
    code: string | null;
    metadata: {
        model?: string;
        provider?: string;
        session_id?: string;
        turn_id?: string;
        response_time?: number;
        [key: string]: any;
    };
    sources: any[];
    tool_calls: any[];
}

export class AgentClient {
    private baseUrl: string;

    constructor(baseUrl?: string) {
        this.baseUrl = baseUrl || PUBLIC_API_ENDPOINT || 'http://localhost:5000';
    }

    async chat(agentName: string, payload: ChatRequest, methodName?: string): Promise<ChatResponse> {
        const path = methodName
            ? `/api/v1/agents/chat/${agentName}/${methodName}`
            : `/api/v1/agents/chat/${agentName}`;

        const url = `${this.baseUrl}${path}`;

        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const errorText = await res.text();
                throw new Error(`API Error ${res.status}: ${errorText}`);
            }

            return await res.json();
        } catch (error) {
            console.error('Agent Chat Error:', error);
            throw error;
        }
    }
}

export const agentClient = new AgentClient();
