# Meter dashboard — Next.js standalone, for Fly.
#
# Multi-stage on purpose: the build needs devDependencies and the full source, the
# runtime needs neither. The final image carries `.next/standalone` (a minimal server
# plus only the traced node_modules), the static assets, and nothing else.
#
# The dashboard reads the same Postgres the proxy writes. It is a *reader* — it opens no
# write path — so it is safe to run it anywhere the database is reachable. Point
# DATABASE_URL at Supabase's TRANSACTION pooler here, not the session one: this app is
# many short-lived request handlers, which is the shape transaction pooling exists for.

FROM node:22-alpine AS deps
WORKDIR /app
# Only the manifests, so this layer caches until dependencies actually change.
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Next collects telemetry on build by default; a CI/image build is not a useful signal
# and it costs a network call in a sandbox that may not have one.
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root. The dashboard only ever reads the ledger, so there is no reason for its
# process to be able to write anything in the image either.
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
# These two are NOT included in `standalone` — the docs assume a CDN serves them. On Fly
# there is no CDN in front, so `server.js` has to serve them itself, which it does only
# if they are placed here. Omitting them yields a running app with no CSS and no images.
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

# `server.js` is emitted by the standalone build, not written by us.
CMD ["node", "server.js"]
