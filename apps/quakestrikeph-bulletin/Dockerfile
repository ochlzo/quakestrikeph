FROM node:24.21.0-bookworm-slim AS build
WORKDIR /app

RUN npm install -g pnpm@11.11.0
COPY apps/quakestrikeph-bulletin/package.json apps/quakestrikeph-bulletin/pnpm-lock.yaml apps/quakestrikeph-bulletin/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/quakestrikeph-bulletin/astro.config.mjs apps/quakestrikeph-bulletin/tsconfig.json ./
COPY apps/quakestrikeph-bulletin/src ./src
COPY apps/quakestrikeph-bulletin/public ./public
ARG PUBLIC_CLERK_PUBLISHABLE_KEY
ENV PUBLIC_CLERK_PUBLISHABLE_KEY=$PUBLIC_CLERK_PUBLISHABLE_KEY
RUN pnpm run check && pnpm run build && pnpm prune --prod

FROM node:24.21.0-bookworm-slim
ENV NODE_ENV=production HOST=0.0.0.0 PORT=4321
WORKDIR /app
COPY --from=build --chown=node:node /app/package.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
USER node
EXPOSE 4321
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD node -e "fetch('http://127.0.0.1:4321/', { signal: AbortSignal.timeout(4000) }).then(r => { if (!r.ok) process.exit(1) }).catch(() => process.exit(1))"
CMD ["node", "./dist/server/entry.mjs"]
