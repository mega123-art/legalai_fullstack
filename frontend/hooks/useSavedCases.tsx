"use client";

import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";
import { getSavedCases, saveCase as apiSaveCase, unsaveCase as apiUnsaveCase } from "@/lib/api";

interface SavedCasesState {
  savedIds: Set<string>;
  isSaved: (case_id: string) => boolean;
  toggle: (args: { case_id: string; citation: string; title: string }) => Promise<void>;
  loaded: boolean;
}

const Ctx = createContext<SavedCasesState | null>(null);

export function SavedCasesProvider({
  userId,
  children,
}: {
  userId: string;
  children: ReactNode;
}) {
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!userId) return;
    getSavedCases(userId)
      .then((r) => setSavedIds(new Set(r.cases.map((c) => c.case_id))))
      .catch(console.error)
      .finally(() => setLoaded(true));
  }, [userId]);

  const isSaved = useCallback((case_id: string) => savedIds.has(case_id), [savedIds]);

  const toggle = useCallback(
    async ({ case_id, citation, title }: { case_id: string; citation: string; title: string }) => {
      const currentlySaved = savedIds.has(case_id);
      // Optimistic
      setSavedIds((prev) => {
        const next = new Set(prev);
        if (currentlySaved) next.delete(case_id);
        else next.add(case_id);
        return next;
      });
      try {
        if (currentlySaved) {
          await apiUnsaveCase(userId, case_id);
        } else {
          await apiSaveCase({ user_id: userId, case_id, citation, title });
        }
      } catch (e) {
        // Rollback
        setSavedIds((prev) => {
          const next = new Set(prev);
          if (currentlySaved) next.add(case_id);
          else next.delete(case_id);
          return next;
        });
        console.error(e);
      }
    },
    [savedIds, userId]
  );

  return (
    <Ctx.Provider value={{ savedIds, isSaved, toggle, loaded }}>{children}</Ctx.Provider>
  );
}

export function useSavedCases(): SavedCasesState {
  const ctx = useContext(Ctx);
  if (!ctx) {
    // Fallback no-op when provider missing (e.g. empty chat page)
    return {
      savedIds: new Set(),
      isSaved: () => false,
      toggle: async () => {},
      loaded: false,
    };
  }
  return ctx;
}
