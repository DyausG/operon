import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build → dist/ (served by FastAPI). During `npm run dev`, proxy API + WS to the
// backend on :8000 so the dashboard hot-reloads against the live engine.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", assetsDir: "assets", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
