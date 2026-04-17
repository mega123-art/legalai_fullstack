"use client";

import { useUser } from "@clerk/nextjs";

export interface AppUser {
  id: string;
  name: string;
  email: string;
}

/**
 * Returns the Clerk user mapped to our app shape.
 * Falls back to demo user when Clerk keys aren't configured yet.
 */
export function useCurrentUser(): { user: AppUser; isLoaded: boolean } {
  const { user, isLoaded } = useUser();

  if (!isLoaded) {
    return { user: { id: "", name: "", email: "" }, isLoaded: false };
  }

  if (user) {
    return {
      user: {
        id: user.id,
        name: user.fullName ?? user.firstName ?? "User",
        email: user.primaryEmailAddress?.emailAddress ?? "",
      },
      isLoaded: true,
    };
  }

  // Clerk keys not set — use demo fallback so the app still works locally
  return {
    user: { id: "demo-user", name: "Demo User", email: "demo@legalai.dev" },
    isLoaded: true,
  };
}
