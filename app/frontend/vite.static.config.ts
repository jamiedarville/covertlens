import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// CL-66: static, zero-server Analyze page (`npm run build:static`).
// Relative base so the output works from any static host path;
// public-static/ holds the Python bundle, examples, the Pyodide
// runtime and the service worker (written by scripts/build-static.mjs).
export default defineConfig({
  plugins: [react()],
  base: "./",
  publicDir: "public-static",
  worker: { format: "es" },
  build: {
    outDir: "dist-static",
    emptyOutDir: true,
    assetsDir: "assets",
    rollupOptions: { input: "static.html" },
  },
});
