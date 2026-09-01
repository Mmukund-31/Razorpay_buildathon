import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Proxies /api to the backend so the dashboard can call relative paths in both dev and prod
// (docker-compose's nginx/static serving, added in Phase 14, mirrors this same /api prefix).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
