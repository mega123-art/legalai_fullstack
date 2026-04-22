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

  // No authenticated user — treat as not loaded to force auth redirect
  return { user: { id: "", name: "", email: "" }, isLoaded: false };
}
