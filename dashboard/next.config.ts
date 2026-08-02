import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits `.next/standalone` with a minimal `server.js` and only the `node_modules` the
  // build actually traced. That is what makes the container small enough to be worth
  // deploying — without it the image carries the whole dependency tree.
  //
  // Two consequences the Dockerfile has to honour, both from
  // `node_modules/next/dist/docs/.../01-next-config-js/output.md`: `server.js` does NOT
  // copy `public/` or `.next/static/` itself (they are assumed to be on a CDN), so the
  // image copies them in explicitly — miss that and the app boots and serves unstyled
  // HTML with no assets, which looks like a CSS bug rather than a packaging one. And it
  // reads `PORT` / `HOSTNAME` from the environment, which is how it binds 0.0.0.0.
  output: "standalone",
};

export default nextConfig;
