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
