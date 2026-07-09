import { create } from "zustand";

type UiState = {
  selectedSymbol: string | null;
  selectedMarket: string | null;
  settingsOpen: null | "columns" | "formations" | "levels" | "densities" | "workspace" | "ai";
  setSelectedSymbol: (symbol: string | null, market?: string | null) => void;
  openSettings: (name: UiState["settingsOpen"]) => void;
  closeSettings: () => void;
};

export const useUiStore = create<UiState>((set) => ({
  selectedSymbol: null,
  selectedMarket: null,
  settingsOpen: null,
  setSelectedSymbol: (selectedSymbol, selectedMarket = null) => set({ selectedSymbol, selectedMarket }),
  openSettings: (settingsOpen) => set({ settingsOpen }),
  closeSettings: () => set({ settingsOpen: null })
}));

