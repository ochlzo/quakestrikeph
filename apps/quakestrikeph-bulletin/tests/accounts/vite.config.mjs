import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
const path = (relative) => fileURLToPath(new URL(relative, import.meta.url));
export default {
  cacheDir: path('../../node_modules/.vite-accounts'),
  root: path('./'), publicDir: path('../../public'), plugins: [tailwindcss()],
  resolve: { alias: [
    { find: /^@clerk\/react\/legacy$/, replacement: path('./clerk-fixture.tsx') },
    { find: /^@clerk\/react$/, replacement: path('./clerk-fixture.tsx') },
    { find: '@', replacement: path('../../src') },
  ] },
  esbuild: { jsx: 'automatic' },
  define: { 'import.meta.env.PUBLIC_CLERK_PUBLISHABLE_KEY': JSON.stringify('FIXTURE_ONLY') },
  server: { host: '127.0.0.1', port: 4332, strictPort: true },
};
