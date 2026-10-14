let pending = 0;
export const loadingListeners = new Set<() => void>();
export const isLoading = () => pending > 0;

// Requests have no measurable percentage; keep estimated progress below completion.
export const estimatedProgress = (elapsedMs: number, start = 0.08) =>
  0.94 - (0.94 - start) * Math.exp(-Math.max(0, elapsedMs) / 1800);

export async function trackLoading<T>(request: () => Promise<T>, visible = true): Promise<T> {
  if (!visible) return request();
  pending++;
  loadingListeners.forEach(listener => listener());
  try {
    return await request();
  } finally {
    pending--;
    loadingListeners.forEach(listener => listener());
  }
}
