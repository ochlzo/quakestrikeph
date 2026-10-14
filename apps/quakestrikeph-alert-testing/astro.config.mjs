import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  output: "static",
  devToolbar: { enabled: false },
  integrations: [react()],
  vite: {
    plugins: [tailwindcss()],
    worker: {
      plugins: () => [{
        name: "retain-maplibre-worker-initialization",
        transform(code, id) {
          // MapLibre marks dist modules side-effect-free, but this installs its worker API.
          if (id.replaceAll("\\", "/").endsWith("/maplibre-gl-worker.mjs")) {
            return { code, moduleSideEffects: "no-treeshake" };
          }
        },
      }],
    },
  },
});
