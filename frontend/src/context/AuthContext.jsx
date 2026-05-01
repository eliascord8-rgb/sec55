import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const token = () => localStorage.getItem("bs_user_token");

  const setAuth = useCallback((t, u) => {
    if (t) localStorage.setItem("bs_user_token", t);
    setUser(u);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("bs_user_token");
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    const t = token();
    if (!t) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const r = await api.get("/auth/me", { headers: { Authorization: `Bearer ${t}` } });
      setUser(r.data.user);
    } catch {
      localStorage.removeItem("bs_user_token");
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const authedApi = useCallback(() => {
    const t = token();
    return {
      get: (path, opts = {}) =>
        api.get(path, { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${t}` } }),
      post: (path, data, opts = {}) =>
        api.post(path, data, { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${t}` } }),
    };
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, setAuth, logout, refresh, authedApi }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
