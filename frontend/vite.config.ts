import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import { defineConfig, loadEnv } from "vite";
import viteReact from "@vitejs/plugin-react";

/// <reference types="vitest" />

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.API_PROXY_TARGET || "http://localhost:8000";
  // SSR-side fetches read process.env.CRYOET_API_BASE_URL; mirror API_PROXY_TARGET into it
  // so a single .env.local var configures both the browser proxy and the SSR base URL.
  process.env.CRYOET_API_BASE_URL ??= apiTarget;

  // ---------------------------------------------------------------------------
  // DEV-ONLY reverse proxy for in-process Neuroglancer.
  //
  // IMPORTANT: this proxy ONLY exists in the Vite dev server. In production
  // (the built/`srvx` server, Docker, etc.) Neuroglancer is reached directly on
  // its own port — `docker-compose.yml` maps 8050:8050 — so none of this runs.
  // If you ever want prod parity behind a single ingress, replicate this prefix
  // proxying in nginx / the prod server instead.
  //
  // The proxied prefixes are Neuroglancer's fixed root paths (from its Tornado
  // route table): viewer app + bundles (/v), volume info & data chunks
  // (/neuroglancer), the long-lived state event stream (/events, SSE), and the
  // state/action/response/credentials channels.
  const ngTarget =
    env.NEUROGLANCER_PROXY_TARGET ||
    `http://127.0.0.1:${env.NEUROGLANCER_PORT || 8050}`;
  const ngPaths = [
    "/v",
    "/neuroglancer",
    "/events",
    "/state",
    "/action",
    "/volume_response",
    "/credentials",
  ];
  const neuroglancerDevProxy = Object.fromEntries(
    ngPaths.map((p) => [`^${p}/`, { target: ngTarget, ws: true }]),
  );

  return {
    server: {
      port: Number(env.FRONTEND_PORT) || 3000,
      host: true,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
        // DEV-ONLY: Neuroglancer reverse proxy (see comment above). Not present
        // in any production build.
        ...neuroglancerDevProxy,
      },
    },
    ssr: {
      noExternal: ["@mui/*"],
    },
    resolve: {
      tsconfigPaths: true,
    },
    plugins: [tanstackStart(), viteReact()],
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
    },
  };
});
