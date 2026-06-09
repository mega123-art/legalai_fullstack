import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",

  // Fix: Proxy all /api/* calls through Next.js to avoid browser CORS issues.
  // The browser always calls the same origin (legalai-fullstack.vercel.app/api/*),
  // and Vercel rewrites them server-side to the backend URL.
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
