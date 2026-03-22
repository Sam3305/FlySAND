import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },

  build: {
    target: "es2020",
    // Split vendor bundles for better caching
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react":    ["react", "react-dom"],
          "vendor-charts":   ["recharts"],
          "vendor-state":    ["zustand"],
          "vendor-utils":    ["lodash"],
          "vendor-icons":    ["lucide-react"],
        },
      },
    },
  },

  // Explicit optimisation hints for dev server
  optimizeDeps: {
    include: ["react", "react-dom", "recharts", "zustand", "lodash", "lucide-react"],
  },
});
