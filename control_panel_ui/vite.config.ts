import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "https://127.0.0.1:8765",
        secure: false,
      },
    },
  },
  build: {
    outDir: "../control_panel_dist",
    emptyOutDir: true,
  },
});
