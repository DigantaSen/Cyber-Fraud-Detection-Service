import axios from 'axios';
import { useAuthStore } from '../store/authStore';

const apiClient = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT from auth store to every request
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  config.headers['X-Correlation-ID'] = crypto.randomUUID();
  return config;
});

// Handle 401 — clear auth and redirect to login
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().clearAuth();
    }
    return Promise.reject(error);
  }
);

export default apiClient;
