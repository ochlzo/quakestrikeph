FROM node:24.21.0-bookworm-slim AS build
WORKDIR /app
COPY apps/backend-api/package.json apps/backend-api/package-lock.json ./
RUN npm ci
COPY apps/backend-api/tsconfig.json ./
COPY apps/backend-api/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:24.21.0-bookworm-slim
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build --chown=node:node /app/package.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist/src ./dist/src
USER node
EXPOSE 3000
CMD ["node", "dist/src/server.js"]
