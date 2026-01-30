import axios from 'axios';
import { browser } from '$app/environment';
import { config } from '$lib/config';

const apiClient = axios.create({
  baseURL: config.apiBaseUrl,
  timeout: 120000, // 2 minutes - agent queries can take a while
  withCredentials: config.apiWithCredentials,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Request interceptor - add authorization token
apiClient.interceptors.request.use(
  (requestConfig) => {
    if (browser) {
      const storedData = localStorage.getItem(config.tokenStorageKey);
      if (storedData) {
        try {
          const parsed = JSON.parse(storedData);
          const token = parsed?.token || storedData; // fallback to raw value if not JSON
          if (token) {
            requestConfig.headers.Authorization = `Bearer ${token}`;
          }
        } catch {
          // If parse fails, use raw value (legacy format)
          requestConfig.headers.Authorization = `Bearer ${storedData}`;
        }
      }
    }
    return requestConfig;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor - handle common error scenarios
apiClient.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    if (error.response) {
      switch (error.response.status) {
        case 401:
          // Unauthorized - clear token and redirect to login
          if (browser) {
            localStorage.removeItem(config.tokenStorageKey);
            window.location.href = '/login';
          }
          break;
        case 403:
          // Forbidden - could add notification here
          console.warn('Access forbidden:', error.response.data);
          break;
        case 404:
          // Not found - could add notification here
          console.warn('Resource not found:', error.response.data);
          break;
        case 500:
          // Server error - could add notification here
          console.error('Server error:', error.response.data);
          break;
        default:
          // Other errors
          console.error('API error:', error.response.status, error.response.data);
      }
    } else if (error.request) {
      // Request made but no response received
      console.error('No response received:', error.request);
    } else {
      // Error setting up the request
      console.error('Request setup error:', error.message);
    }
    return Promise.reject(error);
  }
);

export default apiClient;
