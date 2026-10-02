import { defineConfig } from "astro/config";
import node from "@astrojs/node";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  output: "server",
  devToolbar: { enabled: false },
  adapter: node({ mode: "standalone" }),
  integrations: [react()],
  vite: {
    plugins: [tailwindcss()],
    worker: {
      plugins: () => [{
        name: "retain-maplibre-worker-initialization",
        transform(code, id) {
          // MapLibre marks dist modules side-effect-free, but this one installs its worker API.
          if (id.replaceAll("\\", "/").endsWith("/maplibre-gl-worker.mjs")) {
            return { code, moduleSideEffects: "no-treeshake" };
          }
        },
      }],
    },
    server: {
      proxy: {
        "/api/v1/account": {
          target: process.env.ACCOUNT_API_TARGET || "http://127.0.0.1:3000",
          changeOrigin: false,
        },
        "/api/v1": {
          target: "https://quakestrikeph.qzz.io",
          changeOrigin: true,
        },
      },
    },
  },
});
