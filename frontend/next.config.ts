import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // Next's dev-only "instant navigation" check looks at every page by default. All our pages sit behind the login
  // gate (the page only renders once we know who the user is), so the check can't see them and reports "dropped
  // segment". 'manual-warning' = only check pages that opt in with `export const instant`; none do.
  experimental: {
    instantInsights: { validationLevel: "manual-warning" },
  },
  // Production without a shared domain (e.g. frontend on vercel.app, backend on fly.dev): the browser talks to
  // THIS site at /api/... and Next forwards it to the backend (set BACKEND_URL). The login cookie then belongs to this
  // site, so it works without a custom domain. Locally BACKEND_URL is not set and the browser calls the backend directly.
  async rewrites() {
    const backend = (process.env.BACKEND_URL || "").trim().replace(/\/$/, "");
    return backend ? [{ source: "/api/:path*", destination: `${backend}/api/:path*` }] : [];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
