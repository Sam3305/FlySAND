import { create } from "zustand";
import type { AuthState } from "../types";
import { AOCC_CREDENTIALS } from "../constants";

export const useAuthStore = create<AuthState>((set) => ({
  authenticated: false,
  operatorId: null,

  login: async (user: string, pass: string): Promise<boolean> => {
    // Simulate network latency — replace with real POST /auth/token
    await new Promise((r) => setTimeout(r, 900));

    const valid =
      user === AOCC_CREDENTIALS.user && pass === AOCC_CREDENTIALS.pass;

    if (valid) {
      set({ authenticated: true, operatorId: user });
    }

    return valid;
  },

  logout: () => set({ authenticated: false, operatorId: null }),
}));
