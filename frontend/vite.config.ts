/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Dev: `npm run dev` on :5173 proxies /api to `uv run training api` on :8000.
// Production: `npm run build` → dist/, served by FastAPI (`training api --serve-frontend`) on one port.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "Training Analytics",
        short_name: "Tréning",
        description: "Záťaž, forma, spánok a plán tréningov z Garminu",
        lang: "sk",
        theme_color: "#0d0f12",
        background_color: "#0d0f12",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallbackDenylist: [/^\/api\//, /^\/docs/, /^\/openapi\.json/],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
      },
    }),
  ],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
