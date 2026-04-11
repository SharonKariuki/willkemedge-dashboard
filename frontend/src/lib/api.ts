/**
 * Axios instance with JWT auth + automatic refresh on 401.
 *
 * Refresh strategy:
 * - On 401, try POST /auth/refresh/ once with the stored refresh token.
 * - If refresh succeeds, update the access token and retry the original request.
 * - If refresh fails, clear the session and redirect to /login.
 * - Concurrent 401s share a single in-flight refresh promise so we only
 *   ever issue one refresh call per expiry window.
 */
import axios, {
  AxiosError,
  AxiosInstance,
  InternalAxiosRequestConfig,
} from "axios";

import { authStorage } from "./authStorage";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export const api: AxiosInstance = axios.create({
  baseURL,
  withCredentials: false,
  timeout: 10_000,
});

// ----- Request interceptor: attach access token --------------------------
api.interceptors.request.use((config) => {
  const access = authStorage.getAccess();
  if (access && config.headers) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

// ----- Response interceptor: refresh on 401 ------------------------------
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refresh = authStorage.getRefresh();
  if (!refresh) return null;

  try {
    const { data } = await axios.post<{ access: string }>(
      `${baseURL}/auth/refresh/`,
      { refresh }
    );
    authStorage.setAccess(data.access);
    return data.access;
  } catch {
    authStorage.clear();
    return null;
  }
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined;
    const isAuthEndpoint = original?.url?.includes("/auth/");

    if (
      error.response?.status === 401 &&
      original &&
      !original._retried &&
      !isAuthEndpoint
    ) {
      original._retried = true;

      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
      }
      const newAccess = await refreshPromise;

      if (newAccess) {
        original.headers.Authorization = `Bearer ${newAccess}`;
        return api.request(original);
      }

      // Refresh failed — bounce to login.
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }

    return Promise.reject(error);
  }
);
