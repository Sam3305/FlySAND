import { create } from "zustand";
import type { AppView } from "../types";

interface NavState {
  view: AppView;
  setView: (v: AppView) => void;
}

export const useNavStore = create<NavState>((set) => ({
  view: "b2c",
  setView: (view) => set({ view }),
}));
