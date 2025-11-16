import axios from 'axios';
import { config } from '$lib/config';

const apiClient = axios.create({
  baseURL: config.apiBaseUrl,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
});

apiClient.interceptors.request.use((config) => {
  if (typeof window === 'undefined') {
    return config;
  }

  const token = localStorage.getItem(config.tokenStorageKey);
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default apiClient;
