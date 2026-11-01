import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built output is served by the FastAPI container as static files
// (CL-48): index.html at / and /analyze, hashed assets at /assets/.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist",
    assetsDir: "assets",
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
