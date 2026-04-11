/**
 * Auth API calls. Thin wrappers around the Axios client.
 */
import { api } from "./api";
import { StoredUser, authStorage } from "./authStorage";

interface LoginResponse {
  access: string;
  refresh: string;
  user: StoredUser;
}

export async function login(email: string, password: string): Promise<StoredUser> {
  const { data } = await api.post<LoginResponse>("/auth/login/", { email, password });
  authStorage.setSession(data.access, data.refresh, data.user);
  return data.user;
}

export async function logout(): Promise<void> {
  const refresh = authStorage.getRefresh();
  try {
    if (refresh) {
      await api.post("/auth/logout/", { refresh });
    }
  } catch {
    // Best-effort blacklist; clear locally either way.
  } finally {
    authStorage.clear();
  }
}

export async function fetchCurrentUser(): Promise<StoredUser> {
  const { data } = await api.get<StoredUser>("/auth/me/");
  return data;
}
