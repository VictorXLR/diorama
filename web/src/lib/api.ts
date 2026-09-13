// Default to the origin that served the app, so the built bundle talks to
// whatever host/port is serving it. Override with VITE_API_BASE_URL for split
// deployments (or the Vite dev server, which proxies to the backend).
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? window.location.origin;

export const WEBSOCKET_URL: string =
  import.meta.env.VITE_WS_URL ?? `${API_BASE_URL.replace(/^http/, 'ws').replace(/\/$/, '')}/ws`;

/** Fetch helper that surfaces HTTP errors as rejected promises with detail text. */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) {
        detail = body.detail;
      }
    } catch {
      // Not a JSON error body; keep the status text.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}
