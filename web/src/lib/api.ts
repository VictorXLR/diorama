import type {
  KbAnalysis,
  KbArtifact,
  KbRepository,
  QueryKind,
  QueryResponse,
} from '@/types/context';

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

/** Run a deterministic codebase query (graph / connectivity / architecture / table / changes). */
export function runCodebaseQuery<T = unknown>(
  kind: QueryKind,
  options: { table?: string; force?: boolean } = {},
): Promise<QueryResponse<T>> {
  const params = new URLSearchParams();
  if (options.table) params.set('table', options.table);
  if (options.force) params.set('force', 'true');
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<QueryResponse<T>>(`/api/query/${kind}${suffix}`);
}

/** Repositories the knowledge base has analyses for, most recently indexed first. */
export function listKnowledgeRepositories(): Promise<{ repositories: KbRepository[] }> {
  return apiFetch<{ repositories: KbRepository[] }>('/api/kb/repos');
}

/** Analysis history, newest first, optionally filtered to one repository. */
export function listKnowledgeAnalyses(
  repoId?: string,
  limit = 100,
): Promise<{ analyses: KbAnalysis[] }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (repoId) params.set('repo_id', repoId);
  return apiFetch<{ analyses: KbAnalysis[] }>(`/api/kb/analyses?${params.toString()}`);
}

/** Saved artifacts (exported scenes and other durable outputs). */
export function listKnowledgeArtifacts(repoId?: string): Promise<{ artifacts: KbArtifact[] }> {
  const suffix = repoId ? `?repo_id=${encodeURIComponent(repoId)}` : '';
  return apiFetch<{ artifacts: KbArtifact[] }>(`/api/kb/artifacts${suffix}`);
}
