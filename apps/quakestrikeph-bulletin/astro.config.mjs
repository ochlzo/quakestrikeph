import { defineConfig } from "astro/config";
import node from "@astrojs/node";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from 'node:url';

export default defineConfig({
  output: "server",
  devToolbar: { enabled: false },
  adapter: node({ mode: "standalone" }),
  integrations: [react()],
  vite: {
    // Astro 7.3.5 imports a missing, type-only runtime module. Keep its empty
    // shim out of dependency optimization as well as the production bundle.
    optimizeDeps: {
      exclude: ['astro/virtual-modules/transitions-types.js'],
      include: [
        'react-aria-components > react-aria > use-sync-external-store/shim',
        'react-aria-components > react-aria > use-sync-external-store/shim/with-selector',
      ],
    },
    resolve: { alias: [{
      find: '../transitions/types.js',
      replacement: fileURLToPath(new URL('./src/lib/astro-transition-types.ts', import.meta.url)),
    }] },
    plugins: [tailwindcss()],
    worker: {
      plugins: () => [
        {
          name: "retain-maplibre-worker-initialization",
          transform(code, id) {
            // MapLibre marks dist modules side-effect-free, but this one installs its worker API.
            if (id.replaceAll("\\", "/").endsWith("/maplibre-gl-worker.mjs")) {
              return { code, moduleSideEffects: "no-treeshake" };
            }
          },
        },
      ],
    },
    server: {
      proxy: {
        "/api/v1/account": {
          target: process.env.ACCOUNT_API_TARGET || "http://127.0.0.1:3000",
          changeOrigin: false,
        },
        "/api/v1": {
          target: process.env.API_TARGET || "https://quakestrikeph.com",
          changeOrigin: true,
        },
      },
      watch: {
        ignored: ["**/.pnpm-store/**"],
        usePolling: process.env.DEV_USE_POLLING === "true",
        interval: 300,
      },
    },
  },
});
