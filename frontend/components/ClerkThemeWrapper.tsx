"use client";

import { ClerkProvider } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export default function ClerkThemeWrapper({ children }: { children: React.ReactNode }) {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Before hydration, render with dark (matches defaultTheme in ThemeProvider)
  // to avoid flash. After mount, respect the real theme.
  const baseTheme = !mounted || resolvedTheme === "dark" ? dark : undefined;

  return (
    <ClerkProvider appearance={{ baseTheme }}>
      {children}
    </ClerkProvider>
  );
}
