import {
  Compass,
  Eraser,
  FolderOpen,
  Maximize2,
  Moon,
  PanelLeft,
  Radio,
  RefreshCw,
  Sun,
} from 'lucide-react';
import type React from 'react';
import type { Theme } from '@/lib/store';
import type { ConnectionState } from '@/types/context';

interface HeaderNavProps {
  connectionState: ConnectionState;
  onClearBoard: () => void;
  onFitView: () => void;
  /** Opens the server-side directory picker to bind and index a new root. */
  onChooseDirectory: () => void;
  onRefreshCodebaseMap: () => void;
  onToggleTheme: () => void;
  theme: Theme;
  workspaceTitle: string;
  /** Number of elements currently on the whiteboard. */
  boardElementCount: number;
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  activeView: 'landing' | 'workspace';
  onNavigateLanding: () => void;
}

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  connecting: 'Connecting',
  connected: 'Connected',
  reconnecting: 'Reconnecting',
  disconnected: 'Offline',
};

function getConnectionIndicatorClass(connectionState: ConnectionState): string {
  if (connectionState === 'connected') {
    return 'bg-emerald-500 shadow-xs shadow-emerald-500/50';
  }

  if (connectionState === 'disconnected') {
    return 'bg-slate-400';
  }

  return 'bg-amber-400';
}

const HEADER_BUTTON_CLASS =
  'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white';

export function HeaderNav({
  connectionState,
  onClearBoard,
  onFitView,
  onChooseDirectory,
  onRefreshCodebaseMap,
  onToggleTheme,
  theme,
  workspaceTitle,
  boardElementCount,
  isSidebarOpen,
  onToggleSidebar,
  activeView,
  onNavigateLanding,
}: HeaderNavProps): React.JSX.Element {
  const isDark = theme === 'dark';

  return (
    <header className="z-20 flex h-14 shrink-0 select-none items-center justify-between border-b border-slate-200/90 bg-white/95 px-4 shadow-2xs backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/95">
      {/* Left Section: Sidebar Toggle, Brand Logo Button leading to Landing Page */}
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <button
          aria-label={isSidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
          className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          onClick={onToggleSidebar}
          title="Toggle conversations sidebar"
          type="button"
        >
          <PanelLeft className="h-4 w-4" />
        </button>

        <button
          aria-label="Go to landing page"
          className="group flex items-center gap-2.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-slate-100 focus:outline-hidden dark:hover:bg-slate-800/60"
          onClick={onNavigateLanding}
          title="Back to Diorama Landing Page"
          type="button"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-sm ring-1 ring-white/20 transition-transform group-hover:scale-105">
            <Compass className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h1 className="text-sm font-bold tracking-tight text-slate-900 group-hover:text-indigo-600 dark:text-slate-100 dark:group-hover:text-indigo-400">
                Diorama
              </h1>
              <span className="rounded bg-indigo-50 px-1 py-0.2 text-[9px] font-semibold text-indigo-600 dark:bg-indigo-950/80 dark:text-indigo-300">
                studio
              </span>
            </div>
            <p className="text-[10px] font-medium text-slate-500 dark:text-slate-400">Visual Codebase Harness</p>
          </div>
        </button>

        {/* Active Context / Workspace badge */}
        {workspaceTitle && (
          <div className="hidden min-w-0 items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700 md:flex dark:border-slate-800 dark:bg-slate-800/60 dark:text-slate-300">
            <Radio className="h-3 w-3 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <span className="max-w-64 truncate font-medium">{workspaceTitle}</span>
            {activeView === 'workspace' && (
              <span className="rounded bg-slate-200/80 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-700/80 dark:text-slate-300">
                {boardElementCount} {boardElementCount === 1 ? 'element' : 'elements'}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Right Section: Connection, Refresh Map, Clear Board, Theme */}
      <div className="flex items-center gap-1 sm:gap-2">
        <div className="flex items-center gap-1.5 rounded-full border border-slate-200/80 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-800/60 dark:text-slate-400">
          <span className={`h-2 w-2 rounded-full ${getConnectionIndicatorClass(connectionState)}`} />
          <span className="hidden sm:inline">{CONNECTION_LABELS[connectionState]}</span>
        </div>

        {activeView === 'workspace' && (
          <>
            <button
              className={HEADER_BUTTON_CLASS}
              onClick={onChooseDirectory}
              title="Choose a directory on the server to bind and index"
              type="button"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Choose directory</span>
            </button>
            <button
              className={HEADER_BUTTON_CLASS}
              disabled={connectionState !== 'connected'}
              onClick={onRefreshCodebaseMap}
              title="Re-index codebase and regenerate diagram"
              type="button"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Refresh map</span>
            </button>
            <button
              className={HEADER_BUTTON_CLASS}
              onClick={onFitView}
              title="Fit view to whiteboard content"
              type="button"
            >
              <Maximize2 className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Fit view</span>
            </button>
            <button
              className={HEADER_BUTTON_CLASS}
              onClick={onClearBoard}
              title="Clear generated whiteboard elements"
              type="button"
            >
              <Eraser className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Clear board</span>
            </button>
          </>
        )}

        <button
          aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          className={HEADER_BUTTON_CLASS}
          onClick={onToggleTheme}
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          type="button"
        >
          {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
        </button>
      </div>
    </header>
  );
}

export default HeaderNav;
