import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  define: {
    global: "globalThis",
    "process.env": {},
  },
  resolve: {
    alias: {
      // ketcher-core 的 ESM 里 import { EventEmitter } from 'events'，
      // 浏览器没有这个内建模块，用 npm 上的垫片替掉
      events: "events/",
      process: "process/browser",
      buffer: "buffer",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 8192,
    commonjsOptions: { transformMixedEsModules: true },
  },
  server: { port: 5199, strictPort: true },
});
