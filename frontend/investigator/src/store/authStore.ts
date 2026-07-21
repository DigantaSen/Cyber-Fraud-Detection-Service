import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  accessToken: string | null;
  userId: string | null;
  role: string | null;
  isAuthenticated: boolean;
  setTokens: (accessToken: string, userId: string, role: string) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      userId: null,
      role: null,
      isAuthenticated: false,
      setTokens: (accessToken, userId, role) =>
        set({ accessToken, userId, role, isAuthenticated: true }),
      clearAuth: () =>
        set({ accessToken: null, userId: null, role: null, isAuthenticated: false }),
    }),
    { name: 'investigator-auth' }
  )
);
