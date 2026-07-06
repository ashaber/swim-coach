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
      includeAssets: ['icon.svg', 'icon-192.png', 'icon-512.png'],
      manifest: {
        name: 'swim-coach',
        short_name: 'swim-coach',
        description: "Renee's training plan, read-only, on your phone.",
        display: 'standalone',
        theme_color: '#0e7c86',
        background_color: '#eef2f3',
        start_url: '.',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any maskable' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
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
        // every time. runtimeCaching stays empty (no route matches /api/*,
        // so those requests just pass through the service worker
        // untouched) and navigateFallback is explicitly scoped away from
        // /api/ as a second line of defense in case the backend is ever
        // same-origin.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [],
      },
    }),
  ],
  test: {
    environment: 'node',
    include: ['tests/unit/**/*.test.js'],
  },
});
