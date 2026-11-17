// Run against the built Bulletin listening at BULLETIN_URL (default localhost:4321).
const { test } = require('node:test');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { mkdtemp, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');

const run = promisify(execFile);
const scripts = [
  'bulletin-sidebar', 'earthquake-cache', 'event-readability', 'magnitude-filter',
  'map-worker', 'mobile-map', 'search-loading',
];

for (const name of scripts) {
  test(name, async () => {
    // Each script writes screenshots relative to its working directory.
    const directory = await mkdtemp(join(tmpdir(), 'bulletin-browser-'));
    try {
      const { stdout } = await run(process.execPath, [
        '--experimental-strip-types', join(__dirname, name + '.cjs'),
      ], { cwd: directory, timeout: 150000, windowsHide: true });
      process.stdout.write(stdout);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
}
