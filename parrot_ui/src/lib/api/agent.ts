
import apiClient from './http';
import type { AgentChatRequest, AgentChatResponse } from '$lib/types/agent';

const BASE_PATH = '/api/v1/agents/chat';

export const chatWithAgent = async (
    agentName: string,
    request: AgentChatRequest
): Promise<AgentChatResponse> => {
    const response = await apiClient.post<AgentChatResponse>(
        `${BASE_PATH}/${agentName}`,
        { ...request, output_format: 'json' }
    );
    return response.data;
};

export const callAgentMethod = async (
    agentName: string,
    methodName: string,
    request: AgentChatRequest
): Promise<AgentChatResponse> => {
    const response = await apiClient.post<AgentChatResponse>(
        `${BASE_PATH}/${agentName}/${methodName}`,
        { ...request, output_format: 'json' }
    );
    return response.data;
};

export const refreshAgentData = async (
    agentName: string
): Promise<any> => {
    const response = await apiClient.patch(
        `${BASE_PATH}/${agentName}`
    );
    return response.data;
};

export const uploadAgentData = async (
    agentName: string,
    formData: FormData
): Promise<any> => {
    const response = await apiClient.put(
        `${BASE_PATH}/${agentName}`,
        formData,
        {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        }
    );
    return response.data;
};

export const addAgentQuery = async (
    agentName: string,
    slug: string
): Promise<any> => {
    const response = await apiClient.put(
        `${BASE_PATH}/${agentName}`,
        { slug }
    );
    return response.data;
};

// Handle file uploads if needed, usually requires multipart/form-data
// But the current spec implies simply passing text/data. 
// If file upload is needed, we might need a separate endpoint or convert to base64.
// For now, assuming standard JSON payload as per spec. 
