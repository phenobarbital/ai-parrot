import axios, { AxiosHeaders } from 'axios';
import { browser } from '$app/environment';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:3000',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
});

apiClient.interceptors.request.use(
  (config) => {
    if (browser) {
      const token = localStorage.getItem('token');
      if (token) {
        const headers =
          config.headers instanceof AxiosHeaders
            ? config.headers
            : AxiosHeaders.from(config.headers ?? {});

        headers.set('Authorization', `Bearer ${token}`);
        config.headers = headers;
      }
    }

    return config;
  },
  (error) => Promise.reject(error)
);

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      switch (error.response.status) {
        case 401:
          if (browser) {
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            window.location.href = '/login';
          }
          break;
        case 403:
        case 404:
        case 500:
          break;
        default:
      }
    }

    return Promise.reject(error);
  }
);

export default apiClient;
