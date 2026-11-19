import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
const path = (relative) => fileURLToPath(new URL(relative, import.meta.url));
export default {
  cacheDir: path('../../node_modules/.vite-accounts'),
  root: path('./'), publicDir: path('../../public'), plugins: [tailwindcss()],
  // Convert these CommonJS dependencies before serving the isolated fixture.
  optimizeDeps: { include: [
    'react/jsx-runtime',
    'react-dom',
    '@base-ui/react > use-sync-external-store/shim',
    '@base-ui/react > use-sync-external-store/shim/with-selector',
  ] },
  resolve: { alias: [
    { find: /^astro:transitions\/client$/, replacement: path('./navigation-fixture.ts') },
    { find: /^@clerk\/react\/legacy$/, replacement: path('./clerk-fixture.tsx') },
    { find: /^@clerk\/react$/, replacement: path('./clerk-fixture.tsx') },
    { find: '@', replacement: path('../../src') },
  ] },
  esbuild: { jsx: 'automatic' },
  define: { 'import.meta.env.PUBLIC_CLERK_PUBLISHABLE_KEY': JSON.stringify('FIXTURE_ONLY') },
  server: { host: '127.0.0.1', port: 4332, strictPort: true },
};
