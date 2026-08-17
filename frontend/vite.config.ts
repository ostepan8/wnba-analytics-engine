import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Build output lands where FastAPI already serves static files, so the app and
// the API it calls are one origin: no CORS grant, no configured API base, and
// the same behaviour over the tunnel, over the tailnet, and on localhost.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../wnba_engine/api/static",
    emptyOutDir: true,
    // Source maps are ~1MB and only useful to someone who already has the repo.
    sourcemap: false,
  },
  server: {
    // `npm run dev` proxies API calls to a locally-tunnelled API, so the dev
    // server behaves like production without a second base URL to configure.
    proxy: Object.fromEntries(
      ["/api", "/docs", "/openapi.json"]
        .map((path) => [path, { target: "http://127.0.0.1:18090", changeOrigin: true }]),
    ),
  },
});
