import api from '$lib/api/http';

export const crew = {
    listCrews: () => api.get('/api/v1/crew').then((res) => res.data),
    getCrewById: (id: string) => api.get(`/api/v1/crew/${id}`).then((res) => res.data),
    createCrew: (crewData: any) => api.put('/api/v1/crew', crewData).then((res) => res.data),
    updateCrew: (id: string, crewData: any) => api.post(`/api/v1/crew/${id}`, crewData).then((res) => res.data),
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
        return api.post('/api/v1/crew', payload).then((res) => res.data);
    },
    getJobStatus: (jobId: string) =>
        api.patch('/api/v1/crew', undefined, { params: { job_id: jobId } }).then((res) => res.data),
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
