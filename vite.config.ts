import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// For a GitHub Pages *project* site the app is served from
// https://<user>.github.io/<repo>/ , so assets must be prefixed with the repo
// name in production. Locally we serve from root. Override with VITE_BASE if the
// repo is named differently.
const base = process.env.VITE_BASE ?? (process.env.NODE_ENV === "production" ? "/ai-math-tracker/" : "/");

export default defineConfig({
  base,
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ["echarts"],
          motion: ["motion"],
        },
      },
    },
  },
});
