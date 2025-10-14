/**
 * API Client for AI-parrot CrewHandler
 * 
 * This client interfaces with the existing aiohttp-based REST API
 * at /api/v1/crew
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8080';
const API_PATH = '/api/v1/crew';

class CrewAPI {
  constructor(baseUrl = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  /**
   * Create a new crew
   * PUT /api/v1/crew
   */
  async createCrew(crewDefinition) {
    const response = await fetch(`${this.baseUrl}${API_PATH}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(crewDefinition),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Failed to create crew');
    }

    return await response.json();
  }

  /**
   * Upload crew from JSON file
   * POST /api/v1/crew/upload
   */
  async uploadCrew(file) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${this.baseUrl}${API_PATH}/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Failed to upload crew');
    }

    return await response.json();
  }

  /**
   * Get all crews or specific crew by name/id
   * GET /api/v1/crew?name=xxx or ?crew_id=xxx
   */
  async getCrew(identifier = null) {
    let url = `${this.baseUrl}${API_PATH}`;
    
    if (identifier) {
      // Try as name first, then as crew_id
      url += `?name=${encodeURIComponent(identifier)}`;
    }

    const response = await fetch(url);

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Failed to get crew');
    }

    return await response.json();
  }

  /**
   * List all crews
   * GET /api/v1/crew
   */
  async listCrews() {
    return await this.getCrew();
  }

  /**
   * Execute a crew asynchronously
   * POST /api/v1/crew
   */
  async executeCrew(crewId, query, options = {}) {
    const payload = {
      crew_id: crewId,
      query: query,
      user_id: options.user_id,
      session_id: options.session_id,
      synthesis_prompt: options.synthesis_prompt,
      kwargs: options.kwargs || {}
    };

    const response = await fetch(`${this.baseUrl}${API_PATH}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Failed to execute crew');
    }

    return await response.json();
  }

  /**
   * Get job status and results
   * PATCH /api/v1/crew?job_id=xxx
   */
  async getJobStatus(jobId) {
    const response = await fetch(
      `${this.baseUrl}${API_PATH}?job_id=${encodeURIComponent(jobId)}`,
      {
        method: 'PATCH',
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Failed to get job status');
    }

    return await response.json();
  }

  /**
   * Delete a crew
   * DELETE /api/v1/crew?name=xxx or ?crew_id=xxx
   */
  async deleteCrew(identifier) {
    const response = await fetch(
      `${this.baseUrl}${API_PATH}?name=${encodeURIComponent(identifier)}`,
      {
        method: 'DELETE',
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Failed to delete crew');
    }

    return await response.json();
  }

  /**
   * Poll job status until completion
   */
  async pollJobUntilComplete(jobId, intervalMs = 1000, maxAttempts = 300) {
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const status = await this.getJobStatus(jobId);
      
      if (status.status === 'completed' || status.status === 'failed') {
        return status;
      }

      await new Promise(resolve => setTimeout(resolve, intervalMs));
    }

    throw new Error('Job polling timeout');
  }
}

export default new CrewAPI();
