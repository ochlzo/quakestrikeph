ARG BASE_IMAGE_TAG=local-build-required
FROM node:24.21.0-bookworm-slim AS ui
WORKDIR /app/apps/quakestrikeph-alert-testing
RUN npm install -g pnpm@11.11.0
COPY packages/ui /app/packages/ui
COPY packages/contracts /app/packages/contracts
COPY apps/quakestrikeph-alert-testing/package.json apps/quakestrikeph-alert-testing/pnpm-lock.yaml apps/quakestrikeph-alert-testing/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/quakestrikeph-alert-testing/astro.config.mjs apps/quakestrikeph-alert-testing/tsconfig.json ./
COPY apps/quakestrikeph-alert-testing/src ./src
COPY apps/quakestrikeph-alert-testing/public ./public
RUN pnpm check && pnpm build

FROM quakestrike-workers:${BASE_IMAGE_TAG} AS runtime
COPY --from=ui --chown=quakestrike:quakestrike /app/apps/quakestrikeph-alert-testing/dist /app/alert-testing-ui
CMD ["python", "-m", "quakestrike.alert_testing.runtime", "--static-directory", "/app/alert-testing-ui"]
