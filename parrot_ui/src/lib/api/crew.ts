import api from '$lib/api/http';

export const crew = {
    listCrews: () => api.get('/api/v1/crew').then((res) => res.data),
    getCrewById: (id: string) => api.get(`/api/v1/crew/${id}`).then((res) => res.data),
    createCrew: (crewData: any) => api.put('/api/v1/crew', crewData).then((res) => res.data),
    updateCrew: (id: string, crewData: any) => api.put(`/api/v1/crew/${id}`, crewData).then((res) => res.data),
    deleteCrew: (id: string) => api.delete(`/api/v1/crew/${id}`).then((res) => res.data),
    executeCrew: (crewId: string, query: string, options: any = {}) => {
        const payload: any = {
            crew_id: crewId,
            query,
            user_id: options.user_id,
            session_id: options.session_id,
            synthesis_prompt: options.synthesis_prompt,
            kwargs: options.kwargs ?? {}
        };
        if (options.execution_mode) {
            payload.execution_mode = options.execution_mode;
        }
        return api.post('/api/v1/crews', payload).then((res) => res.data);
    },
    getJobStatus: (jobId: string) =>
        api.patch('/api/v1/crews', { job_id: jobId }).then((res) => res.data),

    listActiveJobs: () => api.get('/api/v1/crews', { params: { mode: 'active_jobs' } }).then((res) => res.data),

    listCompletedJobs: () => api.get('/api/v1/crews', { params: { mode: 'completed_jobs' } }).then((res) => res.data),

    // New methods for Crew Execution Wizard
    getAgentStatuses: (jobId: string, crewId: string) => {
        if (!jobId || jobId === 'null' || jobId === 'undefined') {
            throw new Error(`Invalid Job ID: ${jobId}`);
        }
        return api.get(`/api/v1/crews/${jobId}/${crewId}`).then((res) => {
            // Helper: ensure we return a list if the API returns a dict of statuses
            if (res.data && typeof res.data === 'object' && !Array.isArray(res.data)) {
                // If API returns { agent_id: { status: ... }, ... }
                // or { agents: [...] }
                if (res.data.agents && Array.isArray(res.data.agents)) {
                    // Support legacy/wrapper format just in case
                    return res.data.agents;
                }
                // Convert dict to array if it is a dict of statuses
                return Object.values(res.data);
            }
            return res.data;
        });
    },

    getAgentResult: (jobId: string, crewId: string, agentId: string) => {
        if (!jobId || jobId === "null" || jobId === "undefined") {
            throw new Error("Invalid Job ID");
        }
        return api.get(`/api/v1/crews/${jobId}/${crewId}/${agentId}`).then((res) => res.data);
    },

    askCrew: (jobId: string, crewId: string, question: string) =>
        api.post(`/api/v1/crews/${jobId}/${crewId}/ask`, { question }).then((res) => res.data),

    summaryCrew: (jobId: string, crewId: string, mode: 'full_report' | 'executive_summary' = 'executive_summary', prompt?: string) =>
        api.post(`/api/v1/crews/${jobId}/${crewId}/summary`, { mode, summary_prompt: prompt }).then((res) => res.data),


    pollJobUntilComplete: async (jobId: string, intervalMs = 1000, maxAttempts = 300) => {
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
            const status = await crew.getJobStatus(jobId);
            if (status.status === 'completed' || status.status === 'failed') {
                return status;
            }
            await new Promise((resolve) => setTimeout(resolve, intervalMs));
        }
        throw new Error('Job polling timeout');
    }
};
