import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowUp, Folder, FolderOpen, HardDrive, Loader2, X } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import type {
  BindWorkspaceResponse,
  DirectoryEntry,
  WorkspaceBrowseResponse,
  WorkspaceStatusResponse,
} from '@/types/context';

export interface WorkspacePickerProps {
  onClose: () => void;
  /** Called after the server binds and indexes a new directory. */
  onWorkspaceBound: (summary: BindWorkspaceResponse) => void;
}

/**
 * Server-side directory picker: browse folders, bind one as the workspace
 * root, and let the backend index it so the board renders its map.
 */
export function WorkspacePicker({ onClose, onWorkspaceBound }: WorkspacePickerProps): React.JSX.Element {
  const [currentPath, setCurrentPath] = useState<string>('');
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [boundRoot, setBoundRoot] = useState<string | null>(null);
  const [pathInput, setPathInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isBinding, setIsBinding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const browse = useCallback(async (path?: string): Promise<void> => {
    setIsLoading(true);
    setError(null);
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : '';
      const result = await apiFetch<WorkspaceBrowseResponse>(`/api/workspace/browse${query}`);
      setCurrentPath(result.path);
      setParentPath(result.parent);
      setEntries(result.entries);
      setPathInput(result.path);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Could not browse that path.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Mounted only while open: fetch the current binding, then browse from the
  // workspace root (or the server's home directory when nothing is bound yet).
  useEffect(() => {
    apiFetch<WorkspaceStatusResponse>('/api/workspace')
      .then((status) => {
        setBoundRoot(status.root);
        return browse(status.root ?? undefined);
      })
      .catch((exc: unknown) => {
        setError(exc instanceof Error ? exc.message : 'Could not reach the Diorama server.');
      });
  }, [browse]);

  const handleBind = useCallback(
    async (path: string): Promise<void> => {
      setIsBinding(true);
      setError(null);
      try {
        const summary = await apiFetch<BindWorkspaceResponse>('/api/workspace/bind', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path }),
        });
        setBoundRoot(summary.root);
        onWorkspaceBound(summary);
        if (summary.warning) {
          setError(summary.warning);
          setIsBinding(false);
          return;
        }
        onClose();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : 'Could not bind that directory.');
      } finally {
        setIsBinding(false);
      }
    },
    [onClose, onWorkspaceBound],
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm">
      <div className="flex max-h-[80vh] w-full max-w-xl flex-col rounded-2xl border border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <div className="flex items-center gap-2 font-semibold text-slate-800 dark:text-slate-100">
            <HardDrive className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
            <span>Choose a directory to index</span>
          </div>
          <button
            className="rounded-lg p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            onClick={onClose}
            title="Close"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <div className="flex items-center gap-1.5">
            <input
              className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-800 focus:border-indigo-400 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              onChange={(event) => setPathInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  void browse(pathInput.trim());
                }
              }}
              placeholder="/absolute/path/to/repo"
              type="text"
              value={pathInput}
            />
            <button
              className="shrink-0 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              disabled={isLoading || pathInput.trim().length === 0}
              onClick={() => void browse(pathInput.trim())}
              type="button"
            >
              Browse
            </button>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
            {boundRoot ? (
              <span>
                Currently bound: <span className="font-medium text-slate-700 dark:text-slate-300">{boundRoot}</span>
              </span>
            ) : (
              <span>No directory bound yet — pick one to index and map it on the board.</span>
            )}
          </div>
        </div>

        <div className="min-h-48 flex-1 overflow-y-auto px-2 py-2">
          {isLoading ? (
            <div className="flex h-48 items-center justify-center text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <div className="flex flex-col">
              {parentPath && (
                <button
                  className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-slate-500 transition-colors hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
                  onClick={() => void browse(parentPath)}
                  type="button"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                  <span className="truncate font-medium">.. {parentPath}</span>
                </button>
              )}
              {entries.length === 0 && !isLoading && (
                <div className="px-3 py-6 text-center text-xs text-slate-400">
                  No subdirectories here. You can index this folder directly.
                </div>
              )}
              {entries.map((entry) => (
                <button
                  className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-slate-700 transition-colors hover:bg-indigo-50 dark:text-slate-300 dark:hover:bg-indigo-950/60"
                  key={entry.path}
                  onClick={() => void browse(entry.path)}
                  type="button"
                >
                  <Folder className="h-3.5 w-3.5 shrink-0 text-indigo-500 dark:text-indigo-400" />
                  <span className="truncate font-medium">{entry.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {error && (
          <div className="flex items-start gap-2 border-t border-slate-200 bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:border-slate-800 dark:bg-amber-950/40 dark:text-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex items-center justify-between gap-2 border-t border-slate-200 px-4 py-3 dark:border-slate-800">
          <span className="min-w-0 truncate text-[11px] text-slate-500 dark:text-slate-400" title={currentPath}>
            {currentPath || '—'}
          </span>
          <button
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            disabled={isBinding || currentPath.length === 0}
            onClick={() => void handleBind(currentPath)}
            type="button"
          >
            {isBinding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FolderOpen className="h-3.5 w-3.5" />}
            <span>{isBinding ? 'Indexing…' : 'Index this directory'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

export default WorkspacePicker;
