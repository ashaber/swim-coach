// Bundles the PWA's two typefaces (Bioluminescent Dusk design system:
// Manrope for display/headings/labels, Inter for body/UI text) via
// @fontsource so vite ships the woff2 files locally and workbox precaches
// them -- this app is offline-first, so hot-linking Google Fonts (as the
// design handoff's own reference files do) is not an option here.
// Only the weights actually used in index.html's CSS are imported, and only
// the latin subset (the app is English-only) rather than the full
// unicode-range set (cyrillic/greek/vietnamese/etc.) that the unscoped
// per-weight imports would otherwise pull in -- keeps the precache payload
// lean for an offline-first PWA.
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/inter/latin-700.css';
import '@fontsource/manrope/latin-700.css';
import '@fontsource/manrope/latin-800.css';
