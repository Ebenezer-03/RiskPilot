import type { NextConfig } from "next";

// Bare `npm run dev` (this file's own process) reaches the backend via
// localhost; inside Docker Compose (ticket 15) the two apps are separate
// containers, so BACKEND_URL is overridden there to the backend service's
// Compose hostname (see docker-compose.yml) - same rewrite mechanism,
// different network path.
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // In production on Vercel, Vercel routes /api/* to the FastAPI function
  // directly (see vercel.json) - this rewrite would just add a redundant
  // hop there, so it only runs outside that platform (local dev, Docker
  // Compose's `next start`).
  async rewrites() {
    if (process.env.VERCEL) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
