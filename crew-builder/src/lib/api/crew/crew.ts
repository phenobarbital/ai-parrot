import apiClient from '../client';

const API_PATH = '/api/v1/crew';

export type CrewExecutionMode = 'sequential' | 'parallel' | 'loop' | 'flow';

export interface CrewDefinition {
  name: string;
  description: string;
  execution_mode: CrewExecutionMode;
  agents: unknown[];
}

export interface GetCrewParams {
  name?: string;
  crew_id?: string;
}

export async function createCrew(crewDefinition: CrewDefinition) {
  const { data } = await apiClient.put(API_PATH, crewDefinition);
  return data;
}

export async function uploadCrew(file: File) {
  const formData = new FormData();
  formData.append('file', file);

  const { data } = await apiClient.post(`${API_PATH}/upload`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  });

  return data;
}

export async function getCrew(params?: GetCrewParams | string) {
  let query: GetCrewParams | undefined;

  if (typeof params === 'string') {
    query = { name: params };
  } else if (params && (params.name || params.crew_id)) {
    query = params;
  }

  const { data } = await apiClient.get(API_PATH, { params: query });
  return data;
}

export async function listCrews() {
  return getCrew();
}

export async function getCrewById(crewId: string) {
  return getCrew({ crew_id: crewId });
}

export interface ExecuteCrewOptions {
  user_id?: string;
  session_id?: string;
  synthesis_prompt?: string;
  kwargs?: Record<string, unknown>;
  execution_mode?: CrewExecutionMode;
}

export async function executeCrew(
  crewId: string,
  query: string | Record<string, unknown>,
  options: ExecuteCrewOptions = {}
) {
  const payload: {
    crew_id: string;
    query: string | Record<string, unknown>;
    user_id?: string;
    session_id?: string;
    synthesis_prompt?: string;
    kwargs: Record<string, unknown>;
    execution_mode?: CrewExecutionMode;
  } = {
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

  const { data } = await apiClient.post(API_PATH, payload);
  return data;
}

export async function getJobStatus(jobId: string) {
  const { data } = await apiClient.patch(API_PATH, undefined, {
    params: { job_id: jobId }
  });
  return data;
}

export async function deleteCrew(identifier: string) {
  const { data } = await apiClient.delete(API_PATH, {
    params: { name: identifier }
  });
  return data;
}

export async function pollJobUntilComplete(
  jobId: string,
  intervalMs = 1000,
  maxAttempts = 300
) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const status = await getJobStatus(jobId);
    if (status.status === 'completed' || status.status === 'failed') {
      return status;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error('Job polling timeout');
}

export const crew = {
  createCrew,
  uploadCrew,
  getCrew,
  getCrewById,
  listCrews,
  executeCrew,
  getJobStatus,
  deleteCrew,
  pollJobUntilComplete
};
