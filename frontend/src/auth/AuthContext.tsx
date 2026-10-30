import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, onUnauthorized, tokenStore } from "../api/client";
import { Me, TokenOut } from "../api/types";

interface AuthState {
  me: Me | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (body: { organization_name: string; name: string; email: string; password: string }) => Promise<void>;
  logout: () => void;
  can: (perm: string) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => { tokenStore.set(null); setMe(null); }, []);

  useEffect(() => {
    const off = onUnauthorized(logout);
    if (!tokenStore.get()) { setReady(true); return () => { off(); }; }
    api.get<Me>("/auth/me").then(setMe).catch(() => tokenStore.set(null)).finally(() => setReady(true));
    return () => { off(); };
  }, [logout]);

  const accept = (t: TokenOut) => { tokenStore.set(t.access_token); setMe(t.me); };
  const value: AuthState = {
    me, ready, logout,
    login: async (email, password) => accept(await api.post<TokenOut>("/auth/login", { email, password })),
    register: async (body) => accept(await api.post<TokenOut>("/auth/register", body)),
    can: (perm) => !!me?.permissions.includes(perm),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
