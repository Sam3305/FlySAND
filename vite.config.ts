import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },

  build: {
    target: "es2020",
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react":  ["react", "react-dom"],
          "vendor-state":  ["zustand"],
          "vendor-icons":  ["lucide-react"],
        },
      },
    },
  },

  optimizeDeps: {
    include: ["react", "react-dom", "zustand", "lucide-react"],
  },
});
