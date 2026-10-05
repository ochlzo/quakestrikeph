// Bump the version when display-name rules change. Snapshot URLs distinguish tile releases.
export const labelCacheName = "quakestrike-label-tiles-v1";
const maxTiles = 16;
const maxTileBytes = 2 * 1024 * 1024;
let writes = Promise.resolve();

async function openCache(): Promise<Cache | undefined> {
  try {
    if (typeof caches !== "undefined") return await caches.open(labelCacheName);
  } catch {
    // Private browsing, quota limits, or unavailable storage must not prevent map loading.
  }
  return undefined;
}

export async function readLabelTile(url: string): Promise<Response | undefined> {
  try {
    return await (await openCache())?.match(url);
  } catch {
    return undefined;
  }
}

export function cacheLabelTile(url: string, data: ArrayBuffer, headers: Headers): Promise<void> {
  if (data.byteLength > maxTileBytes || /\b(no-store|no-cache|private)\b/i.test(headers.get("Cache-Control") || "")) {
    return Promise.resolve();
  }
  // Copy the bytes before MapLibre transfers and detaches the returned tile buffer.
  const response = new Response(data, { headers });
  writes = writes.then(async () => {
    const cache = await openCache();
    if (!cache) return;
    try {
      await cache.put(url, response);
      // FIFO: retain 16 tiles of at most 2 MiB each (32 MiB of tile bodies).
      const keys = await cache.keys();
      await Promise.all(keys.slice(0, Math.max(0, keys.length - maxTiles)).map((key) => cache.delete(key)));
    } catch {
      // Do not accumulate new entries if eviction is unavailable.
      await cache.delete(url).catch(() => {});
    }
  }).catch(() => { /* Keep the successfully transformed tile usable if caching fails. */ });
  return writes;
}
