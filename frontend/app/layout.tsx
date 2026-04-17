import type { Metadata } from "next";
import { EB_Garamond, Lato } from "next/font/google";
import ThemeProvider from "@/components/ThemeProvider";
import ClerkThemeWrapper from "@/components/ClerkThemeWrapper";
import "./globals.css";

const ebGaramond = EB_Garamond({
  variable: "--font-heading",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const lato = Lato({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["300", "400", "700"],
});

export const metadata: Metadata = {
  title: "LegalAI — Indian Legal Research",
  description: "Search 18,000+ Supreme Court judgments in plain English",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${ebGaramond.variable} ${lato.variable} h-full antialiased`}
    >
      <body className="h-full bg-surface-base text-fg-default font-sans">
        <ThemeProvider>
          <ClerkThemeWrapper>{children}</ClerkThemeWrapper>
        </ThemeProvider>
      </body>
    </html>
  );
}
