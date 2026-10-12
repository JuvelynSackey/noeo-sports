import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Cache Components (PPR + "use cache") is built for mixing static and
  // dynamic content within a route. Every page in this app is a
  // client-rendered view behind client-side JWT auth with no static shell
  // to speak of, so it's off here rather than fought with per-route
  // "instant = false"/Suspense workarounds that wouldn't buy anything.
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
