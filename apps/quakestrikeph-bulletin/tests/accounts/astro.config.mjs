// Separate fixture server for real Astro client navigation. Never used by the
// application build or its normal development server.
import { defineConfig } from 'astro/config';
import base from '../../astro.config.mjs';
import { fileURLToPath } from 'node:url';
const path = relative => fileURLToPath(new URL(relative, import.meta.url));
export default defineConfig({
  ...base,
  cacheDir: './node_modules/.astro-background-fixture',
  vite: {
    ...base.vite,
    // The native Windows transform fails on the first inherited Astro tsconfig read.
    // Keep its equivalent transform settings local to this fixture.
    oxc: { tsconfig: { compilerOptions: {
      target: 'ESNext', module: 'ESNext', verbatimModuleSyntax: true,
      jsx: 'react-jsx', jsxImportSource: 'react',
    } } },
    cacheDir: path('../../node_modules/.vite-background-fixture'),
    resolve: { tsconfigPaths: false, alias: [
      ...base.vite.resolve.alias,
      { find: '@', replacement: path('../../src') },
      { find: /^@clerk\/react\/legacy$/, replacement: path('./clerk-fixture.tsx') },
      { find: /^@clerk\/react$/, replacement: path('./clerk-fixture.tsx') },
    ] },
    plugins: [...base.vite.plugins, {
      name: 'isolated-account-fetch-fixture',
      transform(code, id, options) {
        if (!options?.ssr && id.replaceAll('\\', '/').endsWith('/AccountApp.tsx'))
          return `import '/tests/accounts/channels-fixture.ts';\n${code}`;
      },
    }],
  },
});
