import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  // Surface the control plane URL to the client only when needed; most
  // server-side work stays on Next.js API routes.
  env: {
    NEXT_PUBLIC_CONTROL_PLANE_URL: process.env.NEXT_PUBLIC_CONTROL_PLANE_URL ?? "http://localhost:8000",
  },
};

export default config;
