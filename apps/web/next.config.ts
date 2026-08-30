import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // In production, Vercel routes /api/* to the FastAPI function directly
  // (see vercel.json). In local dev, Next.js's dev server has to proxy
  // the same path to the separately-running uvicorn process so the app
  // behaves identically in both environments.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
