import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend origin is configurable so the same build works locally and on Vultr.
const API_TARGET = process.env.VITE_API_TARGET || "http://localhost:8000";
const proxy = { "/api": { target: API_TARGET, changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  // proxy on BOTH dev and preview so `npm run dev` and `npm run preview` both reach the API
  server: { port: 3000, host: true, proxy },
  preview: { port: 3000, host: true, proxy },
});
