import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  base: process.env.GITHUB_PAGES ? '/swim-coach/' : '/',
  define: {
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version),
  },
  plugins: [
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon-192.png', 'icon-512.png', 'icon-maskable-192.png', 'icon-maskable-512.png'],
      manifest: {
        name: 'swim-coach',
        short_name: 'swim-coach',
        description: "Renee's training plan, read-only, on your phone.",
        display: 'standalone',
        theme_color: '#45afc6',
        background_color: '#45afc6',
        start_url: '.',
        // "any" icons are the design-handoff artwork verbatim (its own rounded
        // tile); "maskable" ones re-seat the figure inside the 80% safe zone so
        // Android's circle crop doesn't clip the wings/tail.
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icon-maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: 'icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // data/*.json (the exported plan) lands in dist/data/ via public/ and
        // matches this glob (json extension), so it's precached for offline
        // load along with the rest of the app shell.
        globPatterns: ['**/*.{js,css,html,ico,png,svg,json}'],
        navigateFallback: 'index.html',
        // The Coach tab's /api/chat and /health calls go to a configurable,
        // usually cross-origin backend URL (see src/api.js) and must never
        // be served from cache -- chat needs a live network round trip
        // every time. navigateFallback is explicitly scoped away from /api/
        // as a second line of defense in case the backend is ever
        // same-origin.
        navigateFallbackDenylist: [/^\/api\//],
        // /api/plan is the one exception: the Plan tab now fetches the live
        // per-identity plan (see main.js's loadPlan / api.js's fetchPlan)
        // instead of a static baked data/<slug>.json, so it needs its own
        // cache to keep the offline-first Plan tab working. NetworkFirst
        // always tries the network first (so a signed-in athlete gets their
        // current plan) and only falls back to the last cached response when
        // offline -- unlike /api/chat, this is safe to cache since a stale
        // plan is still useful and a fresh fetch is preferred whenever
        // there's a connection.
        runtimeCaching: [
          {
            urlPattern: /\/api\/plan(\?.*)?$/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-plan-cache',
              networkTimeoutSeconds: 6,
            },
          },
        ],
      },
    }),
  ],
  test: {
    environment: 'node',
    include: ['tests/unit/**/*.test.js'],
  },
});
