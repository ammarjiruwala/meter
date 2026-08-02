/**
 * A very short in-process cache for the polled endpoints.
 *
 * The dashboard's two live panels poll every 3 seconds. One viewer is nothing; a
 * room of judges each with the page open is the same query repeated N times a
 * second against a pool of four connections, and they are all asking for the
 * identical rows — nothing about the answer is per-viewer.
 *
 * A 2-second TTL collapses that to at most one query per endpoint per 2s no matter
 * how many tabs are open, which makes the load flat in viewers instead of linear.
 *
 * Deliberately shorter than the 3s poll interval, so a client that waited its full
 * interval still gets a fresh read rather than being served a stale entry and
 * effectively polling at 4s. The panels stay live: worst case a row is 2s old,
 * against a poll that was already going to be up to 3s behind.
 *
 * In-process and per-instance, which is fine — `dashboard/fly.toml` runs a single
 * machine (`min_machines_running = 1`, `auto_stop_machines = false`). If that ever
 * scales out, each instance keeps its own cache and the bound becomes one query per
 * endpoint per 2s *per instance*, which is still the property we want.
 *
 * Stashed on globalThis for the same reason the pool is: Next reloads modules on
 * every edit in dev, and a fresh Map per reload would silently disable the cache.
 */
type Entry = { at: number; value: Promise<unknown> };

const globalForCache = globalThis as unknown as {
  meterPollCache?: Map<string, Entry>;
};

const store = (globalForCache.meterPollCache ??= new Map<string, Entry>());

const TTL_MS = 2_000;

export async function cached<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = store.get(key);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.value as Promise<T>;

  // The *promise* is cached, not the resolved value. Several requests arriving in
  // the same tick would otherwise all miss and all issue their own query — the
  // stampede the cache exists to prevent. They now share one in-flight read.
  const value = load();
  store.set(key, { at: Date.now(), value });

  try {
    return (await value) as T;
  } catch (err) {
    // A failed read must not be served to everyone else for the next 2 seconds.
    store.delete(key);
    throw err;
  }
}
