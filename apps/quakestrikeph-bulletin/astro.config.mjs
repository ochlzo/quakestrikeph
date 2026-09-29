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
    server: {
      proxy: {
        "/api/v1": {
          target: "https://quakestrikeph.qzz.io",
          changeOrigin: true,
        },
      },
    },
  },
});
