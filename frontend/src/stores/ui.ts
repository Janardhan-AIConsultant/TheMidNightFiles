import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UiState {
  navOpen: boolean;
  setNavOpen: (open: boolean) => void;
  calendarFilters: { platform: string; status: string; genre: string };
  setCalendarFilter: (key: "platform" | "status" | "genre", value: string) => void;
  /** Unsaved editor text per story. Local convenience only; real saves create backend revisions. */
  drafts: Record<string, string>;
  setDraft: (storyId: string, text: string) => void;
  clearDraft: (storyId: string) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      navOpen: false,
      setNavOpen: (navOpen) => set({ navOpen }),
      calendarFilters: { platform: "", status: "", genre: "" },
      setCalendarFilter: (key, value) => set((s) => ({ calendarFilters: { ...s.calendarFilters, [key]: value } })),
      drafts: {},
      setDraft: (storyId, text) => set((s) => ({ drafts: { ...s.drafts, [storyId]: text } })),
      clearDraft: (storyId) =>
        set((s) => {
          const { [storyId]: _removed, ...rest } = s.drafts;
          return { drafts: rest };
        }),
    }),
    { name: "midnight-ui", partialize: (s) => ({ drafts: s.drafts, calendarFilters: s.calendarFilters }) },
  ),
);
