"use client";

import {
  InMemoryWebStorage,
  User,
  UserManager,
  WebStorageStateStore,
} from "oidc-client-ts";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { setAccessTokenProvider } from "@/lib/api/client";

type AuthState = {
  ready: boolean;
  authenticated: boolean;
  development: boolean;
  subject?: string;
  error?: string;
  login: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);
let manager: UserManager | null = null;

export function getOidcManager(): UserManager {
  if (manager) return manager;
  const authority = process.env.NEXT_PUBLIC_OIDC_AUTHORITY;
  const clientId = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID;
  if (!authority || !clientId) {
    throw new Error("OIDC 模式需要 NEXT_PUBLIC_OIDC_AUTHORITY 和 NEXT_PUBLIC_OIDC_CLIENT_ID");
  }
  manager = new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: `${window.location.origin}/auth/popup-callback`,
    post_logout_redirect_uri: window.location.origin,
    response_type: "code",
    scope: process.env.NEXT_PUBLIC_OIDC_SCOPE ?? "openid profile",
    loadUserInfo: false,
    automaticSilentRenew: false,
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
  return manager;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const mode = process.env.NEXT_PUBLIC_AUTH_MODE;
  const development = mode === "development";
  const [ready, setReady] = useState(development);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (development) {
      setAccessTokenProvider(async () => null);
      return;
    }
    if (mode !== "oidc") {
      setError("NEXT_PUBLIC_AUTH_MODE 必须显式设为 development 或 oidc");
      setReady(true);
      return;
    }
    let oidc: UserManager;
    try {
      oidc = getOidcManager();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "OIDC 配置无效");
      setReady(true);
      return;
    }
    const loaded = (next: User) => setUser(next.expired ? null : next);
    const unloaded = () => setUser(null);
    oidc.events.addUserLoaded(loaded);
    oidc.events.addUserUnloaded(unloaded);
    oidc.events.addAccessTokenExpired(unloaded);
    setAccessTokenProvider(async () => {
      const current = await oidc.getUser();
      return current && !current.expired ? current.access_token : null;
    });
    oidc.getUser()
      .then((current) => setUser(current && !current.expired ? current : null))
      .catch(() => setUser(null))
      .finally(() => setReady(true));
    return () => {
      oidc.events.removeUserLoaded(loaded);
      oidc.events.removeUserUnloaded(unloaded);
      oidc.events.removeAccessTokenExpired(unloaded);
    };
  }, [development, mode]);

  const value = useMemo<AuthState>(
    () => ({
      ready,
      authenticated: development || Boolean(user && !user.expired),
      development,
      subject: user?.profile.sub,
      error,
      login: async () => {
        setError(undefined);
        await getOidcManager().signinPopup();
      },
      logout: async () => {
        const oidc = getOidcManager();
        try {
          await oidc.signoutRedirect();
        } catch {
          await oidc.removeUser();
          setUser(null);
        }
      },
    }),
    [development, error, ready, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
