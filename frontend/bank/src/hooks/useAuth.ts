import { useState, useEffect, useCallback } from 'react';

export interface AuthUser {
  userId: string;
  email: string;
  role: string;
  jurisdictionId: string | null;
}

const TOKEN_KEY = 'bank_access_token';
const REFRESH_KEY = 'bank_refresh_token';
const USER_KEY = 'bank_user';

export function useAuth() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<AuthUser | null>(() => {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const json = await res.json();

      if (!res.ok) {
        const msg = json?.detail?.message ?? json?.detail ?? 'Login failed';
        throw new Error(msg);
      }

      const data = json.data;

      // MFA required
      if (data?.mfa_required) {
        throw new Error('MFA is required. Please contact your administrator to disable MFA for this account.');
      }

      const accessToken: string = data?.access_token;
      const refreshToken: string = data?.refresh_token;

      if (!accessToken) throw new Error('No access token returned');

      // Decode JWT payload (no verification needed — Kong already verified)
      const [, payloadB64] = accessToken.split('.');
      const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

      if (payload.role !== 'BANK_OFFICIAL') {
        throw new Error(`Access denied. This portal requires the BANK_OFFICIAL role, but your account has the '${payload.role}' role.`);
      }

      const authUser: AuthUser = {
        userId: payload.sub,
        email: payload.email,
        role: payload.role,
        jurisdictionId: payload.jurisdictionId ?? null,
      };

      localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
      localStorage.setItem(USER_KEY, JSON.stringify(authUser));

      setToken(accessToken);
      setUser(authUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  }, []);

  // Auto-logout if token is expired
  useEffect(() => {
    if (!token) return;
    try {
      const [, payloadB64] = token.split('.');
      const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));
      const expiresIn = payload.exp * 1000 - Date.now();
      if (expiresIn <= 0) {
        logout();
        return;
      }
      const timer = setTimeout(logout, expiresIn);
      return () => clearTimeout(timer);
    } catch {
      logout();
    }
  }, [token, logout]);

  return { token, user, loading, error, login, logout };
}
