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
  // Only when building the container. Vercel builds and serves Next itself and wants the
  // default output; forcing `standalone` there is at best redundant. Set DOCKER_BUILD=1
  // (the Dockerfile does) to get the self-contained server instead.
  output: process.env.DOCKER_BUILD ? "standalone" : undefined,

  // `X-Powered-By: Next.js` tells an attacker which CVE list to start from and buys us
  // nothing. Off.
  poweredByHeader: false,

  // Security headers. Per `node_modules/next/dist/docs/01-app/03-api-reference/05-config/
  // 01-next-config-js/headers.md`, `headers()` may be sync or async and returns
  // `{source, headers[]}`; `/:path*` applies to every route including `/api/*`.
  //
  // ponytail: no script-src CSP. The documented way to get one in this version
  // (01-app/02-guides/content-security-policy.md) is a per-request nonce issued from a
  // `proxy.ts`, and the doc is explicit that nonces "must use dynamic rendering" — which
  // would convert `/` and `/how-it-works` from prerendered static to server-rendered on
  // every hit, to protect two pages that render no user-supplied HTML. `frame-ancestors`
  // is included below because it is the one CSP directive that costs nothing here.
  // Upgrade path when the console starts rendering untrusted content: add `proxy.ts` with
  // the nonce pattern from that guide and move script-src/style-src into this same header.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // Clickjacking. `frame-ancestors` is the modern control and covers browsers that
          // ignore X-Frame-Options; both are sent because they are cheap.
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          { key: "X-Frame-Options", value: "DENY" },
          // Stops a JSON ledger response being sniffed into something executable.
          { key: "X-Content-Type-Options", value: "nosniff" },
          // A judge session token rides in the URL of nothing, but referrers leak paths —
          // and `/try` paths name a project id. Origin-only on cross-origin navigation.
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // This app asks for none of these. Denying them means an injected script cannot
          // either.
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          // Vercel serves HTTPS only, so this costs nothing and closes the first-visit
          // downgrade window. No `preload` — that is a one-way door for the apex domain
          // and is the owner's call, not a config default.
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
