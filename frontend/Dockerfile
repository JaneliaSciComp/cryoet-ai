# syntax=docker/dockerfile:1.7
# TanStack Start SSR app. Build context: frontend/.
#
# `npm run build` produces dist/client (static assets) and dist/server/server.js
# (a fetch handler exported as default). srvx wraps that handler in an HTTP
# server and serves dist/client as static files.

FROM node:24-bookworm-slim AS base
WORKDIR /app
ENV NODE_ENV=production

# All deps (incl. dev) so we can build.
FROM base AS deps
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --include=dev

# Strip dev deps for the runtime image. srvx is transitive of @tanstack/react-start,
# so it survives the prune and is available via `npx srvx`.
FROM base AS production-deps
COPY package.json package-lock.json ./
COPY --from=deps /app/node_modules ./node_modules
RUN npm prune --omit=dev

FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS runtime
COPY --from=production-deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./

ENV PORT=3000
EXPOSE 3000

CMD ["npm", "run", "start"]
