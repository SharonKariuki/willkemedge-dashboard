/**
 * Auth context — exposes the current user and login/logout actions.
 *
 * On mount, if a token exists in storage we hit /auth/me/ to validate it.
 * If that fails the storage is cleared so the next render bounces to login.
 */
import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { fetchCurrentUser, login as apiLogin, logout as apiLogout } from "@/lib/auth";
import { StoredUser, authStorage } from "@/lib/authStorage";

interface AuthContextValue {
  user: StoredUser | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<StoredUser | null>(() => authStorage.getUser());
  const [isLoading, setIsLoading] = useState<boolean>(() => Boolean(authStorage.getAccess()));

  useEffect(() => {
    if (!authStorage.getAccess()) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    fetchCurrentUser()
      .then((current) => {
        if (!cancelled) setUser(current);
      })
      .catch(() => {
        if (!cancelled) {
          authStorage.clear();
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const next = await apiLogin(email, password);
    setUser(next);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
