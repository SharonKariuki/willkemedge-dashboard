/**
 * Token storage layer.
 *
 * Tokens live in localStorage for v1 (single-owner dashboard, low XSS surface
 * because we control all rendered content). If/when we add tenant-facing
 * surfaces we should move refresh tokens to httpOnly cookies.
 */
const ACCESS_KEY = "wk_access";
const REFRESH_KEY = "wk_refresh";
const USER_KEY = "wk_user";

export interface StoredUser {
  id: number;
  email: string;
  username: string;
}

export const authStorage = {
  getAccess(): string | null {
    return localStorage.getItem(ACCESS_KEY);
  },
  getRefresh(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  },
  getUser(): StoredUser | null {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as StoredUser) : null;
  },
  setSession(access: string, refresh: string, user: StoredUser) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  setAccess(access: string) {
    localStorage.setItem(ACCESS_KEY, access);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  },
};
