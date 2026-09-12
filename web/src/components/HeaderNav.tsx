import { Eraser, Moon, Radio, RefreshCw, SquareDashedMousePointer, Sun } from 'lucide-react';
import type { Theme } from '@/lib/store';
import type { ConnectionState } from '@/types/context';

interface HeaderNavProps {
  connectionState: ConnectionState;
  onClearBoard: () => void;
  onRefreshCodebaseMap: () => void;
  onToggleTheme: () => void;
  theme: Theme;
  workspaceTitle: string;
}

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  connecting: 'Connecting',
  connected: 'Connected',
  reconnecting: 'Reconnecting',
  disconnected: 'Offline',
};

function getConnectionIndicatorClass(connectionState: ConnectionState): string {
  if (connectionState === 'connected') {
    return 'bg-emerald-500';
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
  onRefreshCodebaseMap,
  onToggleTheme,
  theme,
  workspaceTitle,
}: HeaderNavProps): React.JSX.Element {
  const isDark = theme === 'dark';

  return (
    <header className="z-10 flex h-14 shrink-0 select-none items-center justify-between border-b border-slate-200/90 bg-white/95 px-4 shadow-2xs backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/95">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-sm">
            <SquareDashedMousePointer className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-sm leading-none font-bold text-slate-800 dark:text-slate-100">Diorama</h1>
            <p className="text-[10px] leading-tight font-medium text-slate-500 dark:text-slate-400">Conversation canvas</p>
          </div>
        </div>

        <div className="hidden h-5 w-px bg-slate-200 sm:block dark:bg-slate-700" />

        <div className="hidden min-w-0 items-center gap-2 rounded-full border border-slate-200 bg-slate-100/90 px-3 py-1.5 text-xs text-slate-700 md:flex dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
          <Radio className="h-3.5 w-3.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
          <span className="max-w-72 truncate font-medium">{workspaceTitle}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="hidden items-center gap-1.5 text-xs text-slate-500 sm:flex dark:text-slate-400">
          <span className={`h-2 w-2 rounded-full ${getConnectionIndicatorClass(connectionState)}`} />
          {CONNECTION_LABELS[connectionState]}
        </span>
        <button
          aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          className={HEADER_BUTTON_CLASS}
          onClick={onToggleTheme}
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          type="button"
        >
          {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
        </button>
        <button
          className={HEADER_BUTTON_CLASS}
          disabled={connectionState !== 'connected'}
          onClick={onRefreshCodebaseMap}
          title="Re-index the bound workspace and refresh its codebase map"
          type="button"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Refresh map</span>
        </button>
        <button
          className={HEADER_BUTTON_CLASS}
          onClick={onClearBoard}
          title="Clear generated whiteboard content"
          type="button"
        >
          <Eraser className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Clear board</span>
        </button>
      </div>
    </header>
  );
}

export default HeaderNav;
